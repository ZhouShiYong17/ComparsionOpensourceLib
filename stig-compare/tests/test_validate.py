import canonical
import validate

_ROW = {"row_id": "R-aaaa0001",
        "original_company_text": "High | Password reuse must be restricted | 9"}
_RULE = {"rule_id": "V-1001", "title": "Password reuse must be restricted",
         "check_text": "Run SHOW PARAMETER password_reuse_max",
         "fix_text": "Set password_reuse_max to 9 or more."}
_RULES = {"V-1001": _RULE}

_TABLE = {"table_index": 1, "sheet_or_section": "document-body",
          "preceding_narrative": "JB.1.1 STIG HARDEING- SEVERITY HIGH",
          "header_row": ["STIG REQUIREMENT", "DESCRIPTION"],
          "rows": [
              {"row_index": 1, "cells": ["Password reuse restricted",
                                          "No password reuse"], "merged": False},
              {"row_index": 2, "cells": ["", ""], "merged": False}]}

_GOOD_MAPPING = {"table_index": 1, "classification": "stig_relevant",
                 "irrelevant_reason": "",
                 "column_mapping": {"0": "stig_objective_or_requirement",
                                    "1": "stig_description"},
                 "context_grouping": "JB.1.1 STIG HARDEING- SEVERITY HIGH"}


def _good_match():
    return {"decision": "match", "rule_id": "V-1001", "ambiguous_rule_ids": [],
            "row_quote": "Password reuse must be restricted",
            "rule_quote": "password_reuse_max", "basis": "same requirement"}


def test_quote_exists_whitespace_folded():
    assert validate.quote_exists("reuse  must   be", "reuse must be restricted")
    assert not validate.quote_exists("not present", "reuse must be restricted")


def test_valid_match_passes():
    assert validate.validate_match_output(_good_match(), ["V-1001"], _ROW, _RULES) == []


def test_rule_outside_shortlist_rejected():
    out = _good_match()
    out["rule_id"] = "V-9999"
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "rule-not-in-shortlist" in errs


def test_invented_quote_rejected():
    out = _good_match()
    out["row_quote"] = "text that was never in the row"
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "row-quote-not-found" in errs


def test_ambiguous_needs_two():
    out = {"decision": "ambiguous", "rule_id": None,
           "ambiguous_rule_ids": ["V-1001"], "row_quote": "9",
           "rule_quote": "password_reuse_max", "basis": "unclear"}
    errs = validate.validate_match_output(out, ["V-1001", "V-1002"], _ROW, _RULES)
    assert "ambiguous-needs-two" in errs


def test_semantic_bad_type_and_missing_key():
    out = {"finding_type": "banana", "verdict": "Compliant",
           "row_quote": "9", "rule_quote": "password_reuse_max"}
    errs = validate.validate_semantic_output(out, _ROW, _RULE)
    assert "bad-finding-type" in errs
    assert "missing-key:interpretation" in errs


def test_dedup_and_contradictions():
    f1 = {"finding_id": "F-1", "row_id": "R-1", "rule_id": "V-1",
          "finding_type": "equivalent", "verdict": "Compliant"}
    f2 = dict(f1, finding_id="F-2")                       # duplicate
    f3 = dict(f1, finding_id="F-3", finding_type="stronger",
              verdict="Non-Compliant")                     # contradicts f1
    kept, dropped = validate.dedup_findings([f1, f2, f3])
    assert [f["finding_id"] for f in kept] == ["F-1", "F-3"]
    assert dropped == ["F-2"]
    contras = validate.find_contradictions(kept)
    assert contras == [{"finding_ids": ["F-1", "F-3"],
                        "code": "contradictory-verdicts"}]


def test_empty_row_quote_rejected():
    out = _good_match()
    out["row_quote"] = ""
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "row-quote-not-found" in errs


def test_empty_rule_quote_rejected():
    out = _good_match()
    out["rule_quote"] = ""
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "rule-quote-not-found" in errs


def test_rule_id_in_shortlist_but_missing_from_rules_dict():
    out = _good_match()
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, {})
    assert "rule-quote-not-found" in errs


def test_table_mapping_valid():
    assert validate.validate_table_mapping_output(_GOOD_MAPPING, _TABLE) == []


def test_table_mapping_rejects_bad_enum_and_duplicate_fields():
    bad = dict(_GOOD_MAPPING, classification="maybe")
    assert "bad-classification" in validate.validate_table_mapping_output(bad, _TABLE)
    dup = dict(_GOOD_MAPPING, column_mapping={
        "0": "stig_description", "1": "stig_description"})
    assert "duplicate-field-mapping" in validate.validate_table_mapping_output(dup, _TABLE)


def test_table_mapping_irrelevant_needs_reason_and_no_columns_ok():
    irr = dict(_GOOD_MAPPING, classification="irrelevant",
               irrelevant_reason="instructions", column_mapping={})
    assert validate.validate_table_mapping_output(irr, _TABLE) == []
    irr_bad = dict(irr, irrelevant_reason="")
    assert "bad-irrelevant-reason" in validate.validate_table_mapping_output(irr_bad, _TABLE)


def test_table_mapping_relevant_requires_canonical_column():
    none_mapped = dict(_GOOD_MAPPING, column_mapping={"0": "ignore"})
    assert "no-canonical-columns" in validate.validate_table_mapping_output(
        none_mapped, _TABLE)


def test_table_mapping_context_grouping_must_be_verbatim():
    bad = dict(_GOOD_MAPPING, context_grouping="Improved Section Title")
    assert "context-grouping-not-verbatim" in \
        validate.validate_table_mapping_output(bad, _TABLE)


def _canon_resp(rows):
    return {"chunk_id": "T1-C0", "rows": rows}


def test_canonicalize_valid_and_complete():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0,
             "fields": {"stig_objective_or_requirement":
                        "Password reuse restricted"},
             "field_provenance": {"stig_objective_or_requirement":
                                  {"row_index": 1, "cell_index": 0}},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    assert validate.validate_canonicalize_output(resp, _TABLE, [1, 2]) == []


def test_canonicalize_rejects_missing_row():
    resp = _canon_resp([{"row_index": 1, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("missing-rows") for e in errs)


def test_canonicalize_rejects_paraphrase():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0,
             "fields": {"stig_objective_or_requirement":
                        "Passwords may not be reused"},
             "field_provenance": {"stig_objective_or_requirement":
                                  {"row_index": 1, "cell_index": 0}},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("not-cell-verbatim") for e in errs)


def test_canonicalize_rejects_bad_sub_index_sequence():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 1, "fields": {}, "field_provenance": {},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("bad-sub-index") for e in errs)


def test_canonicalize_interpretation_note_is_free_text():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0, "fields": {}, "field_provenance": {},
             "interpretation_note": "This wording implies a deviation."}]},
        {"row_index": 2, "disposition": "separator"}])
    assert validate.validate_canonicalize_output(resp, _TABLE, [1, 2]) == []
