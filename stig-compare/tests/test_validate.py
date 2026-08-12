import validate


_RECORD = {"cells": ["Password reuse must be restricted", "9 or more"],
           "continuation_cells": [{"row_index": 2,
                                   "cells": ["continued evidence text"]}],
           "original_company_text":
               "Password reuse must be restricted | 9 or more"}

_ROW = {"official_row_id": "OR-1",
        "headers": ["Rule ID", "Title"],
        "cells": ["V-1001", "Password reuse must be restricted"],
        "raw_record": {"Rule ID": "V-1001",
                       "Title": "Password reuse must be restricted"}}

_ROWS_BY_ID = {"OR-1": _ROW}


# ---- quote sources --------------------------------------------------------

def test_company_quote_source_includes_continuation_cells():
    src = validate.company_quote_source(_RECORD)
    assert validate.quote_exists("continued evidence text", src)
    assert validate.quote_exists("9 or more", src)


def test_official_quote_source_spans_all_columns():
    src = validate.official_quote_source(_ROW)
    assert validate.quote_exists("V-1001", src)
    assert validate.quote_exists("Password reuse", src)


# ---- echo flags -----------------------------------------------------------

def test_echo_flags():
    assert validate.check_echo_flags({}, require_retry=False) == []
    assert validate.check_echo_flags({"retry": True}, require_retry=True) == []
    assert "retry-echo-mismatch" in \
        validate.check_echo_flags({}, require_retry=True)
    assert "retry-echo-mismatch" in \
        validate.check_echo_flags({"retry": True}, require_retry=False)
    assert "sweep-round-echo-mismatch" in validate.check_echo_flags(
        {}, require_retry=False, require_sweep_round=True)
    assert validate.check_echo_flags(
        {"sweep_round": True}, require_sweep_round=True) == []


# ---- official structure ---------------------------------------------------

def _structure_req():
    return {"structure_id": "OS-0", "headers": ["Rule ID", "Title"]}


def _structure_resp(**kw):
    resp = {"structure_id": "OS-0", "display_id_column": "Rule ID",
            "column_roles": {"Rule ID": "id", "Title": "title"},
            "notes": ""}
    resp.update(kw)
    return resp


def test_structure_valid():
    assert validate.validate_official_structure_output(
        _structure_resp(), _structure_req()) == []


def test_structure_rejects_unknown_column_and_partial_roles():
    assert "bad-display-id-column" in \
        validate.validate_official_structure_output(
            _structure_resp(display_id_column="Nope"), _structure_req())
    assert "column-roles-headers-mismatch" in \
        validate.validate_official_structure_output(
            _structure_resp(column_roles={"Rule ID": "id"}), _structure_req())
    assert "bad-column-role" in \
        validate.validate_official_structure_output(
            _structure_resp(column_roles={"Rule ID": "score",
                                          "Title": "title"}),
            _structure_req())


def test_structure_null_display_id_ok():
    assert validate.validate_official_structure_output(
        _structure_resp(display_id_column=None), _structure_req()) == []


# ---- table mapping --------------------------------------------------------

_TABLE = {"table_index": 1, "sheet_or_section": "document-body",
          "preceding_narrative": "JB.1.1 SECTION",
          "header_row": ["A", "B"],
          "rows": [{"row_index": 1, "cells": ["x", "y"]}]}


def _mapping_resp(**kw):
    resp = {"table_index": 1, "classification": "stig_relevant",
            "irrelevant_reason": "other",
            "column_mapping": {"0": "stig_description", "1": "other"},
            "context_grouping": "JB.1.1 SECTION"}
    resp.update(kw)
    return resp


def test_mapping_valid_and_other_target():
    assert validate.validate_table_mapping_output(_mapping_resp(), _TABLE) == []


def test_mapping_rejects_retired_targets():
    for target in ("extra_field", "ignore"):
        errs = validate.validate_table_mapping_output(
            _mapping_resp(column_mapping={"0": target}), _TABLE)
        assert "bad-mapping-target" in errs


def test_mapping_no_canonical_columns_is_legal_now():
    errs = validate.validate_table_mapping_output(
        _mapping_resp(column_mapping={"0": "other", "1": "other"}), _TABLE)
    assert errs == []


def test_mapping_context_grouping_must_be_verbatim():
    errs = validate.validate_table_mapping_output(
        _mapping_resp(context_grouping="Composed Title"), _TABLE)
    assert "context-grouping-not-verbatim" in errs


def test_mapping_duplicate_field():
    errs = validate.validate_table_mapping_output(
        _mapping_resp(column_mapping={"0": "stig_description",
                                      "1": "stig_description"}), _TABLE)
    assert "duplicate-field-mapping" in errs


# ---- interpretation -------------------------------------------------------

_ITABLE = {"table_index": 1,
           "rows": [{"row_index": 1, "cells": ["req text", "val"]},
                    {"row_index": 2, "cells": ["cont text"]}]}


def _interp_resp(**kw):
    resp = {"chunk_id": "T1-C0", "rows": [
        {"row_index": 1, "disposition": "record",
         "records": [{"sub_index": 0,
                      "fields": {"stig_description": "req text"},
                      "field_provenance": {"stig_description":
                                           {"row_index": 1, "cell_index": 0}},
                      "company_claim_reading": "none",
                      "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "continuation"}]}
    resp.update(kw)
    return resp


def test_interpretation_valid():
    assert validate.validate_interpretation_output(
        _interp_resp(), _ITABLE, [1, 2]) == []


def test_interpretation_every_row_exactly_once():
    resp = _interp_resp()
    resp["rows"] = resp["rows"][:1]
    assert validate.validate_interpretation_output(
        resp, _ITABLE, [1, 2]) == ["missing-rows:1"]


def test_interpretation_rejects_paraphrase():
    resp = _interp_resp()
    resp["rows"][0]["records"][0]["fields"]["stig_description"] = \
        "paraphrased text"
    assert validate.validate_interpretation_output(
        resp, _ITABLE, [1, 2]) == ["not-cell-verbatim:stig_description"]


def test_interpretation_field_may_cite_continuation_cell():
    resp = _interp_resp()
    resp["rows"][0]["records"][0]["fields"]["remarks_or_justification"] = \
        "cont text"
    resp["rows"][0]["records"][0]["field_provenance"][
        "remarks_or_justification"] = {"row_index": 2, "cell_index": 0}
    assert validate.validate_interpretation_output(
        resp, _ITABLE, [1, 2]) == []


def test_interpretation_claim_reading_enum():
    resp = _interp_resp()
    resp["rows"][0]["records"][0]["company_claim_reading"] = "definitely"
    assert validate.validate_interpretation_output(
        resp, _ITABLE, [1, 2]) == ["bad-claim-reading:1"]


# ---- scoping --------------------------------------------------------------

def test_scoping_valid_and_bad_ids():
    resp = {"scoping_id": "SC-B0-K0",
            "nominations": [{"record_id": "CR-1", "official_row_id": "OR-1",
                             "note": ""}]}
    assert validate.validate_scoping_output(resp, {"CR-1"}, {"OR-1"}) == []
    assert validate.validate_scoping_output(resp, {"CR-2"}, {"OR-1"}) == \
        ["bad-nomination"]
    empty = {"scoping_id": "SC-B0-K0", "nominations": []}
    assert validate.validate_scoping_output(empty, set(), set()) == []


# ---- adjudication ---------------------------------------------------------

def _adj_resp(**kw):
    resp = {"record_id": "CR-1", "decision": "match",
            "selections": [{"official_row_id": "OR-1",
                            "row_quote": "Password reuse must be restricted",
                            "official_quote": "V-1001"}],
            "ambiguous_official_row_ids": [], "basis": "b"}
    resp.update(kw)
    return resp


def test_adjudication_valid_match():
    assert validate.validate_adjudication_output(
        _adj_resp(), {"OR-1"}, _RECORD, _ROWS_BY_ID) == []


def test_adjudication_quote_from_continuation_cell_passes():
    # The parked merged-row fast-follow: continuation-row evidence is a
    # legitimate quote source.
    resp = _adj_resp()
    resp["selections"][0]["row_quote"] = "continued evidence text"
    assert validate.validate_adjudication_output(
        resp, {"OR-1"}, _RECORD, _ROWS_BY_ID) == []


def test_adjudication_rejects_unnominated_and_bad_quotes():
    assert "row-not-nominated" in validate.validate_adjudication_output(
        _adj_resp(), set(), _RECORD, _ROWS_BY_ID)
    resp = _adj_resp()
    resp["selections"][0]["row_quote"] = "invented text"
    assert "row-quote-not-found" in validate.validate_adjudication_output(
        resp, {"OR-1"}, _RECORD, _ROWS_BY_ID)
    resp = _adj_resp()
    resp["selections"][0]["official_quote"] = "not in the row"
    assert "official-quote-not-found" in \
        validate.validate_adjudication_output(
            resp, {"OR-1"}, _RECORD, _ROWS_BY_ID)


def test_adjudication_ambiguous_needs_two():
    resp = _adj_resp(decision="ambiguous",
                     ambiguous_official_row_ids=["OR-1"], selections=[])
    assert "ambiguous-needs-two" in validate.validate_adjudication_output(
        resp, {"OR-1"}, _RECORD, _ROWS_BY_ID)


def test_adjudication_sweep_round_echo_enforced():
    errs = validate.validate_adjudication_output(
        _adj_resp(), {"OR-1"}, _RECORD, _ROWS_BY_ID,
        require_sweep_round=True)
    assert "sweep-round-echo-mismatch" in errs
    ok = validate.validate_adjudication_output(
        _adj_resp(sweep_round=True), {"OR-1"}, _RECORD, _ROWS_BY_ID,
        require_sweep_round=True)
    assert ok == []


# ---- comparison -----------------------------------------------------------

def _cmp_entry(**kw):
    entry = {"official_row_id": "OR-1", "match_rationale": "r",
             "field_alignment": [
                 {"company_ref": "A", "official_column": "Title",
                  "company_quote": "9 or more",
                  "official_quote": "Password reuse must be restricted",
                  "relation": "equivalent"}],
             "semantic_differences": "s", "change_analysis": ["weakened"],
             "verdict": "Compliant", "confidence": "High",
             "human_review": False,
             "row_quote": "Password reuse must be restricted",
             "official_quote": "V-1001", "reasoning": "why"}
    entry.update(kw)
    return entry


def _cmp_resp(entries=None, **kw):
    resp = {"comparison_id": "CMP-CR-1", "record_id": "CR-1",
            "per_rule": entries if entries is not None else [_cmp_entry()],
            "claim_consistency": "no-claim", "record_notes": ""}
    resp.update(kw)
    return resp


def test_comparison_valid():
    assert validate.validate_comparison_output(
        _cmp_resp(), _RECORD, _ROWS_BY_ID, ["OR-1"]) == []


def test_comparison_per_rule_completeness():
    assert "per-rule-coverage-mismatch" in validate.validate_comparison_output(
        _cmp_resp(entries=[]), _RECORD, _ROWS_BY_ID, ["OR-1"])
    assert "per-rule-coverage-mismatch" in validate.validate_comparison_output(
        _cmp_resp(entries=[_cmp_entry(), _cmp_entry()]),
        _RECORD, _ROWS_BY_ID, ["OR-1"])


def test_comparison_bad_enums():
    assert "bad-verdict" in validate.validate_comparison_output(
        _cmp_resp(entries=[_cmp_entry(verdict="Non-Compliant")]),
        _RECORD, _ROWS_BY_ID, ["OR-1"])
    assert "bad-change-analysis" in validate.validate_comparison_output(
        _cmp_resp(entries=[_cmp_entry(change_analysis=["made-up"])]),
        _RECORD, _ROWS_BY_ID, ["OR-1"])


def test_comparison_alignment_missing_side_rules():
    ok = _cmp_entry(field_alignment=[
        {"company_ref": "A", "official_column": "Title",
         "company_quote": "", "official_quote": "V-1001",
         "relation": "company-missing"}])
    assert validate.validate_comparison_output(
        _cmp_resp(entries=[ok]), _RECORD, _ROWS_BY_ID, ["OR-1"]) == []
    bad = _cmp_entry(field_alignment=[
        {"company_ref": "A", "official_column": "Title",
         "company_quote": "", "official_quote": "V-1001",
         "relation": "differs"}])
    assert "alignment-company-quote-not-found" in \
        validate.validate_comparison_output(
            _cmp_resp(entries=[bad]), _RECORD, _ROWS_BY_ID, ["OR-1"])


def test_comparison_headline_quotes_never_empty():
    bad = _cmp_entry(row_quote="")
    assert "row-quote-not-found" in validate.validate_comparison_output(
        _cmp_resp(entries=[bad]), _RECORD, _ROWS_BY_ID, ["OR-1"])


# ---- rollup ---------------------------------------------------------------

def _rollup_resp(**kw):
    resp = {"rollup_id": "RU-1", "contributing_record_ids": ["CR-1", "CR-2"],
            "joint_verdict": "Compliant",
            "coverage_of_requirement": "fully-covered",
            "reasoning": "joint", "confidence": "High",
            "human_review": False}
    resp.update(kw)
    return resp


def test_rollup_valid_and_contributor_mismatch():
    assert validate.validate_rollup_output(
        _rollup_resp(), ["CR-2", "CR-1"]) == []
    assert "contributing-records-mismatch" in validate.validate_rollup_output(
        _rollup_resp(contributing_record_ids=["CR-1"]), ["CR-1", "CR-2"])


# ---- validation pass ------------------------------------------------------

_EVIDENCE = "Password reuse must be restricted 9 or more V-1001"


def _val_resp(**kw):
    resp = {"validation_id": "VAL-F-1", "finding_id": "F-1",
            "independent_verdict": "Compliant", "outcome": "upheld",
            "revised_verdict": None, "revised_change_analysis": None,
            "reason": "", "evidence_quote": ""}
    resp.update(kw)
    return resp


def test_validation_upheld_ok():
    assert validate.validate_validation_output(
        _val_resp(), "Compliant", _EVIDENCE) == []


def test_uphold_contradicting_own_verdict_rejected():
    errs = validate.validate_validation_output(
        _val_resp(independent_verdict="Deviating"), "Compliant", _EVIDENCE)
    assert "uphold-contradicts-own-verdict" in errs


def test_revised_requires_verdict_and_only_when_revised():
    errs = validate.validate_validation_output(
        _val_resp(outcome="revised", reason="x"), "Compliant", _EVIDENCE)
    assert "revised-needs-verdict" in errs
    ok = validate.validate_validation_output(
        _val_resp(outcome="revised", revised_verdict="Deviating",
                  independent_verdict="Deviating", reason="x"),
        "Compliant", _EVIDENCE)
    assert ok == []
    errs = validate.validate_validation_output(
        _val_resp(revised_verdict="Deviating"), "Compliant", _EVIDENCE)
    assert "revised-verdict-without-revised" in errs


def test_refuted_needs_reason_and_verbatim_evidence():
    errs = validate.validate_validation_output(
        _val_resp(outcome="refuted", independent_verdict="Deviating"),
        "Compliant", _EVIDENCE)
    assert "reason-required" in errs
    errs = validate.validate_validation_output(
        _val_resp(outcome="refuted", independent_verdict="Deviating",
                  reason="wrong", evidence_quote="invented"),
        "Compliant", _EVIDENCE)
    assert "evidence-quote-not-found" in errs


# ---- dedup ----------------------------------------------------------------

def test_dedup_key_is_record_and_official_row():
    f1 = {"finding_id": "F-1", "record_id": "CR-1", "official_row_id": "OR-1"}
    f2 = {"finding_id": "F-2", "record_id": "CR-1", "official_row_id": "OR-1"}
    f3 = {"finding_id": "F-3", "record_id": "CR-1", "official_row_id": "OR-2"}
    kept, dropped = validate.dedup_findings([f1, f2, f3])
    assert [f["finding_id"] for f in kept] == ["F-1", "F-3"]
    assert dropped == ["F-2"]
