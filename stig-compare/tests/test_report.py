import json

import report


def _finding():
    return {
        "finding_id": "F-1", "record_id": "CR-1", "row_id": "R-1",
        "official_row_id": "OR-1", "display_id": "V-1001",
        "verdict": "Deviating", "first_pass_verdict": "Compliant",
        "verdict_source": "validation-revised",
        "change_analysis": ["weakened"],
        "match_rationale": "same control subject",
        "semantic_differences": "company version is less strict",
        "reasoning": "the approved setting is lower",
        "field_alignment": [
            {"company_ref": "APPROVED SETTING", "official_column":
             "Expected Value", "company_quote": "5",
             "official_quote": "9 or more", "relation": "differs"}],
        "row_quote": "<b>reuse</b> must be restricted",
        "official_quote": "Password reuse must be restricted",
        "confidence": "Medium", "human_review": False,
        "human_review_needed": True,
        "review_reasons": ["validation-revised"],
        "claim_reading": "deviation", "claim_consistency": "contradicted",
        "record_notes": "", "sweep_originated": True,
        "comparison_split": False,
        "validation": {"outcome": "revised",
                       "independent_verdict": "Deviating",
                       "revised_verdict": "Deviating",
                       "reason": "evidence shows a weaker setting",
                       "evidence_quote": "5"},
        "disputed": False,
        "match_basis": {"basis": "same parameter", "row_quote": "x",
                        "official_quote": "y"},
        "company_row": {
            "record_id": "CR-1", "row_id": "R-1",
            "header_row": ["REQ", "APPROVED SETTING"],
            "cells": ["<b>reuse</b> must be restricted", "5"],
            "continuation_cells": [{"row_index": 2,
                                    "cells": ["continued cell text"]}],
            "merged": False, "preceding_narrative": "JB.1.1 NARRATIVE",
            "context_grouping": "JB.1.1 NARRATIVE",
            "canonical_fields": {"stig_description": "x"},
            "field_provenance": {}, "interpretation_note": "reviewer note",
            "company_claim_reading": "deviation",
            "original_company_text": "<b>reuse</b> must be restricted | 5",
            "status": "ok", "notes": "",
            "source_reference": {"table_index": 3, "row_index": 1,
                                 "sub_index": 0}},
        "official_row": {
            "official_row_id": "OR-1", "display_id": "V-1001",
            "headers": ["Rule ID", "Title"],
            "cells": ["V-1001", "Password reuse must be restricted"],
            "raw_record": {"Rule ID": "V-1001",
                           "Title": "Password reuse must be restricted"},
            "sheet_or_section": "csv", "row_number": 2,
            "provenance": {"source_file": "official.csv",
                           "locator": "csv,row=2"},
            "column_roles": {"Rule ID": "id", "Title": "title"}},
    }


def _final():
    return {
        "manifest": {"official_file": "official.csv",
                     "company_file": "company.docx",
                     "official_sha256": "a" * 64,
                     "company_sha256": "b" * 64,
                     "started": "2026-08-12T00:00:00",
                     "versions": {"skill_version": "0.3.0",
                                  "prompt_hashes": {"comparison.md": "c" * 64}}},
        "findings": [_finding()],
        "rule_rollups": [
            {"rollup_id": "RU-1", "official_row_id": "OR-1",
             "display_id": "V-1001",
             "contributing_record_ids": ["CR-1", "CR-2"],
             "verdict": "Compliant",
             "coverage_of_requirement": "fully-covered",
             "reasoning": "jointly satisfied", "confidence": "High",
             "human_review": False,
             "validation": {"status": "validation-not-run"},
             "human_review_needed": True,
             "review_reasons": ["validation-not-run"], "oversized": False}],
        "match_state": [],
        "coverage": {
            "company": {"total": 4, "matched": 1, "ambiguous": 1,
                        "unmatched": 1, "unresolved": 1,
                        "ignored_irrelevant_table": 0, "separator": 0,
                        "extraction_failed": 0},
            "official": {"total": 2, "addressed": 1, "unaddressed": 1,
                         "multi_matched_row_ids": ["OR-1"]},
            "warnings": [{"code": "low-coverage-red-banner",
                          "detail": "2/4 rows not compared"}],
            "ok": True},
        "warnings": [{"code": "rollup-verdict-differs", "detail": "OR-1"}],
        "unmatched_rows": [
            {"record_id": "CR-3", "original_company_text": "plain row",
             "source_reference": {}, "basis": "no-nominations",
             "warnings": []}],
        "ambiguous": [
            {"record_id": "CR-4", "original_company_text": "ambiguous row",
             "source_reference": {},
             "ambiguous_official_row_ids": ["OR-1", "OR-2"],
             "basis": "cannot discriminate"}],
        "unresolved_rows": [
            {"record_id": "CR-5", "status": "match-pass-not-run",
             "notes": "", "source_reference": {},
             "original_company_text": "unresolved row"}],
        "unresolved_pairs": [
            {"record_id": "CR-1", "official_row_id": "OR-9",
             "status": "comparison-pass-not-run"}],
        "unaddressed_rules": [
            {"official_row_id": "OR-2", "display_id": "V-1002",
             "headers": ["Rule ID"], "cells": ["V-1002"],
             "raw_record": {"Rule ID": "V-1002", "Title": "Other rule"},
             "sheet_or_section": "csv", "row_number": 3,
             "provenance": {"source_file": "official.csv",
                            "locator": "csv,row=3"},
             "column_roles": None}],
        "table_triage": [
            {"table_index": 3, "sheet_or_section": "document-body",
             "classification": "stig_relevant", "irrelevant_reason": "",
             "context_grouping": "JB.1.1 NARRATIVE", "row_count": 2,
             "column_mapping": {"0": "stig_description"}}],
    }


def _render(tmp_path, final=None):
    (tmp_path / "final.json").write_text(
        json.dumps(final or _final()), encoding="utf-8")
    out = report.render(tmp_path)
    return out.read_text(encoding="utf-8")


def test_self_contained_and_escaped(tmp_path):
    html = _render(tmp_path)
    assert "http://" not in html and "https://" not in html
    assert "<b>reuse</b>" not in html
    assert "&lt;b&gt;reuse&lt;/b&gt;" in html


def test_red_banner_never_in_details(tmp_path):
    html = _render(tmp_path)
    assert "red-banner" in html
    before_banner = html.split("red-banner")[0]
    assert before_banner.count("<details") == before_banner.count("</details>")


def test_finding_full_row_evidence(tmp_path):
    html = _render(tmp_path)
    assert "JB.1.1 NARRATIVE" in html          # narrative context
    assert "continued cell text" in html       # continuation row rendered
    assert "APPROVED SETTING" in html          # company headers
    assert "Password reuse must be restricted" in html
    assert "csv,row=2" in html                 # official provenance
    assert "Field alignment" in html
    assert 'data-verdict="Deviating"' in html


def test_validation_and_revised_badges(tmp_path):
    html = _render(tmp_path)
    assert "REVISED by validation" in html
    assert "first pass: Compliant" in html
    assert "Independent verdict" in html
    assert "weakened" in html                  # change-analysis badge
    assert "Review reasons" in html
    assert "company-declared-deviation" in html
    assert "claim-contradicted" in html
    assert "sweep-originated" in html


def test_rollup_and_leftover_sections(tmp_path):
    html = _render(tmp_path)
    assert "Rule rollups" in html
    assert "RU-1" in html
    assert "validation-not-run" in html
    assert "Unresolved pairs" in html
    assert "comparison-pass-not-run" in html
    assert "CR-3" in html and "CR-4" in html and "CR-5" in html
    assert "V-1002" in html                    # unaddressed keeps identity
    assert "Other rule" in html                # ... and all columns


def test_feedback_widgets_on_findings_and_rollups(tmp_path):
    html = _render(tmp_path)
    assert html.count('class="fb"') == 2       # one finding + one rollup
    assert "Export feedback" in html


def test_dashboard_five_verdict_tiles(tmp_path):
    html = _render(tmp_path)
    for v in ("Compliant", "Deviating", "Incomplete", "Ambiguous",
              "Cannot Assess"):
        assert v in html
    assert "Unresolved" in html
