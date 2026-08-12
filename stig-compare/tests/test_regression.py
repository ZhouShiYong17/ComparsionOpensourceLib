import json
from pathlib import Path

import regression


_COMPANY = {"record_id": "CR-1", "row_id": "R-1",
            "header_row": ["REQ", "SETTING"],
            "cells": ["Password reuse must be restricted", "5"],
            "continuation_cells": [], "merged": False,
            "preceding_narrative": "", "context_grouping": "",
            "canonical_fields": {}, "field_provenance": {},
            "interpretation_note": "", "company_claim_reading": "none",
            "original_company_text": "Password reuse must be restricted | 5",
            "status": "ok", "notes": "",
            "source_reference": {"table_index": 1, "row_index": 1}}

_OFFICIAL = {"official_row_id": "OR-1", "display_id": "V-1001",
             "headers": ["Rule ID", "Title"],
             "cells": ["V-1001", "Password reuse must be restricted"],
             "raw_record": {"Rule ID": "V-1001",
                            "Title": "Password reuse must be restricted"},
             "sheet_or_section": "csv", "row_number": 2,
             "provenance": {"source_file": "o.csv", "locator": "csv,row=2"},
             "column_roles": None}


def _pkg(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "tests" / "regression").mkdir(parents=True)
    case = {"case_id": "RC-aaa", "feedback_id": "FB-aaa",
            "kind": "comparison", "classification": "incorrect",
            "comment": "verdict looked wrong", "advisory": True,
            "snapshot": {"finding_id": "F-1", "record_id": "CR-1",
                         "official_row_id": "OR-1", "verdict": "Compliant",
                         "company_row": _COMPANY, "official_row": _OFFICIAL,
                         "match_basis": {"basis": "b"}},
            "manifest": {}}
    (pkg / "tests" / "regression" / "RC-aaa.json").write_text(
        json.dumps(case), encoding="utf-8")
    rollup_case = {"case_id": "RC-bbb", "kind": "rollup",
                   "classification": "correct", "comment": "",
                   "advisory": True, "snapshot": {"rollup_id": "RU-1"}}
    (pkg / "tests" / "regression" / "RC-bbb.json").write_text(
        json.dumps(rollup_case), encoding="utf-8")
    return pkg


def test_build_replay_freezes_comparison_requests(tmp_path):
    pkg = _pkg(tmp_path)
    rd = tmp_path / "replay"
    result = regression.build_replay(pkg, rd)
    assert result["requests"] == 1
    assert result["skipped"] == ["RC-bbb"]
    reqs = [json.loads(l) for l in
            (rd / "replay_requests.jsonl").read_text("utf-8").splitlines()]
    req = reqs[0]
    assert req["comparison_id"] == "RPL-RC-aaa"
    assert req["record"]["cells"]                 # complete payloads frozen
    assert req["official_rows"][0]["raw_record"]
    assert req["instructions_file"] == "prompts/comparison.md"


def _answer(req, verdict):
    row = req["official_rows"][0]
    return {"comparison_id": req["comparison_id"],
            "record_id": req["record_id"],
            "per_rule": [{
                "official_row_id": row["official_row_id"],
                "match_rationale": "m",
                "field_alignment": [],
                "semantic_differences": "s",
                "change_analysis": ["weakened"],
                "verdict": verdict, "confidence": "High",
                "human_review": False,
                "row_quote": req["record"]["cells"][0],
                "official_quote": row["cells"][1],
                "reasoning": "fresh look"}],
            "claim_consistency": "no-claim", "record_notes": ""}


def test_evaluate_replay_diffs_verdicts_advisory(tmp_path):
    pkg = _pkg(tmp_path)
    rd = tmp_path / "replay"
    regression.build_replay(pkg, rd)
    reqs = [json.loads(l) for l in
            (rd / "replay_requests.jsonl").read_text("utf-8").splitlines()]
    with open(rd / "replay_responses.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(_answer(reqs[0], "Deviating")) + "\n")
    report = regression.evaluate_replay(pkg, rd)
    assert report["advisory"] is True
    assert report["answered"] == 1
    r = report["results"][0]
    assert r["prior_verdict"] == "Compliant"
    assert r["fresh_verdict"] == "Deviating"
    assert r["agrees_with_prior"] is False
    assert r["reviewer_classification"] == "incorrect"
    assert r["reviewer_comment"] == "verdict looked wrong"


def test_evaluate_replay_validates_mechanically(tmp_path):
    pkg = _pkg(tmp_path)
    rd = tmp_path / "replay"
    regression.build_replay(pkg, rd)
    reqs = [json.loads(l) for l in
            (rd / "replay_requests.jsonl").read_text("utf-8").splitlines()]
    bad = _answer(reqs[0], "Non-Compliant")       # not a legal verdict
    with open(rd / "replay_responses.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(bad) + "\n")
        f.write("not json\n")
    report = regression.evaluate_replay(pkg, rd)
    assert report["answered"] == 0
    assert len(report["invalid"]) == 2
    assert report["unanswered"] == ["RPL-RC-aaa"]


def test_no_gate_machinery_left():
    for gone in ("run_case", "run_suite", "evaluate_candidate",
                 "approve_candidate"):
        assert not hasattr(regression, gone), gone
