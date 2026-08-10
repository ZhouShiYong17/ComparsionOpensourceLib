import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all
import common
import pipeline


def _answer_matching(run_dir):
    """Scripted stand-in for the Claude matching pass."""
    requests = common.read_jsonl(run_dir / "matching_requests.jsonl")
    responses = []
    for req in requests:
        row = req["row"]
        # simple stand-in policy: match top candidate iff it shares a
        # technical token or >=4 common words; else none
        top = req["candidates"][0]
        row_words = set(row["original_company_text"].lower().split())
        rule_words = set((top["title"] + " " + top["check_text"]).lower().split())
        if len(row_words & rule_words) >= 4:
            responses.append({"row_id": req["row_id"], "decision": "match",
                              "rule_id": top["rule_id"],
                              "ambiguous_rule_ids": [],
                              "row_quote": row["stig_objective_or_requirement"]
                              or row["original_company_text"][:30],
                              "rule_quote": top["title"],
                              "basis": "shared requirement wording"})
        else:
            responses.append({"row_id": req["row_id"], "decision": "none",
                              "rule_id": None, "ambiguous_rule_ids": [],
                              "row_quote": "", "rule_quote": "", "basis": "no fit"})
    common.write_jsonl(run_dir / "matching_responses.jsonl", responses)


def _answer_semantic(run_dir):
    path = run_dir / "semantic_requests.jsonl"
    if not path.exists():
        return
    responses = []
    for req in common.read_jsonl(path):
        responses.append({"row_id": req["row_id"], "rule_id": req["rule_id"],
                          "finding_type": "cannot-determine",
                          "verdict": "Cannot Assess",
                          "row_quote": req["row"]["original_company_text"][:20],
                          "rule_quote": req["rule"]["title"][:20],
                          "interpretation": "stand-in: not decidable"})
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)


def test_full_run_clean_docx(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    assert pipeline.main(["start", "--official", str(fx["official_csv"]),
                          "--company", str(fx["company_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_matching(run_dir)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    _answer_semantic(run_dir)
    assert pipeline.main(["finalize", "--run-dir", str(run_dir),
                          "--allow-pending"]) == 0

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    cov = final["coverage"]
    assert cov["ok"] is True
    assert cov["company"]["total"] == 4
    # row 1 (password_reuse_max, observed 9): T1 match, deterministic Compliant
    compliant = [f for f in final["findings"] if f["verdict"] == "Compliant"]
    assert any(f["rule_id"] == "V-1001" and f["confidence"] == "High"
               for f in compliant)
    # row 3 (vague, no evidence): must be Cannot Assess, never Compliant
    vague = [f for f in final["findings"]
             if f.get("basis") == "missing-evidence"]
    assert all(f["verdict"] == "Cannot Assess" for f in vague)
    # row 4 (screensaver): unmatched, visible in leftovers
    assert cov["company"]["unmatched"] >= 1
    assert (run_dir / "report.html").exists()
    html_text = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "https://" not in html_text


def test_full_run_identical_content_no_false_positives(tmp_path):
    """Identical-files case: company xlsx mirrors official values exactly ->
    nothing may be Non-Compliant."""
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run2"
    pipeline.main(["start", "--official", str(fx["official_csv"]),
                   "--company", str(fx["company_xlsx"]),
                   "--run-dir", str(run_dir)])
    _answer_matching(run_dir)
    pipeline.main(["resolve", "--run-dir", str(run_dir)])
    _answer_semantic(run_dir)
    pipeline.main(["finalize", "--run-dir", str(run_dir), "--allow-pending"])
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    row1 = [f for f in final["findings"] if f["rule_id"] == "V-1001"]
    assert all(f["verdict"] != "Non-Compliant" for f in row1)
