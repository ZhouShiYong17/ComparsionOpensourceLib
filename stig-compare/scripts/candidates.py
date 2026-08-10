"""Lexical candidate generation and deterministic match tiers T0/T1.

Explainable features only; severity can only break ties (spec section 4.5-4.6).
"""
import math
import re

import normalize

_ID = re.compile(r"\b(SV|V)-\d+\b", re.IGNORECASE)
_TECH = re.compile(
    r"[A-Za-z0-9_.\\/-]*(?:_[A-Za-z0-9]+|\.[A-Za-z]+\.[A-Za-z.]+|\\[A-Za-z])"
    r"[A-Za-z0-9_.\\/-]*")
_WORD = re.compile(r"[a-z0-9_]+")

_WEIGHTS = {"technical": 3.0, "token_overlap": 1.0,
            "value_overlap": 0.3, "severity_tiebreak": 0.05}

_ROW_TEXT_FIELDS = ["stig_description", "stig_objective_or_requirement",
                    "stig_command_or_value"]


def technical_tokens(text):
    out = set()
    for m in _TECH.finditer(text or ""):
        tok = m.group(0).strip(".-/\\").lower()
        if len(tok) >= 4 and ("_" in tok or "." in tok or "\\" in tok or "/" in tok):
            out.add(tok)
    for m in re.finditer(r"\b[A-Z][A-Z0-9_]{3,}\b", text or ""):
        out.add(m.group(0).lower())
    return out


def _words(text):
    return set(_WORD.findall(normalize.norm_text(text)))


def build_idf(official_rules):
    docs = [_words(" ".join([r["title"], r["check_text"], r["fix_text"]]))
            for r in official_rules]
    n = max(len(docs), 1)
    idf = {}
    for d in docs:
        for w in d:
            idf[w] = idf.get(w, 0) + 1
    return {w: math.log(n / df) for w, df in idf.items()}


def _rule_text(rule):
    return " ".join([rule["title"], rule["check_text"], rule["fix_text"]])


def score_row(company_row, official_rule, idf):
    row_text = " ".join(company_row.get(f, "") for f in _ROW_TEXT_FIELDS) or \
               company_row["original_company_text"]
    rule_text = _rule_text(official_rule)

    row_words, rule_words = _words(row_text), _words(rule_text)
    shared = row_words & rule_words
    denom = sum(idf.get(w, 0.0) for w in row_words) or 1.0
    token_overlap = sum(idf.get(w, 0.0) for w in shared) / denom

    row_tech = technical_tokens(company_row["original_company_text"])
    rule_tech = technical_tokens(rule_text)
    technical = 1.0 if row_tech & rule_tech else 0.0

    approved = normalize.norm_value(
        company_row.get("company_approved_setting_or_expected_value", ""))
    expected = normalize.norm_value(official_rule.get("expected_value", ""))
    value_overlap = 1.0 if approved and expected and \
        (approved == expected or approved in expected or expected in approved) \
        else 0.0

    sev = normalize.norm_text(company_row.get("context_grouping", ""))
    severity_tiebreak = 1.0 if sev and sev == official_rule.get("severity") else 0.0

    features = {"token_overlap": round(token_overlap, 4),
                "technical": technical, "value_overlap": value_overlap,
                "severity_tiebreak": severity_tiebreak}
    score = sum(_WEIGHTS[k] * v for k, v in features.items())
    return {"score": round(score, 4), "features": features}


def generate(company_rows, official_rules, k=5, floor=0.05, margin=0.15):
    idf = build_idf(official_rules)
    by_id = {r["rule_id"]: r for r in official_rules}
    rule_tech = {r["rule_id"]: technical_tokens(_rule_text(r))
                 for r in official_rules}
    results = []
    for row in company_rows:
        if row.get("status") not in ("ok", "needs-structuring"):
            continue
        scored = sorted(
            ({"rule_id": r["rule_id"], **score_row(row, r, idf)}
             for r in official_rules),
            key=lambda c: c["score"], reverse=True)
        # severity alone must never clear the floor: drop candidates whose
        # score comes only from the severity feature. similarly, token_overlap
        # alone (no technical/value/severity match) doesn't make a plausible candidate.
        shortlist = [c for c in scored
                     if c["score"] >= floor and
                     c["score"] > _WEIGHTS["severity_tiebreak"] *
                     c["features"]["severity_tiebreak"] + 1e-9 and
                     c["score"] > _WEIGHTS["token_overlap"] *
                     c["features"]["token_overlap"] + 1e-9][:k]

        result = {"row_id": row["row_id"], "tier": None,
                  "matched_rule_id": None, "margin_flag": False,
                  "candidates": shortlist}

        m = _ID.search(row["original_company_text"] or "")
        if m and m.group(0).upper() in by_id:
            result["tier"] = "T0"
            result["matched_rule_id"] = m.group(0).upper()
        else:
            row_tech = technical_tokens(row["original_company_text"])
            if row_tech:
                hits = [rid for rid, toks in rule_tech.items() if row_tech & toks]
                if len(hits) == 1:
                    result["tier"] = "T1"
                    result["matched_rule_id"] = hits[0]

        if result["tier"] is None and len(shortlist) >= 2 and shortlist[0]["score"] > 0:
            rel = (shortlist[0]["score"] - shortlist[1]["score"]) / shortlist[0]["score"]
            result["margin_flag"] = rel < margin
        results.append(result)
    return results
