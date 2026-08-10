"""Regression suite runner and rule-approval gate (spec sections 9-10).

`run_case`/`run_suite` replay ONLY the deterministic stages of the pipeline
(candidate generation + deterministic value comparison) against a frozen
case snapshot -- never the LLM matching/semantic/skeptic passes, so a suite
run never talks to the network and never depends on Claude output.

`evaluate_candidate` is the approval gate a human maintainer consults before
a candidate rule (drafted by feedback.py, see spec section 9) may become
active: it never writes the registry itself, so the gate cannot be bypassed
by simply calling the "evaluation" step. `approve_candidate` performs the
write, and re-checks the gate itself (defense in depth) so it can never be
called on a candidate that would regress the suite, even if a caller skips
straight to it.
"""
import json
from datetime import datetime
from pathlib import Path

import candidates as candidates_mod
import compare_values
import rules as rules_mod

_DETERMINISTIC_TIERS = ("T0", "T1")

# Company-row fields a scoped rule (ignore-field, etc.) may target. Used only
# to probe rules.applicable_rules() per field so field-level scopes are
# honored in addition to sheet-or-section/document-type/global scopes.
_ROW_FIELDS = ["stig_description", "stig_objective_or_requirement",
               "stig_command_or_value",
               "company_approved_setting_or_expected_value",
               "observed_value_or_evidence", "context_grouping",
               "original_company_text"]


def _ignore_fields_for(company_row, registry):
    """Field names to blank before replay, per active ignore-field rules
    that apply to this row (spec section 10 scope precedence/conflicts)."""
    source_ref = company_row.get("source_reference") or {}
    doc_type = source_ref.get("document_type", "")
    sheet = source_ref.get("sheet_or_section", "")

    targets = set()
    for field in _ROW_FIELDS:
        context = {"document_type": doc_type, "sheet_or_section": sheet,
                   "field": field}
        applied, _ = rules_mod.applicable_rules(registry, context)
        for r in applied:
            if r["category"] == "ignore-field":
                target = r.get("payload", {}).get("field")
                if target:
                    targets.add(target)
    return targets


def _replay_row(company_row, registry):
    """A copy of company_row with any actively-ignored fields blanked."""
    row = dict(company_row)
    for field in _ignore_fields_for(company_row, registry):
        if field in row:
            row[field] = ""
    return row


def run_case(case, registry):
    """Replay the deterministic stages of one regression case's snapshot
    and evaluate it against `expected` (spec section 9/13-14)."""
    case_id = case["case_id"]
    snapshot = case["snapshot"]
    official_rules = snapshot["official_rules"]
    expected = case.get("expected", {}) or {}

    row = _replay_row(snapshot["company_row"], registry)
    rules_by_id = {r["rule_id"]: r for r in official_rules}

    matches = candidates_mod.generate([row], official_rules)
    match = matches[0] if matches else {"tier": None, "matched_rule_id": None}
    tier = match.get("tier")
    matched_rule_id = match.get("matched_rule_id")
    deterministic_matched = tier in _DETERMINISTIC_TIERS and \
        matched_rule_id is not None

    verdict = None
    if deterministic_matched:
        rule = rules_by_id.get(matched_rule_id)
        if rule is not None:
            result = compare_values.deterministic_verdict(row, rule)
            verdict = result["verdict"] if result is not None else None

    if "not_matched_rule_id" in expected:
        target = expected["not_matched_rule_id"]
        still_matches = deterministic_matched and matched_rule_id == target
        return {"case_id": case_id, "passed": not still_matches,
                "advisory": False,
                "detail": f"tier={tier} matched_rule_id={matched_rule_id}"}

    if "not_verdict" in expected:
        target = expected["not_verdict"]
        if verdict is None:
            return {"case_id": case_id, "passed": True, "advisory": True,
                    "detail": "replay verdict is semantic (None)"}
        return {"case_id": case_id, "passed": verdict != target,
                "advisory": False, "detail": f"verdict={verdict}"}

    if "verdict" in expected and "matched_rule_id" in expected:
        target_verdict = expected["verdict"]
        target_rule = expected["matched_rule_id"]
        matched_ok = deterministic_matched and matched_rule_id == target_rule
        if not matched_ok:
            passed, advisory = False, False
        elif verdict is None:
            # match still holds, but the verdict itself is only decidable
            # semantically now -- defer that aspect to agent review.
            passed, advisory = True, True
        else:
            passed, advisory = (verdict == target_verdict), False
        return {"case_id": case_id, "passed": passed, "advisory": advisory,
                "detail": f"tier={tier} matched_rule_id={matched_rule_id} "
                          f"verdict={verdict}"}

    if expected.get("needs_human_review") or expected.get("note_only"):
        return {"case_id": case_id, "passed": True, "advisory": True,
                "detail": "agent-evaluated expectation"}

    # No recognized deterministic expectation -- nothing to replay-check.
    return {"case_id": case_id, "passed": True, "advisory": True,
            "detail": "no deterministic expectation"}


def run_suite(package_root, registry=None):
    """Run every tests/regression/RC-*.json case against `registry`
    (spec section 9). `registry=None` loads the active registry.json."""
    package_root = Path(package_root)
    if registry is None:
        registry = rules_mod.load_registry(
            package_root / "rules" / "registry.json")

    regression_dir = package_root / "tests" / "regression"
    case_files = sorted(regression_dir.glob("RC-*.json"))

    total = passed = failed = advisory = 0
    failures = []
    for cf in case_files:
        case = json.loads(cf.read_text(encoding="utf-8"))
        result = run_case(case, registry)
        total += 1
        if result["advisory"]:
            advisory += 1
        if result["passed"]:
            passed += 1
        else:
            failed += 1
            failures.append(result)

    return {"total": total, "passed": passed, "failed": failed,
            "advisory": advisory, "failures": failures}


def evaluate_candidate(package_root, candidate_path):
    """The approval gate (spec section 10): never writes the registry."""
    package_root = Path(package_root)
    candidate_path = Path(candidate_path)
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_id = candidate["rule_id"]

    active_registry = rules_mod.load_registry(
        package_root / "rules" / "registry.json")
    baseline = run_suite(package_root, active_registry)

    trial_candidate = dict(candidate)
    trial_candidate["status"] = "active"
    trial_registry = {
        "registry_version": active_registry.get("registry_version"),
        "rules": list(active_registry.get("rules", [])) + [trial_candidate]}
    trial = run_suite(package_root, trial_registry)

    baseline_failed = {f["case_id"] for f in baseline["failures"]}
    trial_failed = {f["case_id"] for f in trial["failures"]}
    regressions = sorted(trial_failed - baseline_failed)
    approvable = (regressions == [] and trial["failed"] == 0)

    return {"candidate_id": candidate_id, "baseline": baseline,
            "trial": trial, "regressions": regressions,
            "approvable": approvable}


def approve_candidate(package_root, candidate_path, approver):
    """Moves an approvable candidate into registry.json as an active rule.

    Raises RuntimeError if the gate says the candidate is not approvable --
    this re-check happens even though a caller is expected to have already
    consulted `evaluate_candidate`, so the gate cannot be skipped
    programmatically (spec section 10, defense in depth).
    """
    package_root = Path(package_root)
    candidate_path = Path(candidate_path)

    verdict = evaluate_candidate(package_root, candidate_path)
    if not verdict["approvable"]:
        raise RuntimeError(
            f"candidate not approvable: {verdict['candidate_id']} "
            f"regressions={len(verdict['regressions'])} "
            f"trial_failed={verdict['trial']['failed']}")

    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["status"] = "active"
    provenance = dict(candidate.get("provenance") or {})
    provenance["approved_by"] = approver
    provenance["approved"] = datetime.now().isoformat(timespec="seconds")
    candidate["provenance"] = provenance

    registry_path = package_root / "rules" / "registry.json"
    registry = rules_mod.load_registry(registry_path)
    registry.setdefault("rules", []).append(candidate)
    registry["registry_version"] = registry.get("registry_version", 0) + 1
    registry_path.write_text(json.dumps(registry, indent=1), encoding="utf-8")

    candidate_path.unlink()

    return {"candidate_id": candidate["rule_id"], "approved_by": approver,
            "registry_version": registry["registry_version"]}
