"""Deterministic value parsing, comparison, and verdicts (spec sections 4.7, 4.4)."""
import re

import common
import normalize

_TRUE = {"enabled", "true", "yes", "on"}
_FALSE = {"disabled", "false", "no", "off"}
_UNITS = r"(?P<unit>days?|hours?|minutes?|seconds?|characters?)?"
_NUM = r"(?P<num>\d+(?:\.\d+)?)"

_RANGE_PATTERNS = [
    (">=", re.compile(rf"^(?:>=|≥|at least)\s*{_NUM}\s*{_UNITS}$")),
    (">=", re.compile(rf"^{_NUM}\s*{_UNITS}\s*or (?:more|greater|higher)$")),
    ("<=", re.compile(rf"^(?:<=|≤|at most|no (?:greater|more) than)\s*{_NUM}\s*{_UNITS}$")),
    ("<=", re.compile(rf"^{_NUM}\s*{_UNITS}\s*or (?:less|fewer|lower)$")),
    ("=",  re.compile(rf"^{_NUM}\s*{_UNITS}$")),
]


def parse_value(text):
    s = normalize.norm_value(text)
    if not s:
        return None
    if s in _TRUE:
        return {"kind": "boolean", "value": True}
    if s in _FALSE:
        return {"kind": "boolean", "value": False}
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return {"kind": "number", "value": float(s)}
    for op, pat in _RANGE_PATTERNS:
        m = pat.match(s)
        if m:
            unit = m.group("unit")
            if unit:
                # Singularize then pluralize: day/days -> days, minute/minutes -> minutes
                unit = unit.rstrip("s") + "s"
            return {"kind": "range", "op": op, "value": float(m.group("num")),
                    "unit": unit}
    return None


def _obs_number(parsed):
    if parsed["kind"] == "number":
        return parsed["value"], None
    if parsed["kind"] == "range" and parsed["op"] == "=":
        return parsed["value"], parsed["unit"]
    return None, None


def satisfies(observed, expected):
    if observed is None or expected is None:
        return None
    if observed["kind"] == "boolean" and expected["kind"] == "boolean":
        return observed["value"] == expected["value"]
    if expected["kind"] in ("number", "range"):
        val, unit = _obs_number(observed)
        if val is None:
            return None
        e_unit = expected.get("unit")
        if unit and e_unit and unit != e_unit:
            return None                      # unit mismatch -> undecidable
        if expected["kind"] == "number":
            return val == expected["value"]
        op = expected["op"]
        return {"<=": val <= expected["value"],
                ">=": val >= expected["value"],
                "=": val == expected["value"]}[op]
    return None


def classify_difference(raw_a, raw_b):
    if raw_a == raw_b:
        return "identical"
    if common.fold_ws(raw_a) == common.fold_ws(raw_b):
        return "formatting-only"
    if normalize.norm_value(raw_a) == normalize.norm_value(raw_b):
        return "normalized-equivalent"
    return "different"


def _alignment(approved_text, expected_text):
    a, e = parse_value(approved_text), parse_value(expected_text)
    if normalize.norm_value(approved_text) == normalize.norm_value(expected_text):
        return "aligned"
    if a is None or e is None:
        return "not-comparable"
    sat = satisfies(a, e)
    if sat is None:
        return "not-comparable"
    return "aligned" if sat else "misaligned"


def deterministic_verdict(company_row, official_rule):
    observed_raw = company_row.get("observed_value_or_evidence", "")
    expected_raw = official_rule.get("expected_value", "")
    approved_raw = company_row.get("company_approved_setting_or_expected_value", "")
    alignment = _alignment(approved_raw, expected_raw)

    if not common.fold_ws(observed_raw):
        return {"verdict": "Cannot Assess", "basis": "missing-evidence",
                "deterministic": True, "approved_alignment": alignment,
                "observation": {"observed": observed_raw,
                                "expected": expected_raw}}

    sat = satisfies(parse_value(observed_raw), parse_value(expected_raw))
    if sat is None:
        return None                          # semantic path decides
    return {"verdict": "Compliant" if sat else "Non-Compliant",
            "basis": "value-comparison", "deterministic": True,
            "approved_alignment": alignment,
            "observation": {"observed": observed_raw, "expected": expected_raw,
                            "relation": "satisfies" if sat else "violates"}}
