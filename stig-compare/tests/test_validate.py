import validate

_ROW = {"row_id": "R-aaaa0001",
        "original_company_text": "High | Password reuse must be restricted | 9"}
_RULE = {"rule_id": "V-1001", "title": "Password reuse must be restricted",
         "check_text": "Run SHOW PARAMETER password_reuse_max",
         "fix_text": "Set password_reuse_max to 9 or more."}
_RULES = {"V-1001": _RULE}


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
