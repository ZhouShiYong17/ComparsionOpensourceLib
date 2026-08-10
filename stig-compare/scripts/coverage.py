"""Coverage accounting: pure arithmetic over item IDs (spec section 7)."""
from collections import Counter

RED_BANNER_THRESHOLD = 0.10


def compute(company_rows, official_rules, match_results, ignored_row_ids):
    by_row = {m["row_id"]: m for m in match_results}
    c = Counter()
    for row in company_rows:
        rid = row["row_id"]
        if row.get("status") == "extraction-failed":
            c["extraction_failed"] += 1
        elif rid in ignored_row_ids:
            c["ignored_by_rule"] += 1
        elif row.get("status") == "needs-structuring" and rid not in by_row:
            c["needs_structuring_unresolved"] += 1
        else:
            m = by_row.get(rid)
            tier = m["tier"] if m else "T4"
            if tier in ("T0", "T1", "T2"):
                c["matched"] += 1
            elif tier == "T3":
                c["ambiguous"] += 1
            else:
                c["unmatched"] += 1

    total = len(company_rows)
    company = {"total": total, "matched": c["matched"],
               "ambiguous": c["ambiguous"], "unmatched": c["unmatched"],
               "ignored_by_rule": c["ignored_by_rule"],
               "extraction_failed": c["extraction_failed"],
               "needs_structuring_unresolved": c["needs_structuring_unresolved"]}

    matched_rules = Counter(m["matched_rule_id"] for m in match_results
                            if m.get("matched_rule_id") and
                            m["tier"] in ("T0", "T1", "T2"))
    official_ids = {r["rule_id"] for r in official_rules}
    addressed = sum(1 for rid in official_ids if matched_rules.get(rid))
    official = {"total": len(official_ids), "addressed": addressed,
                "unaddressed": len(official_ids) - addressed,
                "duplicate_coverage_rule_ids":
                    sorted(rid for rid, n in matched_rules.items() if n > 1)}

    warnings = []
    bucket_sum = sum(v for k, v in company.items() if k != "total")
    ok = bucket_sum == total
    if not ok:
        warnings.append({"code": "coverage-sum-mismatch",
                         "detail": f"buckets={bucket_sum} total={total}"})
    if company["extraction_failed"] > 0:
        warnings.append({"code": "extraction-failures",
                         "detail": str(company["extraction_failed"])})
    bad = (company["extraction_failed"] + company["ignored_by_rule"] +
           company["needs_structuring_unresolved"])
    if total and bad / total > RED_BANNER_THRESHOLD:
        warnings.append({"code": "low-coverage-red-banner",
                         "detail": f"{bad}/{total} rows not compared"})
    return {"company": company, "official": official,
            "warnings": warnings, "ok": ok}
