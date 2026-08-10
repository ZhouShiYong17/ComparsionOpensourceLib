"""Coverage accounting over skeleton rows (spec section 6). Pure arithmetic."""
from collections import Counter

RED_BANNER_THRESHOLD = 0.10
_MATCHED_TIERS = ("T0", "T1", "T2")
_PROCESSABLE = ("stig_relevant", "uncertain")


def _bucket_for_records(records, match_by_record, ignored_row_ids):
    if not records:
        return "extraction_failed"
    if any(r["record_id"] in ignored_row_ids or
           r.get("row_id") in ignored_row_ids for r in records):
        return "ignored_by_rule"
    ok_records = [r for r in records if r.get("status") == "ok"]
    if not ok_records:
        return "extraction_failed"
    tiers = []
    for r in ok_records:
        m = match_by_record.get(r["record_id"])
        if m and m.get("tier") in _MATCHED_TIERS and m.get("matched_rule_ids"):
            return "matched"
        tiers.append(m.get("tier") if m else None)
    if any(t == "T3" for t in tiers):
        return "ambiguous"
    return "unmatched"


def compute(skeleton_tables, table_state_by_index, company_records,
            official_rules, match_results, ignored_row_ids):
    match_by_record = {m["record_id"]: m for m in match_results}
    recs_by_row = {}
    for rec in company_records:
        sr = rec["source_reference"]
        recs_by_row.setdefault(
            (sr["table_index"], sr["row_index"]), []).append(rec)

    c = Counter()
    row_buckets = {}
    continuations = []
    total = 0
    for table in skeleton_tables:
        ti = table["table_index"]
        ts = table_state_by_index.get(ti, {})
        cls = ts.get("classification")
        disps = {int(k): v
                 for k, v in (ts.get("row_dispositions") or {}).items()}
        parents = {int(k): v for k, v in (ts.get("parent_of") or {}).items()}
        for row in table["rows"]:
            total += 1
            ri = row["row_index"]
            if cls == "irrelevant":
                c["ignored_irrelevant_table"] += 1
                continue
            if cls not in _PROCESSABLE:
                c["extraction_failed"] += 1
                continue
            disp = disps.get(ri)
            if disp == "separator":
                c["separator"] += 1
                continue
            if disp == "continuation":
                continuations.append((ti, parents.get(ri)))
                continue
            bucket = _bucket_for_records(recs_by_row.get((ti, ri), []),
                                         match_by_record, ignored_row_ids)
            row_buckets[(ti, ri)] = bucket
            c[bucket] += 1
    for ti, parent in continuations:
        c[row_buckets.get((ti, parent), "extraction_failed")] += 1

    company = {"total": total, "matched": c["matched"],
               "ambiguous": c["ambiguous"], "unmatched": c["unmatched"],
               "ignored_irrelevant_table": c["ignored_irrelevant_table"],
               "ignored_by_rule": c["ignored_by_rule"],
               "separator": c["separator"],
               "extraction_failed": c["extraction_failed"]}

    matched_rules = Counter()
    for m in match_results:
        if m.get("tier") in _MATCHED_TIERS:
            for rid in m.get("matched_rule_ids", []):
                matched_rules[rid] += 1
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
    bad = company["extraction_failed"] + company["ignored_by_rule"]
    if total and bad / total > RED_BANNER_THRESHOLD:
        warnings.append({"code": "low-coverage-red-banner",
                         "detail": f"{bad}/{total} rows not compared"})
    return {"company": company, "official": official,
            "warnings": warnings, "ok": ok}
