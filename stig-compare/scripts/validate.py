"""Deterministic validation. Claude output is untrusted input (spec section 5)."""
import common
import canonical

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
        # Check for empty row_quote after folding
        if not common.fold_ws(output["row_quote"]):
            errs.append("row-quote-not-found")
        elif not quote_exists(output["row_quote"], row["original_company_text"]):
            errs.append("row-quote-not-found")
        # Check for empty rule_quote after folding
        if not common.fold_ws(output["rule_quote"]):
            errs.append("rule-quote-not-found")
        elif rid in rules_by_id and not quote_exists(
                output["rule_quote"], _rule_text(rules_by_id[rid])):
            errs.append("rule-quote-not-found")
        elif rid in shortlist_ids and rid not in rules_by_id:
            # Rule ID is in shortlist but not in rules dict - unverifiable
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
    if "row_quote" in output:
        if not common.fold_ws(output["row_quote"]):
            errs.append("row-quote-not-found")
        elif not quote_exists(output["row_quote"], row["original_company_text"]):
            errs.append("row-quote-not-found")
    if "rule_quote" in output:
        if not common.fold_ws(output["rule_quote"]):
            errs.append("rule-quote-not-found")
        elif not quote_exists(output["rule_quote"], _rule_text(rule)):
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


def validate_table_mapping_output(resp, table):
    errs = _require(resp, ["table_index", "classification",
                           "irrelevant_reason", "column_mapping",
                           "context_grouping"])
    if errs:
        return errs
    if resp["table_index"] != table["table_index"]:
        return ["wrong-table-index"]
    cls = resp["classification"]
    if cls not in canonical.TABLE_CLASSIFICATIONS:
        return ["bad-classification"]
    if cls == "irrelevant" and \
            resp["irrelevant_reason"] not in canonical.IRRELEVANT_REASONS:
        errs.append("bad-irrelevant-reason")
    cm = resp["column_mapping"]
    if not isinstance(cm, dict):
        return errs + ["bad-column-mapping"]
    ncols = max(len(table["header_row"]),
                max((len(r["cells"]) for r in table["rows"]), default=0))
    seen_fields = set()
    for k, v in cm.items():
        if not (isinstance(k, str) and k.isdigit() and int(k) < ncols):
            errs.append("bad-column-index")
            break
        if v not in canonical.MAPPING_TARGETS:
            errs.append("bad-mapping-target")
            break
        if v in canonical.CANONICAL_DATA_FIELDS:
            if v in seen_fields:
                errs.append("duplicate-field-mapping")
                break
            seen_fields.add(v)
    if cls in ("stig_relevant", "uncertain") and not errs and not seen_fields:
        errs.append("no-canonical-columns")
    cg = resp["context_grouping"]
    if not isinstance(cg, str):
        errs.append("bad-context-grouping")
    elif common.fold_ws(cg):
        context_src = " ".join(
            [table.get("preceding_narrative", ""),
             table.get("sheet_or_section", "")] +
            [str(h) for h in table.get("header_row", [])])
        if not quote_exists(cg, context_src):
            errs.append("context-grouping-not-verbatim")
    return errs


def _validate_canon_record(rec, row_index, cells_by_index):
    if not isinstance(rec, dict):
        return [f"bad-record:{row_index}"]
    fields = rec.get("fields")
    prov = rec.get("field_provenance")
    note = rec.get("interpretation_note", "")
    if not isinstance(fields, dict) or not isinstance(prov, dict) or \
            not isinstance(note, str):
        return [f"bad-record:{row_index}"]
    for name, value in fields.items():
        if name not in canonical.CANONICAL_DATA_FIELDS:
            return [f"unknown-field:{name}"]
        if not isinstance(value, str):
            return [f"bad-field-type:{name}"]
        if not common.fold_ws(value):
            continue
        p = prov.get(name)
        if not (isinstance(p, dict) and isinstance(p.get("row_index"), int)
                and isinstance(p.get("cell_index"), int)):
            return [f"missing-provenance:{name}"]
        cells = cells_by_index.get(p["row_index"])
        if cells is None or not (0 <= p["cell_index"] < len(cells)):
            return [f"bad-provenance:{name}"]
        if not quote_exists(value, cells[p["cell_index"]]):
            return [f"not-cell-verbatim:{name}"]
    return []


def validate_canonicalize_output(resp, table, chunk_row_indexes):
    errs = _require(resp, ["chunk_id", "rows"])
    if errs:
        return errs
    rows = resp["rows"]
    if not isinstance(rows, list):
        return ["bad-rows"]
    cells_by_index = {r["row_index"]: r["cells"] for r in table["rows"]}
    chunk_set = set(chunk_row_indexes)
    seen = set()
    for entry in rows:
        if not isinstance(entry, dict):
            return ["bad-row-entry"]
        ri = entry.get("row_index")
        if ri not in chunk_set or ri in seen:
            return ["bad-row-index"]
        seen.add(ri)
        disp = entry.get("disposition")
        if disp not in canonical.DISPOSITIONS:
            return ["bad-disposition"]
        if disp == "separator":
            st = entry.get("separator_text", "")
            if not isinstance(st, str):
                return [f"bad-separator:{ri}"]
            if common.fold_ws(st) and not quote_exists(
                    st, canonical.original_text(cells_by_index[ri])):
                return [f"separator-not-verbatim:{ri}"]
        if disp == "record":
            recs = entry.get("records")
            if not isinstance(recs, list) or not recs:
                return [f"missing-records:{ri}"]
            for pos, rec in enumerate(recs):
                if not isinstance(rec, dict) or rec.get("sub_index") != pos:
                    return [f"bad-sub-index:{ri}"]
                rerrs = _validate_canon_record(rec, ri, cells_by_index)
                if rerrs:
                    return rerrs
    if seen != chunk_set:
        return [f"missing-rows:{len(chunk_set - seen)}"]
    return []
