"""Mechanical validation. Claude output is untrusted input.

Nothing in this module judges content: every check is shape, enum
membership, id echo, exactly-once accounting, or verbatim-substring quote
verification. The quote sources deliberately cover the COMPLETE rows —
parent cells plus every continuation-row cell on the company side, every
column value on the official side — so citing any real evidence passes.
"""
import common
import schema

_ADJ_KEYS = ["record_id", "decision", "selections",
             "ambiguous_official_row_ids", "basis"]
_PER_RULE_KEYS = ["official_row_id", "match_rationale", "field_alignment",
                  "semantic_differences", "change_analysis", "verdict",
                  "confidence", "human_review", "row_quote",
                  "official_quote", "reasoning"]
_ALIGN_KEYS = ["company_ref", "official_column", "company_quote",
               "official_quote", "relation"]
_VALIDATION_KEYS = ["validation_id", "finding_id", "independent_verdict",
                    "outcome", "revised_verdict", "revised_change_analysis",
                    "reason", "evidence_quote"]


def quote_exists(quote, source_text):
    return common.fold_ws(quote) in common.fold_ws(source_text)


# ---- quote sources (complete-row evidence) --------------------------------

def company_quote_source(record):
    """Every verbatim cell of the record's row AND its continuation rows."""
    parts = [str(c) for c in record.get("cells", [])]
    for cont in record.get("continuation_cells", []):
        parts.extend(str(c) for c in cont.get("cells", []))
    parts.append(record.get("original_company_text", ""))
    return " ".join(parts)


def official_quote_source(row):
    """Every verbatim cell value of the official row."""
    return " ".join(str(c) for c in row.get("cells", []))


def context_source(table):
    return " ".join(
        [table.get("preceding_narrative", ""),
         table.get("sheet_or_section", "")] +
        [str(h) for h in table.get("header_row", [])])


# ---- shared low-level checks ----------------------------------------------

def _require(output, keys):
    return [f"missing-key:{k}" for k in keys if k not in output]


def check_echo_flags(resp, require_retry=False, require_sweep_round=None):
    """A retried unit's answer must carry retry:true (and a sweep-round
    adjudication must carry sweep_round:true) so a re-round answer is never
    byte-identical to a consumed line. The reverse is enforced too: claiming
    an echo the request never carried is rejected."""
    errs = []
    if bool(resp.get("retry", False)) != bool(require_retry):
        errs.append("retry-echo-mismatch")
    if require_sweep_round is not None and \
            bool(resp.get("sweep_round", False)) != bool(require_sweep_round):
        errs.append("sweep-round-echo-mismatch")
    return errs


def _quote_ok(quote, source_text, allow_empty=False):
    if not isinstance(quote, str):
        return False
    if not common.fold_ws(quote):
        return allow_empty
    return quote_exists(quote, source_text)


# ---- official structure ---------------------------------------------------

def validate_official_structure_output(resp, request, require_retry=False):
    errs = _require(resp, ["structure_id", "display_id_column",
                           "column_roles", "notes"])
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    if resp["structure_id"] != request["structure_id"]:
        return errs + ["wrong-structure-id"]
    headers = {str(h) for h in request["headers"]}
    dic = resp["display_id_column"]
    if dic is not None and (not isinstance(dic, str) or dic not in headers):
        errs.append("bad-display-id-column")
    roles = resp["column_roles"]
    if not isinstance(roles, dict):
        errs.append("bad-column-roles")
    else:
        if {str(k) for k in roles} != headers:
            errs.append("column-roles-headers-mismatch")
        if any(v not in schema.COLUMN_ROLES for v in roles.values()):
            errs.append("bad-column-role")
    if not isinstance(resp["notes"], str):
        errs.append("bad-notes")
    return errs


# ---- table mapping --------------------------------------------------------

def validate_table_mapping_output(resp, table, require_retry=False):
    errs = _require(resp, ["table_index", "classification",
                           "irrelevant_reason", "column_mapping",
                           "context_grouping"])
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    if resp["table_index"] != table["table_index"]:
        return errs + ["wrong-table-index"]
    cls = resp["classification"]
    if cls not in schema.TABLE_CLASSIFICATIONS:
        return errs + ["bad-classification"]
    if cls == "irrelevant" and \
            resp["irrelevant_reason"] not in schema.IRRELEVANT_REASONS:
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
        if v not in schema.MAPPING_TARGETS:
            errs.append("bad-mapping-target")
            break
        if v in schema.CANONICAL_DATA_FIELDS:
            if v in seen_fields:
                errs.append("duplicate-field-mapping")
                break
            seen_fields.add(v)
    cg = resp["context_grouping"]
    if not isinstance(cg, str):
        errs.append("bad-context-grouping")
    elif common.fold_ws(cg):
        if not quote_exists(cg, context_source(table)):
            errs.append("context-grouping-not-verbatim")
    return errs


# ---- row interpretation ---------------------------------------------------

def _validate_interp_record(rec, row_index, cells_by_index):
    if not isinstance(rec, dict):
        return [f"bad-record:{row_index}"]
    fields = rec.get("fields")
    prov = rec.get("field_provenance")
    note = rec.get("interpretation_note", "")
    claim = rec.get("company_claim_reading")
    if not isinstance(fields, dict) or not isinstance(prov, dict) or \
            not isinstance(note, str):
        return [f"bad-record:{row_index}"]
    if claim not in schema.CLAIM_READINGS:
        return [f"bad-claim-reading:{row_index}"]
    for name, value in fields.items():
        if name not in schema.CANONICAL_DATA_FIELDS:
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


def validate_interpretation_output(resp, table, chunk_row_indexes,
                                   require_retry=False):
    errs = _require(resp, ["chunk_id", "rows"])
    if errs:
        return errs
    echo_errs = check_echo_flags(resp, require_retry)
    if echo_errs:
        return echo_errs
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
        if disp not in schema.DISPOSITIONS:
            return ["bad-disposition"]
        if disp == "separator":
            st = entry.get("separator_text", "")
            if not isinstance(st, str):
                return [f"bad-separator:{ri}"]
            if common.fold_ws(st) and not quote_exists(
                    st, " | ".join(str(c) for c in cells_by_index[ri])):
                return [f"separator-not-verbatim:{ri}"]
        if disp == "record":
            recs = entry.get("records")
            if not isinstance(recs, list) or not recs:
                return [f"missing-records:{ri}"]
            for pos, rec in enumerate(recs):
                if not isinstance(rec, dict) or rec.get("sub_index") != pos:
                    return [f"bad-sub-index:{ri}"]
                rerrs = _validate_interp_record(rec, ri, cells_by_index)
                if rerrs:
                    return rerrs
    if seen != chunk_set:
        return [f"missing-rows:{len(chunk_set - seen)}"]
    return []


# ---- match scoping --------------------------------------------------------

def validate_scoping_output(resp, batch_record_ids, chunk_official_ids,
                            require_retry=False):
    errs = _require(resp, ["scoping_id", "nominations"])
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    noms = resp["nominations"]
    if not isinstance(noms, list):
        return errs + ["bad-nominations"]
    for n in noms:
        if not isinstance(n, dict) or \
                n.get("record_id") not in batch_record_ids or \
                n.get("official_row_id") not in chunk_official_ids or \
                not isinstance(n.get("note", ""), str):
            errs.append("bad-nomination")
            break
    return errs


# ---- match adjudication ---------------------------------------------------

def validate_adjudication_output(resp, nominated_ids, record, rows_by_id,
                                 require_retry=False,
                                 require_sweep_round=False):
    errs = _require(resp, _ADJ_KEYS)
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry, require_sweep_round)
    decision = resp["decision"]
    if decision not in schema.MATCH_DECISIONS:
        return errs + ["bad-decision"]
    company_src = company_quote_source(record)
    if decision == "match":
        sels = resp["selections"]
        if not isinstance(sels, list) or not sels:
            return errs + ["no-selections"]
        seen = set()
        for sel in sels:
            if not isinstance(sel, dict):
                return errs + ["bad-selection"]
            oid = sel.get("official_row_id")
            if oid not in nominated_ids:
                errs.append("row-not-nominated")
                continue
            if oid in seen:
                errs.append("duplicate-selection")
                continue
            seen.add(oid)
            if not _quote_ok(sel.get("row_quote"), company_src):
                errs.append("row-quote-not-found")
            if oid not in rows_by_id or not _quote_ok(
                    sel.get("official_quote"),
                    official_quote_source(rows_by_id[oid])):
                errs.append("official-quote-not-found")
    elif decision == "ambiguous":
        ids = resp["ambiguous_official_row_ids"]
        if not isinstance(ids, list) or len(ids) < 2 or \
                not set(ids) <= set(nominated_ids):
            errs.append("ambiguous-needs-two")
    return errs


# ---- sweep ----------------------------------------------------------------

def validate_sweep_output(resp, batch_record_ids, official_ids):
    errs = _require(resp, ["sweep_id", "proposals"])
    if errs:
        return errs
    props = resp["proposals"]
    if not isinstance(props, list):
        return ["bad-proposals"]
    for p in props:
        if not isinstance(p, dict) or \
                p.get("record_id") not in batch_record_ids or \
                p.get("official_row_id") not in official_ids:
            errs.append("bad-proposal")
            break
    return errs


# ---- comparison -----------------------------------------------------------

def _validate_alignment(entry, company_src, official_src):
    errs = _require(entry, _ALIGN_KEYS)
    if errs:
        return errs
    if entry["relation"] not in schema.ALIGNMENT_RELATIONS:
        return ["bad-alignment-relation"]
    if not isinstance(entry["company_ref"], str) or \
            not isinstance(entry["official_column"], str):
        return ["bad-alignment-ref"]
    if not _quote_ok(entry["company_quote"], company_src,
                     allow_empty=entry["relation"] == "company-missing"):
        return ["alignment-company-quote-not-found"]
    if not _quote_ok(entry["official_quote"], official_src,
                     allow_empty=entry["relation"] == "official-missing"):
        return ["alignment-official-quote-not-found"]
    return []


def validate_comparison_output(resp, record, rows_by_id, expected_ids,
                               require_retry=False):
    errs = _require(resp, ["comparison_id", "record_id", "per_rule",
                           "claim_consistency", "record_notes"])
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    per_rule = resp["per_rule"]
    if not isinstance(per_rule, list):
        return errs + ["bad-per-rule"]
    seen_ids = []
    company_src = company_quote_source(record)
    for entry in per_rule:
        if not isinstance(entry, dict):
            return errs + ["bad-per-rule-entry"]
        missing = _require(entry, _PER_RULE_KEYS)
        if missing:
            return errs + missing
        oid = entry["official_row_id"]
        if not isinstance(oid, str) or oid not in expected_ids or \
                oid not in rows_by_id:
            return errs + ["unexpected-official-row"]
        seen_ids.append(oid)
        official_src = official_quote_source(rows_by_id[oid])
        if entry["verdict"] not in schema.VERDICTS:
            errs.append("bad-verdict")
        if entry["confidence"] not in schema.CONFIDENCES:
            errs.append("bad-confidence")
        if not isinstance(entry["human_review"], bool):
            errs.append("bad-human-review")
        ca = entry["change_analysis"]
        if not isinstance(ca, list) or \
                not set(ca) <= schema.CHANGE_TAGS:
            errs.append("bad-change-analysis")
        for key in ("match_rationale", "semantic_differences", "reasoning"):
            if not isinstance(entry[key], str):
                errs.append(f"bad-{key.replace('_', '-')}")
        if not _quote_ok(entry["row_quote"], company_src):
            errs.append("row-quote-not-found")
        if not _quote_ok(entry["official_quote"], official_src):
            errs.append("official-quote-not-found")
        fa = entry["field_alignment"]
        if not isinstance(fa, list):
            errs.append("bad-field-alignment")
        else:
            for a in fa:
                if not isinstance(a, dict):
                    errs.append("bad-field-alignment")
                    break
                aerrs = _validate_alignment(a, company_src, official_src)
                if aerrs:
                    errs.extend(aerrs)
                    break
        if errs:
            return errs
    if sorted(seen_ids) != sorted(expected_ids) or \
            len(seen_ids) != len(set(seen_ids)):
        errs.append("per-rule-coverage-mismatch")
    if resp["claim_consistency"] not in schema.CLAIM_CONSISTENCY:
        errs.append("bad-claim-consistency")
    if not isinstance(resp["record_notes"], str):
        errs.append("bad-record-notes")
    return errs


# ---- rule rollup ----------------------------------------------------------

def validate_rollup_output(resp, expected_record_ids, require_retry=False):
    errs = _require(resp, ["rollup_id", "contributing_record_ids",
                           "joint_verdict", "coverage_of_requirement",
                           "reasoning", "confidence", "human_review"])
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    ids = resp["contributing_record_ids"]
    if not isinstance(ids, list) or \
            any(not isinstance(i, str) for i in ids) or \
            sorted(ids) != sorted(expected_record_ids):
        errs.append("contributing-records-mismatch")
    if resp["joint_verdict"] not in schema.VERDICTS:
        errs.append("bad-verdict")
    if resp["coverage_of_requirement"] not in schema.ROLLUP_COVERAGE:
        errs.append("bad-coverage-of-requirement")
    if resp["confidence"] not in schema.CONFIDENCES:
        errs.append("bad-confidence")
    if not isinstance(resp["human_review"], bool):
        errs.append("bad-human-review")
    if not isinstance(resp["reasoning"], str) or \
            not common.fold_ws(resp["reasoning"]):
        errs.append("bad-reasoning")
    return errs


# ---- validation pass ------------------------------------------------------

def validate_validation_output(resp, claimed_verdict, evidence_source,
                               require_retry=False):
    errs = _require(resp, _VALIDATION_KEYS)
    if errs:
        return errs
    errs += check_echo_flags(resp, require_retry)
    if resp["independent_verdict"] not in schema.VERDICTS:
        errs.append("bad-independent-verdict")
    outcome = resp["outcome"]
    if outcome not in schema.VALIDATION_OUTCOMES:
        return errs + ["bad-outcome"]
    rv = resp["revised_verdict"]
    rca = resp["revised_change_analysis"]
    if outcome == "revised":
        if rv not in schema.VERDICTS:
            errs.append("revised-needs-verdict")
        if rca is not None and (not isinstance(rca, list) or
                                not set(rca) <= schema.CHANGE_TAGS):
            errs.append("bad-revised-change-analysis")
    else:
        if rv is not None:
            errs.append("revised-verdict-without-revised")
        if rca is not None:
            errs.append("revised-change-analysis-without-revised")
    # Mechanical self-consistency on the LLM's own enums: an uphold that
    # disagrees with the validator's own independent conclusion is
    # incoherent output, not a judgment call.
    if outcome == "upheld" and \
            resp["independent_verdict"] != claimed_verdict:
        errs.append("uphold-contradicts-own-verdict")
    reason = resp["reason"]
    if not isinstance(reason, str):
        errs.append("bad-reason")
    elif outcome in ("refuted", "revised", "needs-human") and \
            not common.fold_ws(reason):
        errs.append("reason-required")
    eq = resp["evidence_quote"]
    if not isinstance(eq, str):
        errs.append("bad-evidence-quote")
    elif common.fold_ws(eq) and not quote_exists(eq, evidence_source):
        errs.append("evidence-quote-not-found")
    return errs


# ---- findings bookkeeping -------------------------------------------------

def dedup_findings(findings):
    """One finding per (record, official row) by construction — a duplicate
    is a pipeline bug surfaced as a warning, never silent judgment."""
    seen, kept, dropped = set(), [], []
    for f in findings:
        key = (f["record_id"], f["official_row_id"])
        if key in seen:
            dropped.append(f["finding_id"])
        else:
            seen.add(key)
            kept.append(f)
    return kept, dropped
