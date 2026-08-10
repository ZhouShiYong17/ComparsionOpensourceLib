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
