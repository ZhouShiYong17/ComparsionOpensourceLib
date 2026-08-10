import json
from pathlib import Path

import pytest

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
