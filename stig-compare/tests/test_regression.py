import json
from pathlib import Path

import pytest

import feedback
import regression


_SNAPSHOT = {
    "company_row": {"row_id": "R-aaaa0001", "status": "ok",
                    "context_grouping": "High",
                    "stig_description": "reuse recent passwords",
                    "stig_objective_or_requirement":
                        "Password reuse must be restricted",
                    "stig_command_or_value":
                        "Run SHOW PARAMETER password_reuse_max",
                    "company_approved_setting_or_expected_value": "9 or more",
                    "observed_value_or_evidence": "9",
                    "original_company_text":
                        "High | reuse | password_reuse_max | 9"},
    "official_rules": [
        {"rule_id": "V-1001", "title": "Password reuse must be restricted",
         "severity": "high",
         "check_text": "Run SHOW PARAMETER password_reuse_max",
         "fix_text": "Set password_reuse_max to 9 or more.",
         "expected_value": "9 or more"}],
}


def _pkg(tmp_path, cases):
    pkg = tmp_path / "pkg"
    (pkg / "tests" / "regression").mkdir(parents=True)
    (pkg / "rules" / "candidates").mkdir(parents=True)
    (pkg / "rules" / "registry.json").write_text(
        json.dumps({"registry_version": 1, "rules": []}), encoding="utf-8")
    for i, case in enumerate(cases):
        (pkg / "tests" / "regression" / f"RC-{i:08d}.json").write_text(
            json.dumps(case), encoding="utf-8")
    return pkg


def test_pin_case_passes(tmp_path):
    case = {"case_id": "RC-00000000", "feedback_id": "FB-x",
            "snapshot": _SNAPSHOT,
            "expected": {"verdict": "Compliant", "matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [case])
    result = regression.run_suite(pkg)
    assert result["total"] == 1 and result["passed"] == 1


def test_not_matched_case_fails_when_replay_still_matches(tmp_path):
    case = {"case_id": "RC-00000000", "feedback_id": "FB-x",
            "snapshot": _SNAPSHOT,
            "expected": {"not_matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [case])
    result = regression.run_suite(pkg)
    assert result["failed"] == 1        # T1 still matches V-1001 -> user's
    #                                     complaint is not yet fixed by any rule


def test_gate_blocks_harmful_candidate(tmp_path):
    pin = {"case_id": "RC-00000000", "feedback_id": "FB-a",
           "snapshot": _SNAPSHOT,
           "expected": {"verdict": "Compliant", "matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [pin])
    # candidate that would ignore observed evidence globally -> breaks the pin
    cand = {"rule_id": "RL-bad00001", "version": 1, "category": "ignore-field",
            "scope": {"level": "global", "value": None}, "status": "candidate",
            "payload": {"field": "observed_value_or_evidence"},
            "provenance": {"feedback_ids": ["FB-b"], "approved_by": None,
                           "created": "2026-08-10", "approved": None}}
    cpath = pkg / "rules" / "candidates" / "RL-bad00001.json"
    cpath.write_text(json.dumps(cand), encoding="utf-8")
    verdict = regression.evaluate_candidate(pkg, cpath)
    assert verdict["approvable"] is False
    assert "RC-00000000" in verdict["regressions"]
    with pytest.raises(RuntimeError):
        regression.approve_candidate(pkg, cpath, approver="tester")


def test_approve_writes_registry_and_bumps_version(tmp_path):
    pkg = _pkg(tmp_path, [])            # no cases -> nothing can regress
    cand = {"rule_id": "RL-good0001", "version": 1,
            "category": "equivalent-terminology",
            "scope": {"level": "field", "value": "observed_value_or_evidence"},
            "status": "candidate", "payload": {"a": "enabled", "b": "turned on"},
            "provenance": {"feedback_ids": ["FB-c"], "approved_by": None,
                           "created": "2026-08-10", "approved": None}}
    cpath = pkg / "rules" / "candidates" / "RL-good0001.json"
    cpath.write_text(json.dumps(cand), encoding="utf-8")
    regression.approve_candidate(pkg, cpath, approver="maintainer")
    reg = json.loads((pkg / "rules" / "registry.json").read_text(encoding="utf-8"))
    assert reg["registry_version"] == 2
    assert reg["rules"][0]["rule_id"] == "RL-good0001"
    assert reg["rules"][0]["status"] == "active"
    assert reg["rules"][0]["provenance"]["approved_by"] == "maintainer"
    assert not cpath.exists()


# -- post-review hardening: one bad case must not crash the whole gate,
# and approve_candidate must be safe to retry after a partial failure.


def test_malformed_case_does_not_abort_suite(tmp_path):
    good = {"case_id": "RC-00000000", "feedback_id": "FB-x",
            "snapshot": _SNAPSHOT,
            "expected": {"verdict": "Compliant", "matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [good])
    # a garbage case file dropped alongside the good one (e.g. a truncated
    # write, or a hand-edited/foreign RC file) must not abort the suite
    (pkg / "tests" / "regression" / "RC-99999999.json").write_text(
        "{not valid json", encoding="utf-8")

    result = regression.run_suite(pkg)

    assert result["total"] == 2
    assert result["passed"] == 1
    assert result["failed"] == 1
    bad = next(f for f in result["failures"] if f["case_id"] != "RC-00000000")
    assert bad["case_id"] == "RC-99999999"      # fell back to the filename
    assert bad["detail"].startswith("unreplayable:")
    assert bad["advisory"] is False


def test_approve_retry_after_stale_candidate_file_is_idempotent(tmp_path):
    pkg = _pkg(tmp_path, [])            # no cases -> nothing can regress
    cand = {"rule_id": "RL-good0002", "version": 1,
            "category": "equivalent-terminology",
            "scope": {"level": "field", "value": "observed_value_or_evidence"},
            "status": "candidate", "payload": {"a": "enabled", "b": "turned on"},
            "provenance": {"feedback_ids": ["FB-c"], "approved_by": None,
                           "created": "2026-08-10", "approved": None}}
    cand_json = json.dumps(cand)
    cpath = pkg / "rules" / "candidates" / "RL-good0002.json"
    cpath.write_text(cand_json, encoding="utf-8")

    result1 = regression.approve_candidate(pkg, cpath, approver="maintainer")
    assert result1["already_approved"] is False
    reg1 = json.loads((pkg / "rules" / "registry.json").read_text(encoding="utf-8"))
    assert reg1["registry_version"] == 2
    assert len(reg1["rules"]) == 1

    # simulate a stale-candidate retry: the registry write succeeded but the
    # candidate-file delete didn't happen (crash/retry before cleanup), so
    # the candidate file reappears at the same path before a second
    # approve_candidate call for the same rule_id.
    cpath.write_text(cand_json, encoding="utf-8")
    result2 = regression.approve_candidate(pkg, cpath, approver="maintainer")
    assert result2["already_approved"] is True

    reg2 = json.loads((pkg / "rules" / "registry.json").read_text(encoding="utf-8"))
    assert reg2["registry_version"] == 2        # not double-bumped
    assert len(reg2["rules"]) == 1               # no duplicate entry
    assert reg2["rules"][0]["rule_id"] == "RL-good0002"
    assert not cpath.exists()


# -- cross-task: Task 13's feedback.ingest() must write a snapshot that
# Task 14's regression.run_suite() can actually replay, not just the
# trimmed audit excerpt.


def test_ingest_produces_replayable_case_for_correct_classification(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "feedback").mkdir(parents=True)
    (pkg / "tests" / "regression").mkdir(parents=True)
    (pkg / "rules" / "candidates").mkdir(parents=True)
    (pkg / "rules" / "registry.json").write_text(
        json.dumps({"registry_version": 1, "rules": []}), encoding="utf-8")

    company_row = _SNAPSHOT["company_row"]
    official_rule = _SNAPSHOT["official_rules"][0]

    run = tmp_path / "run"
    run.mkdir()
    final = {
        "manifest": {"started": "2026-08-10T12:00:00",
                     "official_sha256": "a" * 64, "company_sha256": "b" * 64,
                     "versions": {"skill_version": "0.1.0"}},
        "findings": [{
            "finding_id": "F-11112222", "row_id": company_row["row_id"],
            "rule_id": official_rule["rule_id"], "verdict": "Compliant",
            "match": {"tier": "T1"},
            "company_row": {
                "original_company_text": company_row["original_company_text"],
                "source_reference": {}},
            "official_rule": official_rule}]}
    (run / "final.json").write_text(json.dumps(final), encoding="utf-8")
    (run / "company_rows.jsonl").write_text(
        json.dumps(company_row) + "\n", encoding="utf-8")
    (run / "official_rules.jsonl").write_text(
        json.dumps(official_rule) + "\n", encoding="utf-8")

    fb_path = tmp_path / "fb.json"
    fb_path.write_text(json.dumps({
        "run": {"started": "2026-08-10T12:00:00"},
        "feedback": [{"finding_id": "F-11112222", "classification": "correct",
                      "comment": ""}]}), encoding="utf-8")

    result = feedback.ingest(fb_path, run, pkg)
    assert len(result["cases"]) == 1
    case_path = next((pkg / "tests" / "regression").glob("RC-*.json"))
    case = json.loads(case_path.read_text(encoding="utf-8"))
    assert "replay_note" not in case          # full row/rule were available
    assert "company_row" in case["snapshot"]
    assert "official_rules" in case["snapshot"]

    suite = regression.run_suite(pkg)
    assert suite["total"] == 1
    assert suite["passed"] == 1
    assert suite["failed"] == 0
