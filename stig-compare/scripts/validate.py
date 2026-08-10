"""Deterministic validation. Claude output is untrusted input (spec section 5)."""
import common

FINDING_TYPES = {"equivalent", "stronger", "weaker", "changed-scope",
                 "contradictory", "cannot-determine"}
VERDICTS = {"Compliant", "Non-Compliant", "Cannot Assess"}
_MATCH_KEYS = ["decision", "rule_id", "ambiguous_rule_ids",
               "row_quote", "rule_quote", "basis"]
_SEM_KEYS = ["finding_type", "verdict", "row_quote", "rule_quote",
             "interpretation"]


def quote_exists(quote, source_text):
    return common.fold_ws(quote) in common.fold_ws(source_text)


def _rule_text(rule):
    return " ".join([rule.get("title", ""), rule.get("check_text", ""),
                     rule.get("fix_text", "")])


def _require(output, keys):
    return [f"missing-key:{k}" for k in keys if k not in output]


def validate_match_output(output, shortlist_ids, row, rules_by_id):
    errs = _require(output, _MATCH_KEYS)
    if errs:
        return errs
    decision = output["decision"]
    if decision not in ("match", "none", "ambiguous"):
        return ["bad-decision"]
    if decision == "match":
        rid = output["rule_id"]
        if rid not in shortlist_ids:
            errs.append("rule-not-in-shortlist")
        if not quote_exists(output["row_quote"], row["original_company_text"]):
            errs.append("row-quote-not-found")
        if rid in rules_by_id and not quote_exists(
                output["rule_quote"], _rule_text(rules_by_id[rid])):
            errs.append("rule-quote-not-found")
    elif decision == "ambiguous":
        ids = output["ambiguous_rule_ids"]
        if len(ids) < 2 or not set(ids) <= set(shortlist_ids):
            errs.append("ambiguous-needs-two")
    return errs


def validate_semantic_output(output, row, rule):
    errs = _require(output, _SEM_KEYS)
    if output.get("finding_type") not in FINDING_TYPES:
        errs.append("bad-finding-type")
    if output.get("verdict") not in VERDICTS:
        errs.append("bad-verdict")
    if "row_quote" in output and not quote_exists(
            output["row_quote"], row["original_company_text"]):
        errs.append("row-quote-not-found")
    if "rule_quote" in output and not quote_exists(
            output["rule_quote"], _rule_text(rule)):
        errs.append("rule-quote-not-found")
    return errs


def dedup_findings(findings):
    seen, kept, dropped = set(), [], []
    for f in findings:
        key = (f["row_id"], f["rule_id"], f["finding_type"])
        if key in seen:
            dropped.append(f["finding_id"])
        else:
            seen.add(key)
            kept.append(f)
    return kept, dropped


def find_contradictions(findings):
    by_pair = {}
    for f in findings:
        by_pair.setdefault((f["row_id"], f["rule_id"]), []).append(f)
    out = []
    for pair, fs in by_pair.items():
        verdicts = {f.get("verdict") for f in fs}
        if len(fs) > 1 and len(verdicts) > 1:
            out.append({"finding_ids": [f["finding_id"] for f in fs],
                        "code": "contradictory-verdicts"})
    return out
