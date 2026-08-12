"""Pipeline orchestration: start -> (Claude) -> resolve -> ... -> finalize.

Claude never talks to this module directly; it reads *_requests.jsonl and
writes *_responses.jsonl. Everything it writes is validated mechanically
before use. Python makes NO semantic decisions here: it parses, chunks by
size, routes on enums the LLM chose, counts, and settles two-strike
failures with pipeline statuses (never verdicts).

*_responses.jsonl files are Claude/attacker-controlled input and are read
with tolerant, line-by-line parsing (_read_response_lines/
_parse_response_line): a malformed line never aborts the batch, it becomes
a validation_failures.jsonl entry. common.read_jsonl (strict) is reserved
for the pipeline's own artifacts.

Every response line is fingerprinted and recorded as "consumed" in
consumed_responses.json before it is applied, so replaying an unchanged
responses file is a full no-op. Retried units require a `retry: true` echo
(and sweep-round adjudications a `sweep_round: true` echo), so a re-round
answer is never byte-identical to a consumed line and can never be
swallowed by the fingerprint dedup.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import canonical
import common
import coverage as coverage_mod
import extract
import payloads
import schema
import skeleton
import validate

PKG_ROOT = Path(__file__).resolve().parent.parent

_NO_RULE = object()  # sentinel: "this failure record has no rule_id field"

_SETTLED_NO_MATCH = ("none", "unresolved-llm-output-rejected")


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------

def _read_jsonl_opt(path):
    """Strict reader for the pipeline's own artifacts (never Claude-authored)."""
    path = Path(path)
    if not path.exists():
        return []
    return common.read_jsonl(path)


def _append_jsonl(path, new_records):
    if not new_records:
        return
    existing = _read_jsonl_opt(path)
    existing.extend(new_records)
    common.write_jsonl(path, existing)


def _read_response_lines(path):
    """Tolerant raw-line reader for *_responses.jsonl (Claude-controlled)."""
    path = Path(path)
    if not path.exists():
        return []
    lines = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)
    return lines


def _parse_response_line(raw_line):
    """Parse one *_responses.jsonl line. Never raises."""
    try:
        obj = json.loads(raw_line)
    except (json.JSONDecodeError, ValueError):
        return None, "malformed-json"
    if not isinstance(obj, dict):
        return None, "malformed-json"
    return obj, None


def _mk_failure(row_id, kind, errors, response, rule_id=_NO_RULE):
    rec = {"row_id": row_id, "kind": kind, "errors": errors,
           "response": response,
           "timestamp": datetime.now().isoformat(timespec="seconds")}
    if rule_id is not _NO_RULE:
        rec["rule_id"] = rule_id
    return rec


def _consumed_path(run_dir):
    return Path(run_dir) / "consumed_responses.json"


def _load_consumed(run_dir):
    p = _consumed_path(run_dir)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for k in schema.RESPONSE_KINDS:
        data.setdefault(k, [])
    return data


def _save_consumed(run_dir, consumed):
    _consumed_path(run_dir).write_text(json.dumps(consumed, indent=1),
                                       encoding="utf-8")


def _fingerprint(raw_line):
    return hashlib.sha256(raw_line.encode("utf-8")).hexdigest()


def _psize(obj):
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _chunk_by_bytes(items, budget):
    """Order-preserving greedy chunking by serialized size. Always at least
    one item per chunk — size arithmetic only, never content selection."""
    chunks, current, used = [], [], 0
    for item in items:
        size = _psize(item)
        if current and used + size > budget:
            chunks.append(current)
            current, used = [], 0
        current.append(item)
        used += size
    if current:
        chunks.append(current)
    return chunks


def _new_match_state(record_id, batch):
    return {"record_id": record_id, "scoping_batch": batch,
            "decision": None, "basis": "",
            "selected_official_row_ids": [],
            "ambiguous_official_row_ids": [],
            "row_quotes": {}, "official_quotes": {},
            "nominations": [], "scoping_incomplete": False,
            "adjudication_failures": 0, "adjudication_emitted": False,
            "sweep_round": False, "sweep_origin_row_ids": [],
            "comparison_units": [], "claim_consistency": None,
            "record_notes": "", "warnings": []}


def _ensure_match_fields(m):
    for k, v in _new_match_state("", "").items():
        m.setdefault(k, v)
    return m


def _load_precedents():
    """Prior human feedback, mechanically keyed by official row. The LLM
    judges applicability; Python only looks up by id."""
    return _read_jsonl_opt(PKG_ROOT / "feedback" / "precedents.jsonl")


def _precedents_for(precedents, official_row):
    oid = official_row.get("official_row_id")
    did = official_row.get("display_id")
    out = []
    for p in precedents:
        if p.get("official_row_id") == oid or \
                (did and p.get("display_id") == did):
            out.append({"feedback_id": p.get("feedback_id"),
                        "official_row_id": oid,
                        "classification": p.get("classification"),
                        "comment": p.get("comment"),
                        "prior_verdict": p.get("prior_verdict")})
    return out


def _build_finding(record, m, official_row, entry, claim_consistency,
                   record_notes, split):
    """One finding per (record, official row), copied verbatim from the
    LLM's comparison output plus complete both-side payloads."""
    rid = record["record_id"]
    oid = official_row["official_row_id"]
    return {
        "finding_id": common.finding_id(rid, oid, "comparison"),
        "record_id": rid, "row_id": record["row_id"],
        "official_row_id": oid,
        "display_id": official_row.get("display_id"),
        "verdict": entry["verdict"],
        "verdict_source": "comparison",
        "change_analysis": list(entry["change_analysis"]),
        "match_rationale": entry["match_rationale"],
        "semantic_differences": entry["semantic_differences"],
        "reasoning": entry["reasoning"],
        "field_alignment": entry["field_alignment"],
        "row_quote": entry["row_quote"],
        "official_quote": entry["official_quote"],
        "confidence": entry["confidence"],
        "human_review": entry["human_review"],
        "human_review_needed": None, "review_reasons": [],
        "claim_reading": record.get("company_claim_reading", "none"),
        "claim_consistency": claim_consistency,
        "record_notes": record_notes,
        "sweep_originated": oid in m.get("sweep_origin_row_ids", []),
        "comparison_split": bool(split),
        "validation": None, "disputed": False,
        "match_basis": {"basis": m.get("basis", ""),
                        "row_quote": m.get("row_quotes", {}).get(oid, ""),
                        "official_quote":
                            m.get("official_quotes", {}).get(oid, "")},
        "company_row": payloads.company_record_payload(record),
        "official_row": payloads.official_row_payload(official_row),
    }


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def cmd_start(args):
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        official = extract.extract_official(args.official)
        skel = skeleton.extract_skeleton(args.company)
    except Exception as e:                        # no document text in errors
        print(f"pipeline: cannot read file: {type(e).__name__}", file=sys.stderr)
        return 2

    manifest = {
        "official_file": Path(args.official).name,
        "company_file": Path(args.company).name,
        "official_sha256": common.file_sha256(args.official),
        "company_sha256": common.file_sha256(args.company),
        "started": datetime.now().isoformat(timespec="seconds"),
        "versions": common.load_versions(PKG_ROOT),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    common.write_jsonl(run_dir / "official_rows.jsonl", official["rows"])
    (run_dir / "skeleton.json").write_text(
        json.dumps(skel, indent=1), encoding="utf-8")
    (run_dir / "extract_warnings.json").write_text(json.dumps(
        official["warnings"] + skel["warnings"], indent=1), encoding="utf-8")

    # Official-structure pass: one request per sheet/section, annotation only.
    groups = []
    for row in official["rows"]:
        if not groups or groups[-1][0] != row["sheet_or_section"]:
            groups.append((row["sheet_or_section"], []))
        groups[-1][1].append(row)
    structure_requests, structure_state = [], []
    for n, (section, rows) in enumerate(groups):
        sid = f"OS-{n}"
        structure_requests.append({
            "structure_id": sid, "sheet_or_section": section,
            "headers": rows[0]["headers"],
            "sample_rows": [r["cells"]
                            for r in rows[:schema.STRUCTURE_SAMPLE_ROWS]],
            "row_count": len(rows),
            "instructions_file": "prompts/official_structure.md"})
        structure_state.append({"structure_id": sid,
                                "sheet_or_section": section,
                                "done": False, "failures": 0})
    common.write_jsonl(run_dir / "official_structure_requests.jsonl",
                       structure_requests)
    common.write_jsonl(run_dir / "official_structure_state.jsonl",
                       structure_state)

    mapping_requests = [
        {"table_index": t["table_index"],
         "sheet_or_section": t["sheet_or_section"],
         "preceding_narrative": t["preceding_narrative"],
         "header_row": t["header_row"],
         "sample_rows": [r["cells"]
                         for r in t["rows"][:schema.TABLE_MAPPING_SAMPLE_ROWS]],
         "row_count": len(t["rows"]),
         "total_bytes": _psize([r["cells"] for r in t["rows"]]),
         "instructions_file": "prompts/table_mapping.md"}
        for t in skel["tables"]]
    common.write_jsonl(run_dir / "table_mapping_requests.jsonl",
                       mapping_requests)
    common.write_jsonl(run_dir / "table_state.jsonl", [
        {"table_index": t["table_index"], "classification": None,
         "irrelevant_reason": "", "column_mapping": {},
         "context_grouping": "", "mapping_failures": 0,
         "row_dispositions": {}, "parent_of": {}, "chunks": {},
         "records_built": False}
        for t in skel["tables"]])
    common.write_jsonl(run_dir / "company_records.jsonl", [])
    common.write_jsonl(run_dir / "match_state.jsonl", [])
    common.write_jsonl(run_dir / "scoping_state.jsonl", [])

    print(f"start: tables={len(skel['tables'])} "
          f"official_rows={len(official['rows'])} "
          f"structure_pending={len(structure_requests)} "
          f"mapping_pending={len(mapping_requests)}")
    return 0


# --------------------------------------------------------------------------
# record building (interpretation results -> stored records)
# --------------------------------------------------------------------------

def _build_table_records(table, ts):
    """Walk a fully-interpreted table's stored chunk entries in row order and
    build records. Mutates ts (row_dispositions, parent_of). Continuation
    rows attach their verbatim cells to the parent row's records. Rows the
    validator somehow never saw become extraction-failed records via
    canonical.reconcile."""
    rows_by_index = {r["row_index"]: r for r in table["rows"]}
    entries = []
    for chunk in ts["chunks"].values():
        entries.extend(chunk.get("entries", []))
    entries.sort(key=lambda e: e["row_index"])

    records = []
    records_by_row = {}
    current_context = ts["context_grouping"]
    last_record_row = None
    for entry in entries:
        ri = entry["row_index"]
        disp = entry["disposition"]
        ts["row_dispositions"][str(ri)] = disp
        if disp == "separator":
            st = common.fold_ws(entry.get("separator_text", ""))
            current_context = ts["context_grouping"] + \
                (" | " + st if st else "")
            continue
        if disp == "continuation":
            if last_record_row is None:
                ts["row_dispositions"][str(ri)] = "record"
                rec = canonical.failed_record(
                    table, rows_by_index[ri], "orphan-continuation")
                records.append(rec)
            else:
                ts["parent_of"][str(ri)] = last_record_row
                for rec in records_by_row.get(last_record_row, []):
                    rec["continuation_cells"].append(
                        {"row_index": ri,
                         "cells": [str(c)
                                   for c in rows_by_index[ri]["cells"]]})
            continue
        last_record_row = ri
        for rec_resp in entry["records"]:
            rec = canonical.build_record(
                table, rows_by_index[ri], rec_resp["sub_index"],
                rec_resp["fields"], rec_resp["field_provenance"],
                rec_resp.get("interpretation_note", ""), current_context,
                rec_resp.get("company_claim_reading", "none"))
            records.append(rec)
            records_by_row.setdefault(ri, []).append(rec)
    for ri in canonical.reconcile(
            table, {int(k): v for k, v in ts["row_dispositions"].items()}):
        ts["row_dispositions"][str(ri)] = "record"
        records.append(canonical.failed_record(
            table, rows_by_index[ri], "reconcile-missing"))
    return records


# --------------------------------------------------------------------------
# resolve — the single state-machine advancer; consumes every response kind
# --------------------------------------------------------------------------

def cmd_resolve(args):
    run_dir = Path(args.run_dir)
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    tables_by_index = {t["table_index"]: t for t in skel["tables"]}
    table_state = _read_jsonl_opt(run_dir / "table_state.jsonl")
    tstate_by_index = {t["table_index"]: t for t in table_state}
    structure_state = _read_jsonl_opt(run_dir / "official_structure_state.jsonl")
    sstate_by_id = {s["structure_id"]: s for s in structure_state}
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
    official_rows = common.read_jsonl(run_dir / "official_rows.jsonl")
    rows_by_id = {r["official_row_id"]: r for r in official_rows}
    match_state = [_ensure_match_fields(m) for m in
                   _read_jsonl_opt(run_dir / "match_state.jsonl")]
    state_by_id = {m["record_id"]: m for m in match_state}
    scoping_state = _read_jsonl_opt(run_dir / "scoping_state.jsonl")
    scoping_by_id = {s["scoping_id"]: s for s in scoping_state}
    rollup_state = _read_jsonl_opt(run_dir / "rollup_state.jsonl")
    rollup_by_id = {r["rollup_id"]: r for r in rollup_state}
    validation_state = _read_jsonl_opt(run_dir / "validation_state.jsonl")
    vstate_by_id = {v["validation_id"]: v for v in validation_state}
    precedents = _load_precedents()

    consumed = _load_consumed(run_dir)
    failures_new = []
    run_warnings_new = []
    counts = {}

    def _count(key, n=1):
        counts[key] = counts.get(key, 0) + n

    def _consume(kind, raw_line):
        """Returns (resp, errors) — errors is None for a fresh valid parse,
        "consumed" for an already-consumed replay, or a parse error code."""
        fp = _fingerprint(raw_line)
        if fp in consumed_sets[kind]:
            return None, "consumed"
        consumed_sets[kind].add(fp)
        resp, parse_err = _parse_response_line(raw_line)
        if parse_err:
            failures_new.append(_mk_failure(None, kind, [parse_err], raw_line))
            return None, parse_err
        return resp, None

    consumed_sets = {k: set(consumed[k]) for k in schema.RESPONSE_KINDS}

    # ---- official structure ------------------------------------------------
    structure_req_by_id = {r["structure_id"]: r for r in _read_jsonl_opt(
        run_dir / "official_structure_requests.jsonl")}
    new_structure_requests = []
    official_mutated = False
    for raw_line in _read_response_lines(
            run_dir / "official_structure_responses.jsonl"):
        resp, err = _consume("official_structure", raw_line)
        if resp is None:
            continue
        sid = resp.get("structure_id")
        st = sstate_by_id.get(sid) if isinstance(sid, str) else None
        req = structure_req_by_id.get(sid) if isinstance(sid, str) else None
        if st is None or req is None or st["done"]:
            failures_new.append(_mk_failure(
                None, "official_structure", ["no-such-request"], resp))
            continue
        errs = validate.validate_official_structure_output(
            resp, req, require_retry=st["failures"] == 1)
        if errs:
            st["failures"] += 1
            failures_new.append(_mk_failure(
                None, "official_structure", errs, resp))
            if st["failures"] >= 2:
                st["done"] = True
                st["rejected"] = True
                run_warnings_new.append(
                    {"code": "structure-rejected",
                     "detail": st["sheet_or_section"]})
            else:
                new_structure_requests.append(dict(
                    req, retry=True, previous_errors=errs))
            continue
        st["done"] = True
        _count("structure_ok")
        dic = resp["display_id_column"]
        for row in official_rows:
            if row["sheet_or_section"] != st["sheet_or_section"]:
                continue
            row["column_roles"] = resp["column_roles"]
            if dic is not None:
                row["display_id"] = common.fold_ws(
                    row["raw_record"].get(dic, "")) or None
        official_mutated = True
    if official_mutated:
        # Duplicate display ids: counting LLM-designated values is
        # arithmetic, not judgment.
        seen_display = {}
        for row in official_rows:
            did = row.get("display_id")
            if did:
                seen_display[did] = seen_display.get(did, 0) + 1
        for did, n in sorted(seen_display.items()):
            if n > 1:
                run_warnings_new.append({"code": "duplicate-display-id",
                                         "detail": f"{did} appears {n} times"})

    # ---- table mapping -----------------------------------------------------
    mapping_req_by_index = {r["table_index"]: r for r in _read_jsonl_opt(
        run_dir / "table_mapping_requests.jsonl")}
    new_mapping_requests = []
    new_interp_requests = []
    for raw_line in _read_response_lines(
            run_dir / "table_mapping_responses.jsonl"):
        resp, err = _consume("table_mapping", raw_line)
        if resp is None:
            continue
        tix = resp.get("table_index")
        ts = tstate_by_index.get(tix) if isinstance(tix, int) else None
        if ts is None or ts["classification"] is not None:
            failures_new.append(_mk_failure(
                None, "table_mapping", ["no-such-request"], resp))
            continue
        errs = validate.validate_table_mapping_output(
            resp, tables_by_index[tix],
            require_retry=ts["mapping_failures"] == 1)
        if errs:
            ts["mapping_failures"] += 1
            failures_new.append(_mk_failure(None, "table_mapping", errs, resp))
            if ts["mapping_failures"] >= 2:
                ts["classification"] = "mapping-failed"
                _count("mapping_failed")
            else:
                new_mapping_requests.append(dict(
                    mapping_req_by_index[tix], retry=True,
                    previous_errors=errs))
            continue
        _count("mapping_ok")
        ts["classification"] = resp["classification"]
        ts["irrelevant_reason"] = resp["irrelevant_reason"]
        ts["column_mapping"] = resp["column_mapping"]
        ts["context_grouping"] = common.fold_ws(resp["context_grouping"])
        if ts["classification"] in ("stig_relevant", "uncertain"):
            table = tables_by_index[tix]
            for ci, chunk in enumerate(canonical.chunk_rows(table["rows"])):
                chunk_id = f"T{tix}-C{ci}"
                ts["chunks"][chunk_id] = {
                    "row_indexes": [r["row_index"] for r in chunk],
                    "done": False, "failures": 0, "entries": []}
                new_interp_requests.append({
                    "chunk_id": chunk_id, "table_index": tix,
                    "context_grouping": ts["context_grouping"],
                    "column_mapping": ts["column_mapping"],
                    "header_row": table["header_row"],
                    "preceding_narrative": table["preceding_narrative"],
                    "rows": chunk,
                    "instructions_file": "prompts/row_interpretation.md"})

    # ---- row interpretation ------------------------------------------------
    def _chunk_state(chunk_id):
        for ts in table_state:
            if chunk_id in ts.get("chunks", {}):
                return ts, ts["chunks"][chunk_id]
        return None, None

    def _interp_request(cid, ts, table, chunk):
        rows_by_index = {r["row_index"]: r for r in table["rows"]}
        try:
            rows = [rows_by_index[ri] for ri in chunk["row_indexes"]]
        except KeyError:
            return None
        return {"chunk_id": cid, "table_index": ts["table_index"],
                "context_grouping": ts["context_grouping"],
                "column_mapping": ts["column_mapping"],
                "header_row": table["header_row"],
                "preceding_narrative": table["preceding_narrative"],
                "rows": rows,
                "instructions_file": "prompts/row_interpretation.md"}

    new_records = []
    for raw_line in _read_response_lines(
            run_dir / "interpretation_responses.jsonl"):
        resp, err = _consume("interpretation", raw_line)
        if resp is None:
            continue
        cid = resp.get("chunk_id") if isinstance(resp.get("chunk_id"), str) \
            else None
        ts, chunk = _chunk_state(cid) if cid else (None, None)
        if chunk is None or chunk["done"]:
            failures_new.append(_mk_failure(
                None, "interpretation", ["no-such-request"], resp))
            continue
        table = tables_by_index[ts["table_index"]]
        errs = validate.validate_interpretation_output(
            resp, table, chunk["row_indexes"],
            require_retry=chunk["failures"] == 1)
        if errs:
            chunk["failures"] += 1
            failures_new.append(_mk_failure(None, "interpretation", errs, resp))
            if chunk["failures"] >= 2:
                chunk["done"] = True
                _count("interpretation_failed")
                rows_by_index = {r["row_index"]: r for r in table["rows"]}
                chunk["entries"] = []
                for ri in chunk["row_indexes"]:
                    ts["row_dispositions"][str(ri)] = "record"
                    new_records.append(canonical.failed_record(
                        table, rows_by_index[ri], "interpretation-rejected"))
            else:
                retry_req = _interp_request(cid, ts, table, chunk)
                if retry_req is not None:
                    new_interp_requests.append(dict(
                        retry_req, retry=True, previous_errors=errs))
            continue
        _count("interpretation_ok")
        chunk["done"] = True
        chunk["entries"] = resp["rows"]

    # tables whose chunks all just completed -> build records
    built_records = []
    for ts in table_state:
        chunks = ts.get("chunks", {})
        if not chunks or ts.get("records_built"):
            continue
        if all(c["done"] for c in chunks.values()):
            table = tables_by_index[ts["table_index"]]
            built = _build_table_records(table, ts)
            ts["records_built"] = True
            built_records.extend(built)
    new_records.extend(built_records)

    # ---- match scoping: emit requests for fresh ok records -----------------
    new_scoping_requests = []
    official_payload_chunks = _chunk_by_bytes(
        [payloads.official_row_payload(r) for r in official_rows],
        schema.SCOPING_OFFICIAL_CHUNK_BYTES)
    if new_records:
        company_records.extend(new_records)
        records_by_id.update({r["record_id"]: r for r in new_records})
        fresh_ok = [r for r in new_records if r["status"] == "ok"]
        existing_batches = {s["batch"] for s in scoping_state}
        next_batch = len(existing_batches)
        for i in range(0, len(fresh_ok), schema.SCOPING_RECORD_BATCH):
            batch_records = fresh_ok[i:i + schema.SCOPING_RECORD_BATCH]
            batch = f"B{next_batch}"
            next_batch += 1
            for m_new in batch_records:
                m = _new_match_state(m_new["record_id"], batch)
                match_state.append(m)
                state_by_id[m["record_id"]] = m
            for k, chunk in enumerate(official_payload_chunks):
                sid = f"SC-{batch}-K{k}"
                entry = {"scoping_id": sid, "batch": batch,
                         "record_ids": [r["record_id"]
                                        for r in batch_records],
                         "official_row_ids": [c["official_row_id"]
                                              for c in chunk],
                         "done": False, "failures": 0}
                scoping_state.append(entry)
                scoping_by_id[sid] = entry
                new_scoping_requests.append({
                    "scoping_id": sid,
                    "records": [payloads.company_record_payload(r)
                                for r in batch_records],
                    "official_rows": chunk,
                    "instructions_file": "prompts/match_scoping.md"})

    # ---- match scoping: consume responses ----------------------------------
    scoping_req_by_id = {r["scoping_id"]: r for r in _read_jsonl_opt(
        run_dir / "scoping_requests.jsonl")}
    for raw_line in _read_response_lines(run_dir / "scoping_responses.jsonl"):
        resp, err = _consume("scoping", raw_line)
        if resp is None:
            continue
        sid = resp.get("scoping_id")
        cell = scoping_by_id.get(sid) if isinstance(sid, str) else None
        if cell is None or cell["done"]:
            failures_new.append(_mk_failure(
                None, "scoping", ["no-such-request"], resp))
            continue
        errs = validate.validate_scoping_output(
            resp, set(cell["record_ids"]), set(cell["official_row_ids"]),
            require_retry=cell["failures"] == 1)
        if errs:
            cell["failures"] += 1
            failures_new.append(_mk_failure(None, "scoping", errs, resp))
            if cell["failures"] >= 2:
                cell["done"] = True
                cell["rejected"] = True
                _count("scoping_rejected")
                run_warnings_new.append({"code": "scoping-cell-rejected",
                                         "detail": sid})
                for rid in cell["record_ids"]:
                    if rid in state_by_id:
                        state_by_id[rid]["scoping_incomplete"] = True
            else:
                req = scoping_req_by_id.get(sid)
                if req is not None:
                    new_scoping_requests.append(dict(
                        req, retry=True, previous_errors=errs))
            continue
        cell["done"] = True
        _count("scoping_ok")
        for n in resp["nominations"]:
            m = state_by_id.get(n["record_id"])
            if m is not None and \
                    n["official_row_id"] not in m["nominations"]:
                m["nominations"].append(n["official_row_id"])

    # ---- adjudication: emit for records whose scoping batch settled --------
    new_adjudication_requests = []

    def _adjudication_request(m, extra=None):
        record = records_by_id[m["record_id"]]
        req = {"record_id": m["record_id"],
               "record": payloads.company_record_payload(record),
               "nominated_rows": [payloads.official_row_payload(rows_by_id[oid])
                                  for oid in m["nominations"]
                                  if oid in rows_by_id],
               "sweep_round": m["sweep_round"],
               "instructions_file": "prompts/match_adjudication.md"}
        if extra:
            req.update(extra)
        return req

    cells_by_batch = {}
    for s in scoping_state:
        cells_by_batch.setdefault(s["batch"], []).append(s)
    for m in match_state:
        if m["decision"] is not None or m["adjudication_emitted"] or \
                m["sweep_round"]:
            continue
        cells = cells_by_batch.get(m["scoping_batch"], [])
        if not cells or not all(c["done"] for c in cells):
            continue
        if not m["nominations"]:
            # Zero nominations across every corpus chunk IS the LLM's
            # no-match answer; Python only aggregates it.
            m["decision"] = "none"
            m["basis"] = "no-nominations"
            if m["scoping_incomplete"]:
                m["warnings"].append("scoping-incomplete")
            _count("no_nominations")
            continue
        m["adjudication_emitted"] = True
        new_adjudication_requests.append(_adjudication_request(m))

    # ---- sweep responses -> reopen + fresh adjudication --------------------
    sweep_req_by_id = {r["sweep_id"]: r for r in _read_jsonl_opt(
        run_dir / "sweep_requests.jsonl")}
    reopened = {}
    for raw_line in _read_response_lines(run_dir / "sweep_responses.jsonl"):
        resp, err = _consume("sweep", raw_line)
        if resp is None:
            continue
        sid = resp.get("sweep_id")
        req = sweep_req_by_id.get(sid) if isinstance(sid, str) else None
        if req is None:
            failures_new.append(_mk_failure(
                None, "sweep", ["no-such-request"], resp))
            continue
        batch_ids = {r["record_id"] for r in req["records"]}
        official_ids = {r["official_row_id"] for r in req["official_rows"]}
        errs = validate.validate_sweep_output(resp, batch_ids, official_ids)
        if errs:
            failures_new.append(_mk_failure(None, "sweep", errs, resp))
            continue
        _count("sweep_ok")
        for p in resp["proposals"]:
            m = state_by_id.get(p["record_id"])
            if m is None or m["decision"] not in _SETTLED_NO_MATCH or \
                    m["sweep_round"]:
                continue
            if p["official_row_id"] not in m["nominations"]:
                m["nominations"].append(p["official_row_id"])
            if p["official_row_id"] not in m["sweep_origin_row_ids"]:
                m["sweep_origin_row_ids"].append(p["official_row_id"])
            reopened[p["record_id"]] = m
    for rid, m in reopened.items():
        m["decision"] = None
        m["basis"] = ""
        m["adjudication_failures"] = 0
        m["sweep_round"] = True
        m["adjudication_emitted"] = True
        new_adjudication_requests.append(_adjudication_request(m))

    # ---- adjudication responses -------------------------------------------
    new_comparison_requests = []

    def _emit_comparison(m):
        record = records_by_id[m["record_id"]]
        selected = [rows_by_id[oid] for oid in m["selected_official_row_ids"]
                    if oid in rows_by_id]
        row_payloads = [payloads.official_row_payload(r) for r in selected]
        base = {"record_id": m["record_id"],
                "record": payloads.company_record_payload(record),
                "match_basis": {"basis": m["basis"],
                                "row_quotes": m["row_quotes"],
                                "official_quotes": m["official_quotes"]},
                "sweep_origin_row_ids": m["sweep_origin_row_ids"],
                "instructions_file": "prompts/comparison.md"}
        base_size = _psize(base)
        budget = max(1, schema.COMPARISON_MAX_BYTES - base_size)
        parts = _chunk_by_bytes(row_payloads, budget) \
            if _psize(row_payloads) > budget else [row_payloads]
        split = len(parts) > 1
        if split:
            m["warnings"].append("comparison-split")
            run_warnings_new.append({"code": "comparison-split",
                                     "detail": m["record_id"]})
        for i, part in enumerate(parts):
            cid = f"CMP-{m['record_id']}" + (f"-p{i}" if split else "")
            precs = []
            for rp in part:
                precs.extend(_precedents_for(
                    precedents, rows_by_id[rp["official_row_id"]]))
            m["comparison_units"].append(
                {"comparison_id": cid,
                 "official_row_ids": [rp["official_row_id"] for rp in part],
                 "done": False, "failures": 0, "split": split})
            new_comparison_requests.append(dict(
                base, comparison_id=cid, official_rows=part,
                precedents=precs))

    for raw_line in _read_response_lines(
            run_dir / "adjudication_responses.jsonl"):
        resp, err = _consume("adjudication", raw_line)
        if resp is None:
            continue
        rid = resp.get("record_id") if isinstance(resp.get("record_id"), str) \
            else None
        m = state_by_id.get(rid)
        if m is None or not m["adjudication_emitted"] or \
                m["decision"] is not None:
            failures_new.append(_mk_failure(
                rid, "adjudication", ["no-such-request"], resp))
            continue
        errs = validate.validate_adjudication_output(
            resp, set(m["nominations"]),
            records_by_id.get(rid, {}), rows_by_id,
            require_retry=m["adjudication_failures"] == 1,
            require_sweep_round=m["sweep_round"])
        if errs:
            m["adjudication_failures"] += 1
            failures_new.append(_mk_failure(rid, "adjudication", errs, resp))
            if m["adjudication_failures"] >= 2:
                _count("adjudication_rejected")
                m["decision"] = "unresolved-llm-output-rejected"
                m["warnings"].append("llm-output-rejected")
            else:
                extra = {"retry": True, "previous_errors": errs}
                if m["sweep_round"]:
                    extra["sweep_round"] = True
                new_adjudication_requests.append(
                    _adjudication_request(m, extra=extra))
            continue
        _count("adjudication_ok")
        decision = resp["decision"]
        m["decision"] = decision
        m["basis"] = resp["basis"]
        if decision == "ambiguous":
            m["ambiguous_official_row_ids"] = resp["ambiguous_official_row_ids"]
        elif decision == "match":
            sels = resp["selections"]
            m["selected_official_row_ids"] = [s["official_row_id"]
                                             for s in sels]
            m["row_quotes"] = {s["official_row_id"]: s["row_quote"]
                               for s in sels}
            m["official_quotes"] = {s["official_row_id"]: s["official_quote"]
                                    for s in sels}
            _emit_comparison(m)

    # ---- comparison responses ---------------------------------------------
    unit_by_cid = {}
    for m in match_state:
        for unit in m["comparison_units"]:
            unit_by_cid[unit["comparison_id"]] = (m, unit)
    comparison_req_by_id = {r["comparison_id"]: r for r in _read_jsonl_opt(
        run_dir / "comparison_requests.jsonl")}
    new_findings = []
    for raw_line in _read_response_lines(
            run_dir / "comparison_responses.jsonl"):
        resp, err = _consume("comparison", raw_line)
        if resp is None:
            continue
        cid = resp.get("comparison_id") \
            if isinstance(resp.get("comparison_id"), str) else None
        m, unit = unit_by_cid.get(cid, (None, None))
        if unit is None or unit["done"]:
            failures_new.append(_mk_failure(
                None, "comparison", ["no-such-request"], resp))
            continue
        record = records_by_id.get(m["record_id"], {})
        errs = validate.validate_comparison_output(
            resp, record, rows_by_id, unit["official_row_ids"],
            require_retry=unit["failures"] == 1)
        if errs:
            unit["failures"] += 1
            failures_new.append(_mk_failure(
                m["record_id"], "comparison", errs, resp))
            if unit["failures"] >= 2:
                unit["done"] = True
                unit["rejected"] = True
                _count("comparison_rejected")
                m["warnings"].append("llm-output-rejected")
            else:
                req = comparison_req_by_id.get(cid)
                if req is not None:
                    new_comparison_requests.append(dict(
                        req, retry=True, previous_errors=errs))
            continue
        unit["done"] = True
        _count("comparison_ok")
        m["claim_consistency"] = resp["claim_consistency"]
        m["record_notes"] = resp["record_notes"]
        for entry in resp["per_rule"]:
            official_row = rows_by_id[entry["official_row_id"]]
            new_findings.append(_build_finding(
                record, m, official_row, entry, resp["claim_consistency"],
                resp["record_notes"], unit["split"]))

    # ---- rollup responses --------------------------------------------------
    rollup_req_by_id = {r["rollup_id"]: r for r in _read_jsonl_opt(
        run_dir / "rollup_requests.jsonl")}
    new_rollup_requests = []
    for raw_line in _read_response_lines(run_dir / "rollup_responses.jsonl"):
        resp, err = _consume("rollup", raw_line)
        if resp is None:
            continue
        rup_id = resp.get("rollup_id") \
            if isinstance(resp.get("rollup_id"), str) else None
        entry = rollup_by_id.get(rup_id)
        if entry is None or entry["done"]:
            failures_new.append(_mk_failure(
                None, "rollup", ["no-such-request"], resp))
            continue
        errs = validate.validate_rollup_output(
            resp, entry["record_ids"], require_retry=entry["failures"] == 1)
        if errs:
            entry["failures"] += 1
            failures_new.append(_mk_failure(None, "rollup", errs, resp))
            if entry["failures"] >= 2:
                entry["done"] = True
                entry["rejected"] = True
                _count("rollup_rejected")
            else:
                req = rollup_req_by_id.get(rup_id)
                if req is not None:
                    new_rollup_requests.append(dict(
                        req, retry=True, previous_errors=errs))
            continue
        entry["done"] = True
        _count("rollup_ok")
        entry["result"] = {
            "joint_verdict": resp["joint_verdict"],
            "coverage_of_requirement": resp["coverage_of_requirement"],
            "reasoning": resp["reasoning"],
            "confidence": resp["confidence"],
            "human_review": resp["human_review"]}

    # ---- validation responses ---------------------------------------------
    validation_req_by_id = {r["validation_id"]: r for r in _read_jsonl_opt(
        run_dir / "validation_requests.jsonl")}
    new_validation_requests = []
    for raw_line in _read_response_lines(
            run_dir / "validation_responses.jsonl"):
        resp, err = _consume("validation", raw_line)
        if resp is None:
            continue
        vid = resp.get("validation_id") \
            if isinstance(resp.get("validation_id"), str) else None
        entry = vstate_by_id.get(vid)
        req = validation_req_by_id.get(vid)
        if entry is None or req is None or entry["done"]:
            failures_new.append(_mk_failure(
                None, "validation", ["no-such-request"], resp))
            continue
        req_records = req.get("records") or [req.get("record")] or []
        evidence_source = " ".join(
            [validate.company_quote_source(r) for r in req_records if r] +
            [validate.official_quote_source(r)
             for r in req.get("official_rows", [])])
        errs = validate.validate_validation_output(
            resp, req["claimed"]["verdict"], evidence_source,
            require_retry=entry["failures"] == 1)
        if errs or resp.get("finding_id") != entry["finding_id"]:
            errs = errs or ["wrong-finding-id"]
            entry["failures"] += 1
            failures_new.append(_mk_failure(None, "validation", errs, resp))
            if entry["failures"] >= 2:
                entry["done"] = True
                entry["rejected"] = True
                _count("validation_rejected")
            else:
                new_validation_requests.append(dict(
                    req, retry=True, previous_errors=errs))
            continue
        entry["done"] = True
        _count("validation_ok")
        entry["result"] = {
            "outcome": resp["outcome"],
            "independent_verdict": resp["independent_verdict"],
            "revised_verdict": resp["revised_verdict"],
            "revised_change_analysis": resp["revised_change_analysis"],
            "reason": resp["reason"],
            "evidence_quote": resp["evidence_quote"]}

    # ---- persist -----------------------------------------------------------
    common.write_jsonl(run_dir / "official_rows.jsonl", official_rows)
    common.write_jsonl(run_dir / "official_structure_state.jsonl",
                       structure_state)
    common.write_jsonl(run_dir / "table_state.jsonl", table_state)
    common.write_jsonl(run_dir / "company_records.jsonl", company_records)
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)
    common.write_jsonl(run_dir / "scoping_state.jsonl", scoping_state)
    common.write_jsonl(run_dir / "rollup_state.jsonl", rollup_state)
    common.write_jsonl(run_dir / "validation_state.jsonl", validation_state)
    _append_jsonl(run_dir / "official_structure_requests.jsonl",
                  new_structure_requests)
    _append_jsonl(run_dir / "table_mapping_requests.jsonl",
                  new_mapping_requests)
    _append_jsonl(run_dir / "interpretation_requests.jsonl",
                  new_interp_requests)
    _append_jsonl(run_dir / "scoping_requests.jsonl", new_scoping_requests)
    _append_jsonl(run_dir / "adjudication_requests.jsonl",
                  new_adjudication_requests)
    _append_jsonl(run_dir / "comparison_requests.jsonl",
                  new_comparison_requests)
    _append_jsonl(run_dir / "rollup_requests.jsonl", new_rollup_requests)
    _append_jsonl(run_dir / "validation_requests.jsonl",
                  new_validation_requests)
    _append_jsonl(run_dir / "findings.jsonl", new_findings)
    _append_jsonl(run_dir / "validation_failures.jsonl", failures_new)
    _append_jsonl(run_dir / "run_warnings.jsonl", run_warnings_new)
    for k in schema.RESPONSE_KINDS:
        consumed[k] = sorted(consumed_sets[k])
    _save_consumed(run_dir, consumed)

    pending_adjudication = sum(
        1 for m in match_state
        if m["adjudication_emitted"] and m["decision"] is None)
    pending_scoping = sum(1 for s in scoping_state if not s["done"])
    pending_comparison = sum(
        1 for m in match_state for u in m["comparison_units"]
        if not u["done"])
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"resolve: {summary} pending_scoping={pending_scoping} "
          f"pending_adjudication={pending_adjudication} "
          f"pending_comparison={pending_comparison} "
          f"new_findings={len(new_findings)}")
    return 0


# --------------------------------------------------------------------------
# sweep — one-shot reverse recall barrier
# --------------------------------------------------------------------------

def cmd_sweep(args):
    run_dir = Path(args.run_dir)
    state_path = run_dir / "sweep_state.json"
    if state_path.exists():
        print("sweep: already-done")
        return 0
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
    official_rows = common.read_jsonl(run_dir / "official_rows.jsonl")
    scoping_state = _read_jsonl_opt(run_dir / "scoping_state.jsonl")
    match_state = [_ensure_match_fields(m) for m in
                   _read_jsonl_opt(run_dir / "match_state.jsonl")]

    pending = sum(1 for s in scoping_state if not s["done"]) + \
        sum(1 for m in match_state if m["decision"] is None)
    if pending:
        print(f"sweep: not-ready pending={pending}")
        return 4

    matched_ids = set()
    for m in match_state:
        if m["decision"] == "match":
            matched_ids.update(m["selected_official_row_ids"])
    unmatched = [records_by_id[m["record_id"]] for m in match_state
                 if m["decision"] in _SETTLED_NO_MATCH
                 and records_by_id.get(m["record_id"], {}).get("status") == "ok"]
    unaddressed = [r for r in official_rows
                   if r["official_row_id"] not in matched_ids]
    if not unmatched or not unaddressed:
        state_path.write_text(json.dumps({"done": True, "batches": 0},
                                         indent=1), encoding="utf-8")
        print("sweep: nothing-to-sweep")
        return 0

    official_chunks = _chunk_by_bytes(
        [payloads.official_row_payload(r) for r in unaddressed],
        schema.SCOPING_OFFICIAL_CHUNK_BYTES)
    requests = []
    for bi in range(0, len(unmatched), schema.SWEEP_RECORD_BATCH):
        batch = unmatched[bi:bi + schema.SWEEP_RECORD_BATCH]
        for k, chunk in enumerate(official_chunks):
            requests.append({
                "sweep_id": f"SW-B{bi // schema.SWEEP_RECORD_BATCH}-K{k}",
                "records": [payloads.company_record_payload(r)
                            for r in batch],
                "official_rows": chunk,
                "instructions_file": "prompts/sweep.md"})
    common.write_jsonl(run_dir / "sweep_requests.jsonl", requests)
    state_path.write_text(json.dumps({"done": True,
                                      "batches": len(requests)}, indent=1),
                          encoding="utf-8")
    print(f"sweep: batches={len(requests)} unmatched={len(unmatched)} "
          f"unaddressed={len(unaddressed)}")
    return 0


# --------------------------------------------------------------------------
# rollup — one-shot joint-assessment barrier (1:N requirement)
# --------------------------------------------------------------------------

def cmd_rollup(args):
    run_dir = Path(args.run_dir)
    marker_path = run_dir / "rollup_marker.json"
    if marker_path.exists():
        print("rollup: already-done")
        return 0
    if not (run_dir / "sweep_state.json").exists():
        print("rollup: not-ready (sweep not run)")
        return 4
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
    official_rows = common.read_jsonl(run_dir / "official_rows.jsonl")
    rows_by_id = {r["official_row_id"]: r for r in official_rows}
    match_state = [_ensure_match_fields(m) for m in
                   _read_jsonl_opt(run_dir / "match_state.jsonl")]
    findings = _read_jsonl_opt(run_dir / "findings.jsonl")

    pending = sum(1 for m in match_state if m["decision"] is None) + \
        sum(1 for m in match_state for u in m["comparison_units"]
            if not u["done"])
    if pending:
        print(f"rollup: not-ready pending={pending}")
        return 4

    findings_by_pair = {(f["record_id"], f["official_row_id"]): f
                        for f in findings}
    matchers = {}
    for m in match_state:
        if m["decision"] == "match":
            for oid in m["selected_official_row_ids"]:
                matchers.setdefault(oid, []).append(m["record_id"])

    rollup_state, requests = [], []
    for oid, rids in sorted(matchers.items()):
        contributors = [rid for rid in rids
                        if (rid, oid) in findings_by_pair]
        if len(contributors) < 2 or oid not in rows_by_id:
            continue
        rup_id = common.rollup_id(oid)
        req = {"rollup_id": rup_id,
               "official_row": payloads.official_row_payload(rows_by_id[oid]),
               "company_records": [payloads.company_record_payload(
                   records_by_id[rid]) for rid in contributors],
               "per_record_findings": [
                   {"record_id": rid,
                    "verdict": findings_by_pair[(rid, oid)]["verdict"],
                    "change_analysis":
                        findings_by_pair[(rid, oid)]["change_analysis"],
                    "reasoning": findings_by_pair[(rid, oid)]["reasoning"],
                    "row_quote": findings_by_pair[(rid, oid)]["row_quote"],
                    "official_quote":
                        findings_by_pair[(rid, oid)]["official_quote"]}
                   for rid in contributors],
               "instructions_file": "prompts/rule_rollup.md"}
        oversized = _psize(req) > schema.ROLLUP_MAX_BYTES
        rollup_state.append({"rollup_id": rup_id, "official_row_id": oid,
                             "record_ids": contributors,
                             "oversized": oversized,
                             "done": False, "failures": 0})
        requests.append(req)
    common.write_jsonl(run_dir / "rollup_state.jsonl", rollup_state)
    common.write_jsonl(run_dir / "rollup_requests.jsonl", requests)
    marker_path.write_text(json.dumps({"done": True,
                                       "groups": len(requests)}, indent=1),
                           encoding="utf-8")
    print(f"rollup: groups={len(requests)}")
    return 0


# --------------------------------------------------------------------------
# finalize — gate, validation dispatch, merge, coverage, report
# --------------------------------------------------------------------------

def _validation_request_for_finding(f):
    return {"validation_id": "VAL-" + f["finding_id"],
            "finding_id": f["finding_id"],
            "kind": "comparison",
            "record": f["company_row"],
            "official_rows": [f["official_row"]],
            "claimed": {"verdict": f["verdict"],
                        "change_analysis": f["change_analysis"],
                        "field_alignment": f["field_alignment"],
                        "match_rationale": f["match_rationale"],
                        "semantic_differences": f["semantic_differences"],
                        "reasoning": f["reasoning"],
                        "confidence": f["confidence"],
                        "human_review": f["human_review"],
                        "row_quote": f["row_quote"],
                        "official_quote": f["official_quote"],
                        "match_basis": f["match_basis"]},
            "instructions_file": "prompts/validation.md"}


def _validation_request_for_rollup(entry, records_by_id, rows_by_id):
    result = entry["result"]
    return {"validation_id": "VAL-" + entry["rollup_id"],
            "finding_id": entry["rollup_id"],
            "kind": "rollup",
            "records": [payloads.company_record_payload(records_by_id[rid])
                        for rid in entry["record_ids"]
                        if rid in records_by_id],
            "official_rows": [payloads.official_row_payload(
                rows_by_id[entry["official_row_id"]])]
            if entry["official_row_id"] in rows_by_id else [],
            "claimed": {"verdict": result["joint_verdict"],
                        "coverage_of_requirement":
                            result["coverage_of_requirement"],
                        "reasoning": result["reasoning"],
                        "confidence": result["confidence"],
                        "human_review": result["human_review"]},
            "instructions_file": "prompts/validation.md"}


def _merge_validation(target, ventry):
    """Copy the validator's decision onto a finding/rollup. Every branch
    routes on an enum the LLM chose."""
    if ventry is None:
        target["validation"] = {"status": "validation-not-run"}
        return
    if ventry.get("rejected") or "result" not in ventry:
        target["validation"] = {"status": "llm-output-rejected"}
        return
    r = ventry["result"]
    target["validation"] = {
        "outcome": r["outcome"],
        "independent_verdict": r["independent_verdict"],
        "revised_verdict": r["revised_verdict"],
        "reason": r["reason"],
        "evidence_quote": r["evidence_quote"]}
    if r["outcome"] == "refuted":
        target["disputed"] = True
    elif r["outcome"] == "revised":
        target["first_pass_verdict"] = target["verdict"]
        target["verdict"] = r["revised_verdict"]
        target["verdict_source"] = "validation-revised"
        if r["revised_change_analysis"] is not None and \
                "change_analysis" in target:
            target["change_analysis"] = r["revised_change_analysis"]


_VALIDATION_REVIEW_REASONS = {
    "refuted": "validation-refuted",
    "revised": "validation-revised",
    "needs-human": "validation-needs-human"}


def cmd_finalize(args):
    run_dir = Path(args.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    table_state = _read_jsonl_opt(run_dir / "table_state.jsonl")
    tstate_by_index = {t["table_index"]: t for t in table_state}
    tables_by_index = {t["table_index"]: t for t in skel["tables"]}
    structure_state = _read_jsonl_opt(run_dir / "official_structure_state.jsonl")
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
    official_rows = common.read_jsonl(run_dir / "official_rows.jsonl")
    rows_by_id = {r["official_row_id"]: r for r in official_rows}
    match_state = [_ensure_match_fields(m) for m in
                   _read_jsonl_opt(run_dir / "match_state.jsonl")]
    state_by_id = {m["record_id"]: m for m in match_state}
    scoping_state = _read_jsonl_opt(run_dir / "scoping_state.jsonl")
    rollup_state = _read_jsonl_opt(run_dir / "rollup_state.jsonl")
    validation_state = _read_jsonl_opt(run_dir / "validation_state.jsonl")
    vstate_by_id = {v["validation_id"]: v for v in validation_state}
    findings = _read_jsonl_opt(run_dir / "findings.jsonl")

    # ---- pending inventory -------------------------------------------------
    pending_structure = [s["structure_id"] for s in structure_state
                         if not s["done"]]
    pending_tables = [t["table_index"] for t in table_state
                      if t["classification"] is None]
    pending_chunks = [(t["table_index"], cid)
                      for t in table_state
                      for cid, c in t.get("chunks", {}).items()
                      if not c["done"]]
    pending_scoping = [s["scoping_id"] for s in scoping_state
                       if not s["done"]]
    pending_matching = [m["record_id"] for m in match_state
                        if m["decision"] is None]
    pending_comparison = [u["comparison_id"]
                          for m in match_state
                          for u in m["comparison_units"] if not u["done"]]
    rollup_run = (run_dir / "rollup_marker.json").exists()
    pending_rollup = [] if not rollup_run else \
        [r["rollup_id"] for r in rollup_state if not r["done"]]
    rollup_missing = not rollup_run

    blocking = (pending_tables or pending_chunks or pending_scoping or
                pending_matching or pending_comparison or pending_rollup or
                rollup_missing)
    if blocking and not args.allow_pending:
        print(f"finalize: refused - pending mapping={len(pending_tables)} "
              f"interpretation={len(pending_chunks)} "
              f"scoping={len(pending_scoping)} "
              f"matching={len(pending_matching)} "
              f"comparison={len(pending_comparison)} "
              f"rollup={'not-run' if rollup_missing else len(pending_rollup)} "
              f"(use --allow-pending to force)")
        return 4

    run_warnings_new = []
    # ---- allow-pending settlements (pipeline statuses, never verdicts) ----
    if args.allow_pending:
        for sid in pending_structure:
            run_warnings_new.append({"code": "structure-pass-not-run",
                                     "detail": sid})
        for tix in pending_tables:
            tstate_by_index[tix]["classification"] = "mapping-pass-not-run"
        for tix, cid in pending_chunks:
            ts = tstate_by_index[tix]
            chunk = ts["chunks"][cid]
            chunk["done"] = True
            chunk["not_run"] = True
            table = tables_by_index[tix]
            rows_by_index = {r["row_index"]: r for r in table["rows"]}
            for ri in chunk["row_indexes"]:
                if str(ri) not in ts["row_dispositions"]:
                    ts["row_dispositions"][str(ri)] = "record"
                    rec = canonical.failed_record(
                        table, rows_by_index[ri],
                        "interpretation-pass-not-run")
                    company_records.append(rec)
                    records_by_id[rec["record_id"]] = rec
        for s in scoping_state:
            if not s["done"]:
                s["done"] = True
                s["not_run"] = True
                for rid in s["record_ids"]:
                    if rid in state_by_id:
                        state_by_id[rid]["scoping_incomplete"] = True
                        if "scoping-pass-not-run" not in \
                                state_by_id[rid]["warnings"]:
                            state_by_id[rid]["warnings"].append(
                                "scoping-pass-not-run")
        for rid in pending_matching:
            m = state_by_id.get(rid)
            if m is not None and m["decision"] is None and \
                    "adjudication-pass-not-run" not in m["warnings"] and \
                    m["adjudication_emitted"]:
                m["warnings"].append("adjudication-pass-not-run")
        for m in match_state:
            for u in m["comparison_units"]:
                if not u["done"]:
                    u["done"] = True
                    u["not_run"] = True
        if rollup_missing:
            run_warnings_new.append({"code": "rollup-pass-not-run",
                                     "detail": ""})
        for r in rollup_state:
            if not r["done"]:
                r["done"] = True
                r["not_run"] = True

    # ---- validation dispatch ----------------------------------------------
    new_validation_requests = []
    if not args.allow_pending:
        for f in findings:
            vid = "VAL-" + f["finding_id"]
            if vid not in vstate_by_id:
                entry = {"validation_id": vid,
                         "finding_id": f["finding_id"],
                         "done": False, "failures": 0}
                validation_state.append(entry)
                vstate_by_id[vid] = entry
                new_validation_requests.append(
                    _validation_request_for_finding(f))
        for r in rollup_state:
            if r.get("done") and "result" in r:
                vid = "VAL-" + r["rollup_id"]
                if vid not in vstate_by_id:
                    entry = {"validation_id": vid,
                             "finding_id": r["rollup_id"],
                             "done": False, "failures": 0}
                    validation_state.append(entry)
                    vstate_by_id[vid] = entry
                    new_validation_requests.append(
                        _validation_request_for_rollup(
                            r, records_by_id, rows_by_id))

    # ---- persist bookkeeping before any refusal ---------------------------
    common.write_jsonl(run_dir / "table_state.jsonl", table_state)
    common.write_jsonl(run_dir / "company_records.jsonl", company_records)
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)
    common.write_jsonl(run_dir / "scoping_state.jsonl", scoping_state)
    common.write_jsonl(run_dir / "rollup_state.jsonl", rollup_state)
    common.write_jsonl(run_dir / "validation_state.jsonl", validation_state)
    _append_jsonl(run_dir / "validation_requests.jsonl",
                  new_validation_requests)
    _append_jsonl(run_dir / "run_warnings.jsonl", run_warnings_new)

    pending_validation = [v["validation_id"] for v in validation_state
                          if not v["done"]]
    if pending_validation and not args.allow_pending:
        print(f"finalize: refused - pending validation="
              f"{len(pending_validation)} (dispatch the validation pass, "
              f"then resolve)")
        return 4

    # ---- merge validation + review flags ----------------------------------
    validation_counts = {}
    for f in findings:
        m = state_by_id.get(f["record_id"], _new_match_state("", ""))
        ventry = vstate_by_id.get("VAL-" + f["finding_id"])
        _merge_validation(f, ventry)
        v = f["validation"]
        validation_counts[v.get("outcome", v.get("status"))] = \
            validation_counts.get(v.get("outcome", v.get("status")), 0) + 1

        reasons = []
        if f["human_review"]:
            reasons.append("llm-human-review")
        outcome = v.get("outcome")
        if outcome in _VALIDATION_REVIEW_REASONS:
            reasons.append(_VALIDATION_REVIEW_REASONS[outcome])
        if v.get("status") == "llm-output-rejected":
            reasons.append("validation-rejected")
        if v.get("status") == "validation-not-run":
            reasons.append("validation-not-run")
        if f["claim_consistency"] == "contradicted":
            reasons.append("claim-contradicted")
        record = records_by_id.get(f["record_id"], {})
        if tstate_by_index.get(
                record.get("source_reference", {}).get("table_index"),
                {}).get("classification") == "uncertain":
            reasons.append("uncertain-table")
        if m.get("scoping_incomplete"):
            reasons.append("scoping-incomplete")
        if f.get("comparison_split"):
            reasons.append("comparison-split")
        if any(w in ("llm-output-rejected", "scoping-pass-not-run",
                     "adjudication-pass-not-run")
               for w in m.get("warnings", [])):
            reasons.append("record-had-rejected-output")
        f["review_reasons"] = reasons
        f["human_review_needed"] = bool(reasons)

    # ---- rule rollups ------------------------------------------------------
    findings_by_pair = {(f["record_id"], f["official_row_id"]): f
                        for f in findings}
    rule_rollups = []
    rollup_warnings = []
    for r in rollup_state:
        base = {"rollup_id": r["rollup_id"],
                "official_row_id": r["official_row_id"],
                "display_id": rows_by_id.get(
                    r["official_row_id"], {}).get("display_id"),
                "contributing_record_ids": r["record_ids"],
                "oversized": r.get("oversized", False)}
        if "result" in r:
            base.update(r["result"])
            base["verdict"] = base.pop("joint_verdict")
            _merge_validation(base, vstate_by_id.get("VAL-" + r["rollup_id"]))
            reasons = []
            if base["human_review"]:
                reasons.append("llm-human-review")
            outcome = base["validation"].get("outcome")
            if outcome in _VALIDATION_REVIEW_REASONS:
                reasons.append(_VALIDATION_REVIEW_REASONS[outcome])
            if base["validation"].get("status") in ("llm-output-rejected",
                                                    "validation-not-run"):
                reasons.append("validation-" +
                               ("rejected" if base["validation"]["status"] ==
                                "llm-output-rejected" else "not-run"))
            if base["oversized"]:
                reasons.append("rollup-oversized")
            differs = [rid for rid in r["record_ids"]
                       if (rid, r["official_row_id"]) in findings_by_pair
                       and findings_by_pair[(rid, r["official_row_id"])]
                       ["verdict"] != base["verdict"]]
            if differs:
                reasons.append("rollup-verdict-differs")
                rollup_warnings.append({"code": "rollup-verdict-differs",
                                        "detail": r["official_row_id"]})
                for rid in differs:
                    f = findings_by_pair[(rid, r["official_row_id"])]
                    if "rollup-verdict-differs" not in f["review_reasons"]:
                        f["review_reasons"].append("rollup-verdict-differs")
                        f["human_review_needed"] = True
            base["review_reasons"] = reasons
            base["human_review_needed"] = bool(reasons)
        else:
            base["status"] = "llm-output-rejected" if r.get("rejected") \
                else "rollup-pass-not-run"
            base["human_review_needed"] = True
            base["review_reasons"] = [base["status"]]
        rule_rollups.append(base)

    # ---- dedup -------------------------------------------------------------
    kept, dropped = validate.dedup_findings(findings)

    # ---- coverage ----------------------------------------------------------
    coverage = coverage_mod.compute(skel["tables"], tstate_by_index,
                                    company_records, official_rows,
                                    match_state)
    if not coverage["ok"]:
        print(f"finalize: aborted - coverage not ok: {coverage['warnings']}")
        return 3

    # ---- leftovers ---------------------------------------------------------
    unmatched_rows, ambiguous, unresolved_match = [], [], []
    for m in match_state:
        record = records_by_id.get(m["record_id"])
        if record is None or record.get("status") != "ok":
            continue
        if m["decision"] == "ambiguous":
            ambiguous.append({
                "record_id": m["record_id"],
                "original_company_text": record.get("original_company_text", ""),
                "source_reference": record.get("source_reference", {}),
                "ambiguous_official_row_ids":
                    m.get("ambiguous_official_row_ids", []),
                "basis": m.get("basis", "")})
        elif m["decision"] == "none":
            unmatched_rows.append({
                "record_id": m["record_id"],
                "original_company_text": record.get("original_company_text", ""),
                "source_reference": record.get("source_reference", {}),
                "basis": m.get("basis", ""),
                "warnings": m.get("warnings", [])})
        elif m["decision"] == "unresolved-llm-output-rejected" or \
                m["decision"] is None:
            unresolved_match.append({
                "record_id": m["record_id"],
                "status": m["decision"] or "match-pass-not-run",
                "original_company_text": record.get("original_company_text", ""),
                "source_reference": record.get("source_reference", {}),
                "warnings": m.get("warnings", [])})

    unresolved_rows = [
        {"record_id": r["record_id"], "status": r.get("status"),
         "notes": r.get("notes", ""),
         "source_reference": r.get("source_reference", {}),
         "original_company_text": r.get("original_company_text", "")}
        for r in company_records
        if r["status"] == "extraction-failed"] + unresolved_match

    unresolved_pairs = []
    for m in match_state:
        for u in m["comparison_units"]:
            status = None
            if u.get("rejected"):
                status = "comparison-unresolved/llm-output-rejected"
            elif u.get("not_run"):
                status = "comparison-pass-not-run"
            if status:
                for oid in u["official_row_ids"]:
                    if (m["record_id"], oid) not in \
                            {(f["record_id"], f["official_row_id"])
                             for f in kept}:
                        unresolved_pairs.append(
                            {"record_id": m["record_id"],
                             "official_row_id": oid, "status": status})

    matched_union = set()
    for m in match_state:
        if m["decision"] == "match":
            matched_union.update(m["selected_official_row_ids"])
    unaddressed_rules = [payloads.official_row_payload(r)
                         for r in official_rows
                         if r["official_row_id"] not in matched_union]

    # ---- table triage ------------------------------------------------------
    table_triage = []
    triage_warnings = []
    for t in skel["tables"]:
        ts = tstate_by_index.get(t["table_index"], {})
        table_triage.append({
            "table_index": t["table_index"],
            "sheet_or_section": t["sheet_or_section"],
            "classification": ts.get("classification"),
            "irrelevant_reason": ts.get("irrelevant_reason", ""),
            "context_grouping": ts.get("context_grouping", ""),
            "row_count": len(t["rows"]),
            "column_mapping": ts.get("column_mapping", {})})
        if ts.get("classification") == "uncertain":
            triage_warnings.append({"code": "uncertain-table",
                                    "detail": f"table={t['table_index']}"})
        elif ts.get("classification") in ("mapping-failed",
                                          "mapping-pass-not-run"):
            triage_warnings.append({"code": "mapping-failed",
                                    "detail": f"table={t['table_index']}"})

    # ---- warnings ----------------------------------------------------------
    extract_warnings = json.loads(
        (run_dir / "extract_warnings.json").read_text(encoding="utf-8")) \
        if (run_dir / "extract_warnings.json").exists() else []
    run_warnings = _read_jsonl_opt(run_dir / "run_warnings.jsonl")
    warnings = (list(extract_warnings) + list(run_warnings) +
                list(coverage["warnings"]) +
                [{"code": "duplicate-finding-dropped", "detail": fid}
                 for fid in dropped] +
                rollup_warnings + triage_warnings)

    final = {
        "manifest": manifest,
        "findings": kept,
        "rule_rollups": rule_rollups,
        "match_state": match_state,
        "coverage": coverage,
        "warnings": warnings,
        "unmatched_rows": unmatched_rows,
        "ambiguous": ambiguous,
        "unresolved_rows": unresolved_rows,
        "unresolved_pairs": unresolved_pairs,
        "unaddressed_rules": unaddressed_rules,
        "table_triage": table_triage,
    }
    (run_dir / "final.json").write_text(json.dumps(final, indent=1),
                                        encoding="utf-8")

    common.write_jsonl(run_dir / "table_state.jsonl", table_state)
    common.write_jsonl(run_dir / "company_records.jsonl", company_records)
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)

    if not args.no_report:
        import report
        report.render(run_dir)

    vsum = " ".join(f"{k}={v}" for k, v in sorted(validation_counts.items()))
    print(f"finalize: findings={len(kept)} rollups={len(rule_rollups)} "
          f"dropped_dupes={len(dropped)} coverage_ok={coverage['ok']} "
          f"validation[{vsum}] "
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

    for name in ("resolve", "sweep", "rollup"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--run-dir", required=True)
    p_finalize.add_argument("--no-report", action="store_true")
    p_finalize.add_argument("--allow-pending", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "resolve":
        return cmd_resolve(args)
    if args.cmd == "sweep":
        return cmd_sweep(args)
    if args.cmd == "rollup":
        return cmd_rollup(args)
    if args.cmd == "finalize":
        return cmd_finalize(args)
    raise ValueError(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
