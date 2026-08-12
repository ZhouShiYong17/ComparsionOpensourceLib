"""Coverage accounting over skeleton rows. Pure arithmetic.

Every bucket is a count of LLM decisions (table classifications, row
dispositions, match decisions) or pipeline statuses — Python only counts,
it never judges. `bucket_for_records` is the single bucket function; the
finalize leftover sections derive from the same decisions so report and
coverage can never drift.
"""
from collections import Counter

RED_BANNER_THRESHOLD = 0.10
_PROCESSABLE = ("stig_relevant", "uncertain")


def bucket_for_records(records, match_by_record):
    """Bucket one skeleton row from its records' statuses and LLM match
    decisions. Priority: matched > ambiguous > unmatched > unresolved."""
    if not records:
        return "extraction_failed"
    ok_records = [r for r in records if r.get("status") == "ok"]
    if not ok_records:
        return "extraction_failed"
    decisions = [(match_by_record.get(r["record_id"]) or {}).get("decision")
                 for r in ok_records]
    if any(d == "match" for d in decisions):
        return "matched"
    if any(d == "ambiguous" for d in decisions):
        return "ambiguous"
    if all(d == "none" for d in decisions):
        return "unmatched"
    # A decision that is still None (pass never ran) or a two-strike
    # "unresolved-llm-output-rejected" settlement: honest pipeline statuses,
    # never verdicts.
    return "unresolved"


def compute(skeleton_tables, table_state_by_index, company_records,
            official_rows, match_results):
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
            bucket = bucket_for_records(recs_by_row.get((ti, ri), []),
                                        match_by_record)
            row_buckets[(ti, ri)] = bucket
            c[bucket] += 1
    for ti, parent in continuations:
        c[row_buckets.get((ti, parent), "extraction_failed")] += 1

    company = {"total": total, "matched": c["matched"],
               "ambiguous": c["ambiguous"], "unmatched": c["unmatched"],
               "unresolved": c["unresolved"],
               "ignored_irrelevant_table": c["ignored_irrelevant_table"],
               "separator": c["separator"],
               "extraction_failed": c["extraction_failed"]}

    matched_rows = Counter()
    for m in match_results:
        if m.get("decision") == "match":
            for oid in m.get("selected_official_row_ids", []):
                matched_rows[oid] += 1
    official_ids = {r["official_row_id"] for r in official_rows}
    addressed = sum(1 for oid in official_ids if matched_rows.get(oid))
    official = {"total": len(official_ids), "addressed": addressed,
                "unaddressed": len(official_ids) - addressed,
                "multi_matched_row_ids":
                    sorted(oid for oid, n in matched_rows.items()
                           if n > 1 and oid in official_ids)}

    warnings = []
    bucket_sum = sum(v for k, v in company.items() if k != "total")
    ok = bucket_sum == total
    if not ok:
        warnings.append({"code": "coverage-sum-mismatch",
                         "detail": f"buckets={bucket_sum} total={total}"})
    if company["extraction_failed"] > 0:
        warnings.append({"code": "extraction-failures",
                         "detail": str(company["extraction_failed"])})
    bad = company["extraction_failed"] + company["unresolved"]
    if total and bad / total > RED_BANNER_THRESHOLD:
        warnings.append({"code": "low-coverage-red-banner",
                         "detail": f"{bad}/{total} rows not compared"})
    return {"company": company, "official": official,
            "warnings": warnings, "ok": ok}
