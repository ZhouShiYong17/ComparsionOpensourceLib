import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all, _write_docx, _HEADERS
import common
import compare_values
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


def test_semantic_retry_not_swept_by_allow_pending(tmp_path):
    """A semantic response that fails validation on strike 1 must get its
    documented retry chance via `finalize` (no --allow-pending) refusing
    with exit 4 -- it must NOT be immediately swept into a permanent,
    falsely-labeled "semantic-pass-not-run" finding just because
    --allow-pending happens to be set on that call. This guards the
    SKILL.md-documented compare-mode flow (step 5's retry loop must run
    to completion, without --allow-pending, before any pending semantic
    pair may legitimately be treated as unanswerable)."""
    fx = build_all(tmp_path / "fx")

    # One company row that MATCHES V-1003 (audit logging) lexically, but
    # whose observed value is unparseable, so the deterministic value
    # comparison can't decide it and it must hand off to the semantic pass.
    row = ["High", "Audit logging must be enabled",
           "Database audit logging requirement",
           "Review audit configuration", "enabled",
           "see attached screenshot evidence"]
    company_path = tmp_path / "fx" / "company_semantic.docx"
    _write_docx(company_path, _HEADERS, [row])

    # Sanity check: this pairing really is semantic-only (deterministic
    # value comparison must return None), matching the row's real shape
    # after extraction (context_grouping/description/objective/command/
    # approved/observed, in the order _HEADERS maps them).
    official = json.loads(fx["official_json"].read_text(encoding="utf-8"))
    v1003 = next(r for r in official if r["rule_id"] == "V-1003")
    company_row = {
        "context_grouping": row[0],
        "stig_objective_or_requirement": row[1],
        "stig_description": row[2],
        "stig_command_or_value": row[3],
        "company_approved_setting_or_expected_value": row[4],
        "observed_value_or_evidence": row[5],
    }
    assert compare_values.deterministic_verdict(company_row, v1003) is None

    run_dir = tmp_path / "run3"
    assert pipeline.main(["start", "--official", str(fx["official_csv"]),
                          "--company", str(company_path),
                          "--run-dir", str(run_dir)]) == 0

    reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert len(reqs) == 1
    row_id = reqs[0]["row_id"]
    common.write_jsonl(run_dir / "matching_responses.jsonl", [{
        "row_id": row_id, "decision": "match", "rule_id": "V-1003",
        "ambiguous_rule_ids": [],
        "row_quote": "Audit logging must be enabled",
        "rule_quote": "Audit logging must be enabled",
        "basis": "direct requirement match"}])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    sem_reqs = common.read_jsonl(run_dir / "semantic_requests.jsonl")
    assert len(sem_reqs) == 1
    sreq = sem_reqs[0]
    assert sreq["row_id"] == row_id and sreq["rule_id"] == "V-1003"

    # Strike 1: an invalid semantic response (empty quotes -> rejected by
    # validate.validate_semantic_output).
    responses = [{"row_id": sreq["row_id"], "rule_id": sreq["rule_id"],
                 "finding_type": "cannot-determine", "verdict": "Cannot Assess",
                 "row_quote": "", "rule_quote": "", "interpretation": "n/a"}]
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)

    # finalize WITHOUT --allow-pending must refuse (exit 4), not sweep the
    # still-retriable pair into a finding.
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 4

    final_path = run_dir / "final.json"
    assert not final_path.exists()

    # The retry must have been queued, not discarded, and the strike-1
    # rejection must be on the audit trail.
    sem_reqs2 = common.read_jsonl(run_dir / "semantic_requests.jsonl")
    retry_reqs = [r for r in sem_reqs2 if r.get("retry")]
    assert len(retry_reqs) == 1
    assert retry_reqs[0]["row_id"] == row_id and retry_reqs[0]["rule_id"] == "V-1003"

    vfails = common.read_jsonl(run_dir / "validation_failures.jsonl")
    assert any(v["kind"] == "semantic" and v["row_id"] == row_id
               for v in vfails)

    # Strike 2 (the retry): a valid semantic response this time.
    responses.append({"row_id": sreq["row_id"], "rule_id": sreq["rule_id"],
                      "finding_type": "weaker", "verdict": "Cannot Assess",
                      "row_quote": "see attached screenshot evidence",
                      "rule_quote": "Audit logging must be enabled",
                      "interpretation": "evidence references an external "
                                        "artifact, not a verifiable value"})
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)

    # No pending work remains once the retry is answered -- --allow-pending
    # is not needed here.
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir)])
    assert rc == 0

    final = json.loads(final_path.read_text(encoding="utf-8"))
    findings = [f for f in final["findings"] if f["rule_id"] == "V-1003"]
    assert len(findings) == 1
    f = findings[0]
    assert f["finding_type"] == "weaker"
    assert f["verdict"] == "Cannot Assess"
    assert f["basis"] == "semantic-comparison"
    assert f["basis"] != "semantic-pass-not-run"
