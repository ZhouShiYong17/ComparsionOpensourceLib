import compare_values as cv


def test_parse_number_and_range():
    assert cv.parse_value("9") == {"kind": "number", "value": 9.0}
    assert cv.parse_value("9 or more") == {"kind": "range", "op": ">=",
                                           "value": 9.0, "unit": None}
    assert cv.parse_value("60 days or less") == {"kind": "range", "op": "<=",
                                                 "value": 60.0, "unit": "days"}
    assert cv.parse_value("at least 14") == {"kind": "range", "op": ">=",
                                             "value": 14.0, "unit": None}
    assert cv.parse_value("15 minutes") == {"kind": "range", "op": "=",
                                            "value": 15.0, "unit": "minutes"}
    assert cv.parse_value("≥ 9")["op"] == ">="


def test_parse_boolean_and_unparseable():
    assert cv.parse_value("Enabled") == {"kind": "boolean", "value": True}
    assert cv.parse_value("off") == {"kind": "boolean", "value": False}
    assert cv.parse_value("logo.png") is None
    assert cv.parse_value("") is None


def test_satisfies():
    nine = cv.parse_value("9")
    assert cv.satisfies(nine, cv.parse_value("9 or more")) is True
    assert cv.satisfies(cv.parse_value("8"), cv.parse_value("9 or more")) is False
    assert cv.satisfies(cv.parse_value("59"), cv.parse_value("60 days or less")) is True
    assert cv.satisfies(cv.parse_value("enabled"), cv.parse_value("enabled")) is True
    # incompatible kinds / units -> None, not a guess
    assert cv.satisfies(cv.parse_value("enabled"), cv.parse_value("9 or more")) is None
    assert cv.satisfies(cv.parse_value("15 minutes"),
                        cv.parse_value("60 days or less")) is None


def test_classify_difference():
    assert cv.classify_difference("abc", "abc") == "identical"
    assert cv.classify_difference("a  b", "a b") == "formatting-only"
    assert cv.classify_difference("`09`", "9") == "normalized-equivalent"
    assert cv.classify_difference("9", "12") == "different"


def _row(observed, approved="9 or more"):
    return {"observed_value_or_evidence": observed,
            "company_approved_setting_or_expected_value": approved}


_RULE = {"expected_value": "9 or more"}


def test_missing_evidence_is_always_cannot_assess():
    v = cv.deterministic_verdict(_row(""), _RULE)
    assert v["verdict"] == "Cannot Assess"
    assert v["basis"] == "missing-evidence"
    assert v["deterministic"] is True


def test_compliant_and_noncompliant():
    assert cv.deterministic_verdict(_row("9"), _RULE)["verdict"] == "Compliant"
    v = cv.deterministic_verdict(_row("8"), _RULE)
    assert v["verdict"] == "Non-Compliant"
    assert v["approved_alignment"] == "aligned"     # approved '9 or more' == expected


def test_unparseable_returns_none_for_semantic_path():
    row = _row("evidence attached as screenshot")
    assert cv.deterministic_verdict(row, _RULE) is None
