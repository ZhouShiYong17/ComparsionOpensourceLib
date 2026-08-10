"""Pipeline orchestration: start -> (Claude) -> resolve -> (Claude) -> finalize.

Claude never talks to this module directly; it reads *_requests.jsonl and writes
*_responses.jsonl. Everything it writes is validated before use.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import candidates as candidates_mod
import common
import compare_values
import coverage as coverage_mod
import extract
import normalize
import rules as rules_mod
import validate

PKG_ROOT = Path(__file__).resolve().parent.parent

_COMPANY_NORM_FIELDS = ["stig_description", "stig_objective_or_requirement",
                        "stig_command_or_value",
                        "company_approved_setting_or_expected_value",
                        "observed_value_or_evidence"]
_OFFICIAL_NORM_FIELDS = ["title", "check_text", "fix_text", "expected_value"]

# Fields a structuring response may extract (context_grouping is already known
# from the request itself, so it is not part of what Claude must recover).
_STRUCT_FIELDS = ["stig_description", "stig_objective_or_requirement",
                  "stig_command_or_value",
                  "company_approved_setting_or_expected_value",
                  "observed_value_or_evidence"]

_MATCHED_TIERS = ("T0", "T1", "T2")


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------

def _read_jsonl_opt(path):
    path = Path(path)
    if not path.exists():
        return []
    return common.read_jsonl(path)


def _append_jsonl(path, new_records):
    """Read the current content of an accumulating log, append, rewrite."""
    if not new_records:
        return
    existing = _read_jsonl_opt(path)
    existing.extend(new_records)
    common.write_jsonl(path, existing)


def _rule_text(rule):
    return " ".join([rule.get("title", ""), rule.get("check_text", ""),
                     rule.get("fix_text", "")])


def _context_for_row(row, doc_type, field=""):
    return {"document_type": doc_type,
            "sheet_or_section": row.get("source_reference", {}).get(
                "sheet_or_section", ""),
            "field": field}


def _finding_id(row_id, rule_id, finding_type):
    return common.finding_id(row_id, rule_id, finding_type or "deterministic")


def _ensure_match_fields(m):
    """Backfill pipeline-tracked bookkeeping fields onto a match_state record.

    candidates.generate() only produces row_id/tier/matched_rule_id/margin_flag
    /candidates; everything else here is added and persisted by this module.
    """
    m.setdefault("match_failures", 0)
    m.setdefault("semantic_failures", 0)
    m.setdefault("retried", False)
    m.setdefault("warnings", [])
    m.setdefault("row_quote", None)
    m.setdefault("rule_quote", None)
    m.setdefault("ambiguous_rule_ids", [])
    m.setdefault("verdict_done", False)
    return m


def _build_finding(row_id, rule_id, verdict, basis, deterministic, finding_type,
                    observation, interpretation, applied_rules_list,
                    match_row, company_row, official_rule,
                    approved_alignment=None):
    return {
        "finding_id": _finding_id(row_id, rule_id, finding_type),
        "row_id": row_id, "rule_id": rule_id, "verdict": verdict,
        "finding_type": finding_type, "deterministic": deterministic,
        "basis": basis, "observation": observation,
        "interpretation": interpretation, "skeptic": None,
        "disputed": False,
        "applied_rules": list(applied_rules_list or []),
        "approved_alignment": approved_alignment,
        "match": {"tier": match_row["tier"], "candidates": match_row["candidates"]},
        "company_row": {
            "original_company_text": company_row.get("original_company_text", ""),
            "source_reference": company_row.get("source_reference", {})},
        "official_rule": {
            "rule_id": official_rule.get("rule_id", rule_id),
            "title": official_rule.get("title", ""),
            "check_text": official_rule.get("check_text", ""),
            "expected_value": official_rule.get("expected_value", "")},
        "confidence": None, "human_review_needed": None,
    }


def assign_confidence(match_record, finding, skeptic_outcome):
    tier = match_record.get("tier")
    deterministic = bool(finding.get("deterministic"))
    if match_record.get("margin_flag") or match_record.get("retried"):
        return "Low"
    if tier in ("T0", "T1") and deterministic:
        return "High"
    if tier == "T2" and deterministic:
        return "High"
    if tier == "T2" and not deterministic and skeptic_outcome == "upheld":
        return "Medium"
    return "Low"


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def cmd_start(args):
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    official = extract.extract_official(args.official)
    company = extract.extract_company(args.company)
    normalize.add_normalized(official["records"], _OFFICIAL_NORM_FIELDS)
    normalize.add_normalized(company["records"], _COMPANY_NORM_FIELDS)

    registry = rules_mod.load_registry(PKG_ROOT / "rules" / "registry.json")
    doc_type = Path(args.company).suffix.lstrip(".").lower()
    _, conflicts = rules_mod.applicable_rules(
        registry, {"document_type": doc_type, "sheet_or_section": "",
                   "field": ""})

    manifest = {
        "official_file": Path(args.official).name,
        "company_file": Path(args.company).name,
        "official_sha256": common.file_sha256(args.official),
        "company_sha256": common.file_sha256(args.company),
        "started": datetime.now().isoformat(timespec="seconds"),
        "versions": common.load_versions(PKG_ROOT),
        "registry_version": registry["registry_version"],
        "rule_conflicts": conflicts,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    common.write_jsonl(run_dir / "official_rules.jsonl", official["records"])
    common.write_jsonl(run_dir / "company_rows.jsonl", company["records"])
    (run_dir / "extract_warnings.json").write_text(json.dumps(
        official["warnings"] + company["warnings"], indent=1), encoding="utf-8")

    match_state = candidates_mod.generate(company["records"], official["records"])
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)

    structuring = [
        {"row_id": r["row_id"],
         "original_company_text": r["original_company_text"],
         "context_grouping": r["context_grouping"],
         "instructions_file": "prompts/structuring.md"}
        for r in company["records"] if r["status"] == "needs-structuring"]
    common.write_jsonl(run_dir / "structuring_requests.jsonl", structuring)

    rules_by_id = {r["rule_id"]: r for r in official["records"]}
    rows_by_id = {r["row_id"]: r for r in company["records"]}
    matching = [
        {"row_id": m["row_id"], "row": rows_by_id[m["row_id"]],
         "candidates": [rules_by_id[c["rule_id"]] | {"_score": c["score"]}
                        for c in m["candidates"]],
         "instructions_file": "prompts/matching.md"}
        for m in match_state
        if m["tier"] is None and m["candidates"]
        and rows_by_id[m["row_id"]]["status"] == "ok"]
    common.write_jsonl(run_dir / "matching_requests.jsonl", matching)

    t_counts = {}
    for m in match_state:
        t_counts[m["tier"]] = t_counts.get(m["tier"], 0) + 1
    print(f"start: tiers={t_counts} structuring_pending={len(structuring)} "
          f"matching_pending={len(matching)}")
    return 0


# --------------------------------------------------------------------------
# resolve
# --------------------------------------------------------------------------

def cmd_resolve(args):
    run_dir = Path(args.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    registry = rules_mod.load_registry(PKG_ROOT / "rules" / "registry.json")
    doc_type = Path(manifest["company_file"]).suffix.lstrip(".").lower()

    company_rows = common.read_jsonl(run_dir / "company_rows.jsonl")
    rows_by_id = {r["row_id"]: r for r in company_rows}
    official_rules = common.read_jsonl(run_dir / "official_rules.jsonl")
    rules_by_id = {r["rule_id"]: r for r in official_rules}

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    for m in match_state:
        _ensure_match_fields(m)
    state_by_id = {m["row_id"]: m for m in match_state}

    matching_requests_all = _read_jsonl_opt(run_dir / "matching_requests.jsonl")
    validation_failures_new = []
    new_matching_requests = []

    # ---- structuring pass ------------------------------------------------
    structuring_ok = 0
    structuring_failed = 0
    for resp in _read_jsonl_opt(run_dir / "structuring_responses.jsonl"):
        rid = resp.get("row_id")
        row = rows_by_id.get(rid)
        if row is None or row.get("status") != "needs-structuring":
            validation_failures_new.append(
                {"row_id": rid, "kind": "structuring", "errors": ["no-such-request"],
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            continue
        present = [k for k in _STRUCT_FIELDS if k in resp]
        codes = [] if present else ["no-fields-extracted"]
        for k in present:
            if not validate.quote_exists(resp[k], row.get("original_company_text", "")):
                codes.append(f"not-verbatim:{k}")
        if codes:
            structuring_failed += 1
            row["status"] = "extraction-failed"
            row["notes"] = "structuring-rejected:" + ",".join(codes)
            validation_failures_new.append(
                {"row_id": rid, "kind": "structuring", "errors": codes,
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            continue
        structuring_ok += 1
        for k in present:
            row[k] = resp[k]
        row["status"] = "ok"
        row["notes"] = ""
        # regenerate this row's tier/candidates now that fields are populated
        regen = candidates_mod.generate([row], official_rules)
        if regen:
            new_m = _ensure_match_fields(regen[0])
            state_by_id[rid] = new_m
            if new_m["tier"] is None and new_m["candidates"]:
                rules_for_req = [rules_by_id[c["rule_id"]] | {"_score": c["score"]}
                                 for c in new_m["candidates"]]
                new_matching_requests.append(
                    {"row_id": rid, "row": row, "candidates": rules_for_req,
                     "instructions_file": "prompts/matching.md"})

    # rebuild match_state list (preserve any newly-added regenerated rows)
    match_state = list(state_by_id.values())

    # ---- matching pass -----------------------------------------------------
    requested_ids = {r["row_id"] for r in matching_requests_all}
    matching_ok = 0
    matching_rejected_final = 0
    no_such_request = 0

    def _pending_ids():
        return requested_ids & {rid for rid, m in state_by_id.items()
                                 if m["tier"] is None}

    for resp in _read_jsonl_opt(run_dir / "matching_responses.jsonl"):
        rid = resp.get("row_id")
        if rid not in _pending_ids():
            no_such_request += 1
            validation_failures_new.append(
                {"row_id": rid, "kind": "matching", "errors": ["no-such-request"],
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            continue
        m = state_by_id[rid]
        row = rows_by_id.get(rid)
        shortlist_ids = [c["rule_id"] for c in m["candidates"]]
        errs = validate.validate_match_output(resp, shortlist_ids, row, rules_by_id)
        if errs:
            m["match_failures"] += 1
            m["retried"] = True
            validation_failures_new.append(
                {"row_id": rid, "kind": "matching", "errors": errs,
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            if m["match_failures"] >= 2:
                matching_rejected_final += 1
                m["tier"] = "T4"
                m["warnings"].append("llm-output-rejected")
            else:
                rules_for_req = [rules_by_id[c["rule_id"]] | {"_score": c["score"]}
                                 for c in m["candidates"]]
                new_matching_requests.append(
                    {"row_id": rid, "row": row, "candidates": rules_for_req,
                     "instructions_file": "prompts/matching.md", "retry": True,
                     "previous_errors": errs})
            continue

        decision = resp["decision"]
        matching_ok += 1
        if decision == "none":
            m["tier"] = "T4"
        elif decision == "ambiguous":
            m["tier"] = "T3"
            m["ambiguous_rule_ids"] = resp["ambiguous_rule_ids"]
        else:  # match
            chosen_id = resp["rule_id"]
            downgraded = False
            if m.get("margin_flag") and len(m["candidates"]) >= 2:
                runner_up = next((c for c in m["candidates"]
                                  if c["rule_id"] != chosen_id), None)
                if runner_up is not None:
                    runner_rule = rules_by_id.get(runner_up["rule_id"])
                    if runner_rule and validate.quote_exists(
                            resp["rule_quote"], _rule_text(runner_rule)):
                        downgraded = True
                        m["tier"] = "T3"
                        m["ambiguous_rule_ids"] = [chosen_id, runner_up["rule_id"]]
            if not downgraded:
                m["tier"] = "T2"
                m["matched_rule_id"] = chosen_id
                m["row_quote"] = resp["row_quote"]
                m["rule_quote"] = resp["rule_quote"]

    # ---- deterministic verdict / semantic hand-off -------------------------
    new_findings = []
    new_semantic_requests = []
    for m in match_state:
        if m["tier"] not in _MATCHED_TIERS or not m.get("matched_rule_id"):
            continue
        if m.get("verdict_done"):
            continue
        row_id = m["row_id"]
        row = rows_by_id.get(row_id)
        rule_id = m["matched_rule_id"]
        rule = rules_by_id.get(rule_id)
        if row is None or rule is None:
            continue
        context = _context_for_row(row, doc_type, field="expected_value")
        applied, _ = rules_mod.applicable_rules(registry, context)
        observed_raw = row.get("observed_value_or_evidence", "")
        expected_raw = rule.get("expected_value", "")
        eq_rule_id = rules_mod.equivalent_by_rule(applied, observed_raw, expected_raw)
        applied_rules_list = []
        if eq_rule_id:
            result = {"verdict": "Compliant", "basis": "rule-equivalence",
                      "deterministic": True, "approved_alignment": None,
                      "observation": {"observed": observed_raw,
                                      "expected": expected_raw}}
            applied_rules_list = [eq_rule_id]
        else:
            result = compare_values.deterministic_verdict(row, rule)

        m["verdict_done"] = True
        if result is not None:
            finding = _build_finding(
                row_id, rule_id, result["verdict"], result["basis"],
                result["deterministic"], None, result["observation"], None,
                applied_rules_list, m, row, rule,
                approved_alignment=result.get("approved_alignment"))
            new_findings.append(finding)
        else:
            new_semantic_requests.append(
                {"row_id": row_id, "rule_id": rule_id, "row": row, "rule": rule,
                 "instructions_file": "prompts/semantic_compare.md"})

    # ---- persist -------------------------------------------------------
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)
    common.write_jsonl(run_dir / "company_rows.jsonl", company_rows)
    _append_jsonl(run_dir / "matching_requests.jsonl", new_matching_requests)
    _append_jsonl(run_dir / "validation_failures.jsonl", validation_failures_new)
    _append_jsonl(run_dir / "findings.jsonl", new_findings)
    _append_jsonl(run_dir / "semantic_requests.jsonl", new_semantic_requests)

    retries_pending = sum(1 for m in match_state
                          if m["tier"] is None and m["match_failures"] == 1)
    semantic_pending_total = len(_read_jsonl_opt(run_dir / "semantic_requests.jsonl"))
    print(f"resolve: structuring_ok={structuring_ok} "
          f"structuring_failed={structuring_failed} matching_ok={matching_ok} "
          f"matching_rejected_final={matching_rejected_final} "
          f"no_such_request={no_such_request} retries_pending={retries_pending} "
          f"new_findings={len(new_findings)} semantic_pending={semantic_pending_total}")
    return 0


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------

def _ignored_row_ids(registry, company_rows, doc_type):
    ignored = set()
    for row in company_rows:
        context = _context_for_row(row, doc_type, field="")
        applied, _ = rules_mod.applicable_rules(registry, context)
        if any(r["category"] == "ignore-field" and
               r["scope"]["level"] == "sheet-or-section" for r in applied):
            ignored.add(row["row_id"])
    return ignored


def cmd_finalize(args):
    run_dir = Path(args.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    registry = rules_mod.load_registry(PKG_ROOT / "rules" / "registry.json")
    doc_type = Path(manifest["company_file"]).suffix.lstrip(".").lower()

    company_rows = common.read_jsonl(run_dir / "company_rows.jsonl")
    rows_by_id = {r["row_id"]: r for r in company_rows}
    official_rules = common.read_jsonl(run_dir / "official_rules.jsonl")
    rules_by_id = {r["rule_id"]: r for r in official_rules}

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    for m in match_state:
        _ensure_match_fields(m)
    state_by_id = {m["row_id"]: m for m in match_state}

    validation_failures = _read_jsonl_opt(run_dir / "validation_failures.jsonl")
    new_validation_failures = []

    # ---- pending matching rows --------------------------------------------
    matching_requests_all = _read_jsonl_opt(run_dir / "matching_requests.jsonl")
    matching_requested_ids = {r["row_id"] for r in matching_requests_all}
    pending_matching_ids = sorted(
        rid for rid in matching_requested_ids
        if state_by_id.get(rid, {}).get("tier") is None)

    # ---- semantic responses -------------------------------------------
    semantic_requests_all = _read_jsonl_opt(run_dir / "semantic_requests.jsonl")
    semantic_pairs = {(r["row_id"], r["rule_id"]) for r in semantic_requests_all}
    resolved_pairs = set()
    semantic_findings = []
    new_semantic_requests = []

    for resp in _read_jsonl_opt(run_dir / "semantic_responses.jsonl"):
        rid, ruleid = resp.get("row_id"), resp.get("rule_id")
        pair = (rid, ruleid)
        if pair not in semantic_pairs or pair in resolved_pairs:
            new_validation_failures.append(
                {"row_id": rid, "rule_id": ruleid, "kind": "semantic",
                 "errors": ["no-such-request"],
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            continue
        row = rows_by_id.get(rid)
        rule = rules_by_id.get(ruleid)
        m = state_by_id.get(rid)
        if row is None or rule is None or m is None:
            new_validation_failures.append(
                {"row_id": rid, "rule_id": ruleid, "kind": "semantic",
                 "errors": ["no-such-request"],
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            resolved_pairs.add(pair)
            continue
        errs = validate.validate_semantic_output(resp, row, rule)
        if errs:
            m["semantic_failures"] += 1
            m["retried"] = True
            new_validation_failures.append(
                {"row_id": rid, "rule_id": ruleid, "kind": "semantic",
                 "errors": errs,
                 "timestamp": datetime.now().isoformat(timespec="seconds")})
            if m["semantic_failures"] >= 2:
                resolved_pairs.add(pair)
                semantic_findings.append(_build_finding(
                    rid, ruleid, "Cannot Assess", "llm-output-rejected", False,
                    None, None, None, [], m, row, rule))
            else:
                new_semantic_requests.append(
                    {"row_id": rid, "rule_id": ruleid, "row": row, "rule": rule,
                     "instructions_file": "prompts/semantic_compare.md",
                     "retry": True, "previous_errors": errs})
            continue

        resolved_pairs.add(pair)
        semantic_findings.append(_build_finding(
            rid, ruleid, resp["verdict"], "semantic-comparison", False,
            resp["finding_type"], {"row_quote": resp.get("row_quote"),
                                    "rule_quote": resp.get("rule_quote")},
            resp.get("interpretation"), [], m, row, rule))

    pending_semantic_pairs = sorted(semantic_pairs - resolved_pairs)

    # Persist the bookkeeping from this call's semantic-response processing
    # (retry counters, requeued requests, validation failures) *before* any
    # early return below. A refusal or coverage-abort must not silently
    # discard work already done, or the two-strike retry counter would never
    # advance across repeated `finalize` invocations.
    common.write_jsonl(run_dir / "match_state.jsonl", list(state_by_id.values()))
    _append_jsonl(run_dir / "validation_failures.jsonl", new_validation_failures)
    _append_jsonl(run_dir / "semantic_requests.jsonl", new_semantic_requests)

    # ---- refusal gate -------------------------------------------------
    if (pending_matching_ids or pending_semantic_pairs) and not args.allow_pending:
        print(f"finalize: refused - pending matching={len(pending_matching_ids)} "
              f"pending semantic={len(pending_semantic_pairs)} "
              f"(use --allow-pending to force)")
        return 4

    passnotrun_findings = []
    if args.allow_pending:
        for rid in pending_matching_ids:
            m = state_by_id[rid]
            m["tier"] = "T4"
            if "matching-pass-not-run" not in m["warnings"]:
                m["warnings"].append("matching-pass-not-run")
        for rid, ruleid in pending_semantic_pairs:
            m = state_by_id.get(rid)
            row = rows_by_id.get(rid)
            rule = rules_by_id.get(ruleid)
            if m is None or row is None or rule is None:
                continue
            f = _build_finding(rid, ruleid, "Cannot Assess",
                                "semantic-pass-not-run", False, None, None,
                                None, [], m, row, rule)
            f["human_review_needed"] = True
            passnotrun_findings.append(f)

    match_state = list(state_by_id.values())

    # ---- deterministic findings recorded during resolve --------------
    det_findings = _read_jsonl_opt(run_dir / "findings.jsonl")

    all_findings = det_findings + semantic_findings + passnotrun_findings

    # ---- skeptic merge -------------------------------------------------
    skeptic_by_finding = {s["finding_id"]: s
                          for s in _read_jsonl_opt(run_dir / "skeptic_responses.jsonl")}
    for f in all_findings:
        s = skeptic_by_finding.get(f["finding_id"])
        if s is not None:
            f["skeptic"] = {"outcome": s.get("outcome"), "reason": s.get("reason")}
            f["disputed"] = s.get("outcome") == "refuted"

    # ---- dedup + contradictions ----------------------------------------
    kept, dropped = validate.dedup_findings(all_findings)
    contradictions = validate.find_contradictions(kept)

    # ---- coverage --------------------------------------------------------
    ignored_row_ids = _ignored_row_ids(registry, company_rows, doc_type)
    coverage = coverage_mod.compute(company_rows, official_rules, match_state,
                                    ignored_row_ids)
    if not coverage["ok"]:
        print(f"finalize: aborted - coverage not ok: {coverage['warnings']}")
        return 3

    # ---- validation-failure and rule-conflict lookups for review flags --
    all_validation_failures = validation_failures + new_validation_failures
    validation_failed_row_ids = {vf["row_id"] for vf in all_validation_failures}
    duplicate_rule_ids = set(coverage["official"]["duplicate_coverage_rule_ids"])
    global_conflict = bool(manifest.get("rule_conflicts"))
    row_conflict_cache = {}

    def _row_has_conflict(row_id):
        if row_id in row_conflict_cache:
            return row_conflict_cache[row_id]
        row = rows_by_id.get(row_id)
        result = global_conflict
        if row is not None and not result:
            context = _context_for_row(row, doc_type, field="")
            _, conflicts = rules_mod.applicable_rules(registry, context)
            result = bool(conflicts)
        row_conflict_cache[row_id] = result
        return result

    # ---- confidence + human_review_needed --------------------------------
    for f in kept:
        m = state_by_id.get(f["row_id"], {"tier": None, "margin_flag": False,
                                          "retried": False})
        skeptic_outcome = f["skeptic"]["outcome"] if f.get("skeptic") else None
        f["confidence"] = assign_confidence(m, f, skeptic_outcome)

        review = False
        if m.get("tier") == "T3":
            review = True
        if not f.get("deterministic", False):
            outcome = f["skeptic"]["outcome"] if f.get("skeptic") else None
            if outcome != "upheld":
                review = True
        if f.get("rule_id") in duplicate_rule_ids:
            review = True
        row = rows_by_id.get(f["row_id"], {})
        if f.get("verdict") == "Cannot Assess" and common.fold_ws(
                row.get("observed_value_or_evidence", "")):
            review = True
        if f["row_id"] in validation_failed_row_ids:
            review = True
        if _row_has_conflict(f["row_id"]):
            review = True
        f["human_review_needed"] = review

    # ---- leftovers: unmatched / ambiguous / unaddressed -------------------
    matched_rule_ids = {m["matched_rule_id"] for m in match_state
                        if m["tier"] in _MATCHED_TIERS and m.get("matched_rule_id")}
    unmatched_rows = []
    ambiguous = []
    for m in match_state:
        row = rows_by_id.get(m["row_id"])
        if row is None or row.get("status") != "ok":
            continue
        if m["tier"] == "T3":
            ambiguous.append({
                "row_id": m["row_id"],
                "original_company_text": row.get("original_company_text", ""),
                "source_reference": row.get("source_reference", {}),
                "ambiguous_rule_ids": m.get("ambiguous_rule_ids", []),
                "candidates": m.get("candidates", [])})
        elif m["tier"] in (None, "T4"):
            unmatched_rows.append({
                "row_id": m["row_id"],
                "original_company_text": row.get("original_company_text", ""),
                "source_reference": row.get("source_reference", {}),
                "warnings": m.get("warnings", [])})
    unaddressed_rules = [
        {"rule_id": r["rule_id"], "title": r.get("title", ""),
         "check_text": r.get("check_text", ""),
         "expected_value": r.get("expected_value", "")}
        for r in official_rules if r["rule_id"] not in matched_rule_ids]

    # ---- top-level warnings ----------------------------------------------
    extract_warnings = json.loads(
        (run_dir / "extract_warnings.json").read_text(encoding="utf-8")) \
        if (run_dir / "extract_warnings.json").exists() else []
    warnings = list(extract_warnings) + list(coverage["warnings"]) + \
        [{"code": "rule-conflict", "rule_ids": c["rule_ids"],
         "scope_level": c["scope_level"]} for c in manifest.get("rule_conflicts", [])] + \
        [{"code": "duplicate-finding-dropped", "detail": fid} for fid in dropped] + \
        [{"code": c["code"], "finding_ids": c["finding_ids"]} for c in contradictions]

    final = {
        "manifest": manifest,
        "findings": kept,
        "match_state": match_state,
        "coverage": coverage,
        "warnings": warnings,
        "unmatched_rows": unmatched_rows,
        "unaddressed_rules": unaddressed_rules,
        "ambiguous": ambiguous,
    }
    (run_dir / "final.json").write_text(json.dumps(final, indent=1),
                                        encoding="utf-8")

    # ---- persist post-finalize mutations (allow-pending tier/warning changes) --
    # (validation_failures.jsonl / semantic_requests.jsonl were already persisted
    # above, before the refusal/coverage gates; re-persist only match_state here
    # to capture the allow-pending tier="T4" / matching-pass-not-run mutations.)
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)

    if not args.no_report:
        import report
        report.render(run_dir)

    print(f"finalize: findings={len(kept)} dropped_dupes={len(dropped)} "
          f"contradictions={len(contradictions)} coverage_ok={coverage['ok']} "
          f"human_review={sum(1 for f in kept if f['human_review_needed'])}")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--official", required=True)
    p_start.add_argument("--company", required=True)
    p_start.add_argument("--run-dir", required=True)

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--run-dir", required=True)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--run-dir", required=True)
    p_finalize.add_argument("--no-report", action="store_true")
    p_finalize.add_argument("--allow-pending", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)
    if args.cmd == "finalize":
        return cmd_finalize(args)
    raise ValueError(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
