import json
from pathlib import Path

import pytest

import common
import feedback


def _final():
    finding = {
        "finding_id": "F-1", "record_id": "CR-1", "row_id": "R-1",
        "official_row_id": "OR-1", "display_id": "V-1001",
        "verdict": "Compliant", "company_row": {"cells": ["x"]},
        "official_row": {"official_row_id": "OR-1", "raw_record": {"A": "x"}}}
    rollup = {"rollup_id": "RU-1", "official_row_id": "OR-2",
              "display_id": "V-1002", "verdict": "Deviating",
              "contributing_record_ids": ["CR-1", "CR-2"]}
    return {"manifest": {"official_sha256": "a" * 64,
                         "company_sha256": "b" * 64, "versions": {}},
            "findings": [finding], "rule_rollups": [rollup]}


@pytest.fixture()
def setup(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final.json").write_text(json.dumps(_final()),
                                        encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    fb = tmp_path / "feedback.json"
    fb.write_text(json.dumps({
        "run": {"started": "2026-08-12T00:00:00"},
        "feedback": [
            {"finding_id": "F-1", "classification": "incorrect",
             "comment": "the approved setting is actually weaker"},
            {"finding_id": "RU-1", "classification": "correct",
             "comment": ""},
            {"finding_id": "F-404", "classification": "other",
             "comment": ""}]}), encoding="utf-8")
    return run_dir, pkg, fb


def test_ingest_stores_verbatim_and_indexes_precedents(setup):
    run_dir, pkg, fb = setup
    result = feedback.ingest(fb, run_dir, pkg)
    assert len(result["stored"]) == 2
    assert len(result["cases"]) == 2
    assert len(result["precedents"]) == 2
    assert result["errors"] == ["unknown finding_id: F-404"]

    fb_files = sorted((pkg / "feedback").glob("FB-*.json"))
    assert len(fb_files) == 2
    records = [json.loads(p.read_text(encoding="utf-8")) for p in fb_files]
    by_fid = {r["finding_id"]: r for r in records}
    # Verbatim: the reviewer's words and the finding snapshot, untouched.
    assert by_fid["F-1"]["comment"] == \
        "the approved setting is actually weaker"
    assert by_fid["F-1"]["classification"] == "incorrect"
    assert by_fid["F-1"]["snapshot"]["verdict"] == "Compliant"
    assert by_fid["RU-1"]["kind"] == "rollup"

    precedents = common.read_jsonl(pkg / "feedback" / "precedents.jsonl")
    by_row = {p["official_row_id"]: p for p in precedents}
    assert by_row["OR-1"]["prior_verdict"] == "Compliant"
    assert by_row["OR-1"]["comment"] == \
        "the approved setting is actually weaker"
    assert by_row["OR-2"]["display_id"] == "V-1002"

    cases = sorted((pkg / "tests" / "regression").glob("RC-*.json"))
    assert len(cases) == 2
    case = json.loads(cases[0].read_text(encoding="utf-8"))
    assert case["advisory"] is True
    assert case["classification"] in ("incorrect", "correct")


def test_duplicate_ingest_rejected(setup):
    run_dir, pkg, fb = setup
    feedback.ingest(fb, run_dir, pkg)
    result = feedback.ingest(fb, run_dir, pkg)
    assert result["stored"] == []
    assert all("duplicate-feedback" in e or "unknown" in e
               for e in result["errors"])


def test_no_interpretation_machinery_left():
    for gone in ("_RULE_MAPPING", "_FIELD_ALIASES", "_OTHER_FIELD_PATTERNS",
                 "_candidate_draft", "_expected_for",
                 "_comment_names_other_field"):
        assert not hasattr(feedback, gone), gone


def test_precedent_injection_into_comparison(setup, monkeypatch, tmp_path):
    """pipeline injects precedents by mechanical official-row key; the
    request carries them verbatim for the LLM to judge."""
    import pipeline
    precedents = [{"feedback_id": "FB-1", "official_row_id": "OR-1",
                   "display_id": "V-1001", "classification": "incorrect",
                   "comment": "check the weaker setting",
                   "prior_verdict": "Compliant"}]
    row = {"official_row_id": "OR-1", "display_id": "V-1001"}
    out = pipeline._precedents_for(precedents, row)
    assert out == [{"feedback_id": "FB-1", "official_row_id": "OR-1",
                    "classification": "incorrect",
                    "comment": "check the weaker setting",
                    "prior_verdict": "Compliant"}]
    # Also matches by display_id when the row hash changed across files.
    row2 = {"official_row_id": "OR-different", "display_id": "V-1001"}
    assert pipeline._precedents_for(precedents, row2)
    row3 = {"official_row_id": "OR-x", "display_id": "V-9999"}
    assert pipeline._precedents_for(precedents, row3) == []
