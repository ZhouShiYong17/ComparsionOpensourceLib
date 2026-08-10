import json
from pathlib import Path

import pytest

import feedback


@pytest.fixture()
def env(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "feedback").mkdir(parents=True)
    (pkg / "tests" / "regression").mkdir(parents=True)
    (pkg / "rules" / "candidates").mkdir(parents=True)
    run = tmp_path / "run"
    run.mkdir()
    final = {"manifest": {"started": "2026-08-10T12:00:00",
                          "official_sha256": "a" * 64,
                          "company_sha256": "b" * 64,
                          "versions": {"skill_version": "0.1.0"}},
             "findings": [{"finding_id": "F-11112222", "row_id": "R-aaaa0001",
                           "rule_id": "V-1001", "verdict": "Compliant",
                           "match": {"tier": "T2"},
                           "company_row": {"original_company_text": "row text",
                                           "source_reference": {"table_index": 1,
                                                                "row_index": 1}},
                           "official_rule": {"rule_id": "V-1001",
                                             "title": "t", "check_text": "c"}}]}
    (run / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return pkg, run


def _fb(items):
    return {"run": {"started": "2026-08-10T12:00:00"}, "feedback": items}


def test_wrong_match_creates_case_and_candidate(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "wrong match",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert len(result["stored"]) == 1
    assert len(result["cases"]) == 1
    assert len(result["candidates"]) == 1
    case = json.loads(next((pkg / "tests" / "regression").glob("RC-*.json"))
                      .read_text(encoding="utf-8"))
    assert case["expected"] == {"not_matched_rule_id": "V-1001"}
    cand = json.loads(next((pkg / "rules" / "candidates").glob("RL-*.json"))
                      .read_text(encoding="utf-8"))
    assert cand["status"] == "candidate"          # never active automatically
    assert cand["provenance"]["feedback_ids"] == result["stored"]


def test_correct_pins_result_but_no_rule(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "correct",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert len(result["cases"]) == 1
    assert result["candidates"] == []
    case = json.loads(next((pkg / "tests" / "regression").glob("RC-*.json"))
                      .read_text(encoding="utf-8"))
    assert case["expected"] == {"verdict": "Compliant",
                                "matched_rule_id": "V-1001"}


def test_unknown_finding_is_visible_error(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-doesnot1",
                                  "classification": "incorrect",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert result["stored"] == []
    assert any("F-doesnot1" in e for e in result["errors"])


def test_duplicate_feedback_skipped(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "wrong match",
                                  "comment": ""}])), encoding="utf-8")
    feedback.ingest(p, run, pkg)
    result2 = feedback.ingest(p, run, pkg)
    assert result2["stored"] == []
    assert any("duplicate-feedback" in e for e in result2["errors"])
