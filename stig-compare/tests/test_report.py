import json
import re
from pathlib import Path

import report


def _final(tmp_path):
    final = {
        "manifest": {"official_file": "o.csv", "company_file": "c.docx",
                     "official_sha256": "a" * 64, "company_sha256": "b" * 64,
                     "started": "2026-08-10T12:00:00",
                     "versions": {"skill_version": "0.1.0", "prompt_hashes": {}},
                     "registry_version": 1, "rule_conflicts": []},
        "findings": [{
            "finding_id": "F-11112222", "row_id": "R-aaaa0001",
            "rule_id": "V-1001", "verdict": "Compliant",
            "finding_type": None, "deterministic": True,
            "confidence": "High", "human_review_needed": False,
            "basis": "value-comparison",
            "observation": {"observed": "9", "expected": "9 or more"},
            "interpretation": None, "skeptic": None, "applied_rules": [],
            "match": {"tier": "T1", "candidates": [
                {"rule_id": "V-1001", "score": 3.2}]},
            "company_row": {"original_company_text":
                            "High | <b>reuse</b> | 9",
                            "source_reference": {"table_index": 1,
                                                 "row_index": 1}},
            "official_rule": {"rule_id": "V-1001", "title": "Password reuse",
                              "check_text": "check", "expected_value": "9 or more"}},
            {
            "finding_id": "F-33334444", "row_id": "R-bbbb0002",
            "rule_id": "V-1002", "verdict": "Non-Compliant",
            "finding_type": "weaker", "deterministic": False,
            "confidence": "Medium", "human_review_needed": True,
            "basis": "semantic-comparison",
            "observation": {"row_quote": "60 days",
                            "rule_quote": "no greater than 60 days"},
            "interpretation": "Company policy uses a coarser boundary than "
                              "the official rule requires.",
            "skeptic": None, "applied_rules": [],
            "match": {"tier": "T2", "candidates": []},
            "company_row": {"original_company_text":
                            "Medium | rotate passwords | 60 days",
                            "source_reference": {"table_index": 1,
                                                 "row_index": 2}},
            "official_rule": {"rule_id": "V-1002", "title": "Max password age",
                              "check_text": "check", "expected_value":
                              "60 days or less"}}],
        "match_state": [], "ambiguous": [],
        "coverage": {"company": {"total": 1, "matched": 1, "ambiguous": 0,
                                 "unmatched": 0, "ignored_by_rule": 0,
                                 "extraction_failed": 0,
                                 "needs_structuring_unresolved": 0},
                     "official": {"total": 5, "addressed": 1, "unaddressed": 4,
                                  "duplicate_coverage_rule_ids": []},
                     "warnings": [{"code": "low-coverage-red-banner",
                                   "detail": "2/10 rows not compared"}],
                     "ok": True},
        "warnings": [], "unmatched_rows": [], "unaddressed_rules": []}
    (tmp_path / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return tmp_path


def test_render_self_contained(tmp_path):
    out = report.render(_final(tmp_path))
    html_text = Path(out).read_text(encoding="utf-8")
    assert "https://" not in html_text and "http://" not in html_text
    assert "F-11112222" in html_text
    assert "CONTAINS SENSITIVE DOCUMENT CONTENT" in html_text


def test_document_text_is_escaped(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert "<b>reuse</b>" not in html_text          # raw tag must not survive
    assert "&lt;b&gt;reuse&lt;/b&gt;" in html_text


def test_red_banner_never_in_details(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert "red-banner" in html_text
    warnings_section = re.search(
        r"<section id=\"warnings\">.*?</section>", html_text, re.S).group(0)
    assert "<details" not in warnings_section


def test_feedback_widgets_present(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert 'class="fb"' in html_text
    assert "wrong match" in html_text
    assert "Export feedback" in html_text
    assert "data-fid=\"F-11112222\"" in html_text


def test_semantic_finding_shows_finding_type_and_interpretation(tmp_path):
    # Important finding 2: the report must surface both finding_type (so the
    # "wrong classification" feedback option is meaningful) and the
    # interpretation ("reason") for a semantic finding.
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert "weaker" in html_text
    assert "Interpretation" in html_text
    assert ("Company policy uses a coarser boundary than the official rule "
           "requires.") in html_text

    # And a deterministic finding with finding_type/interpretation both None
    # must render neither block -- no stray "None" text or empty label.
    art = re.search(
        r'<article class="finding" data-fid="F-11112222".*?</article>',
        html_text, re.S).group(0)
    assert "Interpretation" not in art


def _minimal_final(tmp_path):
    """Minimal final.json structure for triage/claim badge tests."""
    final = {
        "manifest": {"official_file": "o.csv", "company_file": "c.docx",
                     "official_sha256": "a" * 64, "company_sha256": "b" * 64,
                     "started": "2026-08-10T12:00:00",
                     "versions": {"skill_version": "0.1.0", "prompt_hashes": {}},
                     "registry_version": 1, "rule_conflicts": []},
        "findings": [{
            "finding_id": "F-11112222", "row_id": "R-aaaa0001",
            "record_id": "CR-1",
            "rule_id": "V-1001", "verdict": "Compliant",
            "finding_type": None, "deterministic": True,
            "confidence": "High", "human_review_needed": False,
            "basis": "value-comparison",
            "observation": {"observed": "9", "expected": "9 or more"},
            "interpretation": None, "skeptic": None, "applied_rules": [],
            "match": {"tier": "T1", "candidates": [
                {"rule_id": "V-1001", "score": 3.2}]},
            "company_row": {"original_company_text":
                            "High | <b>reuse</b> | 9",
                            "source_reference": {"table_index": 1,
                                                 "row_index": 1}},
            "official_rule": {"rule_id": "V-1001", "title": "Password reuse",
                              "check_text": "check", "expected_value": "9 or more"},
            "claim_flags": ["company-declared-deviation", "claim-contradicted"],
            "claim_normalized": "deviation",
            "company_compliance_claim": "DEVIATION",
            "interpretation_note": "reviewer note",
            "sweep_originated": True}],
        "table_triage": [
            {"table_index": 1, "sheet_or_section": "document-body",
             "classification": "irrelevant", "irrelevant_reason": "instructions",
             "context_grouping": "", "row_count": 3, "column_mapping": {}},
            {"table_index": 2, "sheet_or_section": "document-body",
             "classification": "stig_relevant", "irrelevant_reason": "",
             "context_grouping": "JB.1.1", "row_count": 5,
             "column_mapping": {"0": "stig_description"}}],
        "match_state": [],
        "ambiguous": [{
            "record_id": "CR-amb1",
            "original_company_text": "ambiguous text",
            "source_reference": {"table_index": 1, "row_index": 3},
            "ambiguous_rule_ids": ["V-2001", "V-2002"],
            "candidates": []}],
        "unmatched_rows": [{
            "record_id": "CR-unm1",
            "original_company_text": "unmatched text",
            "source_reference": {"table_index": 1, "row_index": 4},
            "warnings": []}],
        "unresolved_rows": [{
            "record_id": "CR-unr1",
            "original_company_text": "unresolved text",
            "source_reference": {"table_index": 1, "row_index": 5},
            "status": "needs-structuring-unresolved",
            "notes": "needs structuring"}],
        "coverage": {"company": {"total": 1, "matched": 1, "ambiguous": 0,
                                 "unmatched": 0, "ignored_by_rule": 0,
                                 "extraction_failed": 0,
                                 "needs_structuring_unresolved": 0},
                     "official": {"total": 5, "addressed": 1, "unaddressed": 4,
                                  "duplicate_coverage_rule_ids": []},
                     "warnings": [], "ok": True},
        "warnings": [], "unaddressed_rules": []}
    (tmp_path / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return tmp_path


def test_report_renders_triage_and_claim_badges(tmp_path):
    run_dir = _minimal_final(tmp_path)
    report.render(run_dir)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Table triage" in html
    assert "irrelevant" in html and "instructions" in html
    assert "company-declared-deviation" in html
    assert "claim-contradicted" in html
    assert "Interpretation (not evidence)" in html
    assert "sweep-originated" in html
    # Verify record_id appears in leftover sections
    assert "CR-amb1" in html
    assert "CR-unm1" in html
    assert "CR-unr1" in html
