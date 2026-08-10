"""Canonical company record model (spec section 3) and mechanical helpers.

All interpretation happens in Claude passes; this module only defines the
target shape plus deterministic claim normalization, chunking, and count
reconciliation. Claim synonyms are intentionally minimal — extensions come
through the rules registry's equivalent-terminology category, never by
editing this file per-submission.
"""
import common
import normalize

CANONICAL_DATA_FIELDS = [
    "stig_description", "stig_objective_or_requirement",
    "stig_command_or_value", "company_approved_setting_or_expected_value",
    "observed_value_or_evidence", "company_compliance_claim",
    "company_severity", "remarks_or_justification"]

MAPPING_TARGETS = set(CANONICAL_DATA_FIELDS) | {"extra_field", "ignore"}
TABLE_CLASSIFICATIONS = {"stig_relevant", "irrelevant", "uncertain"}
IRRELEVANT_REASONS = {"instructions", "general-info", "toc", "signoff",
                      "other"}
DISPOSITIONS = {"record", "separator", "continuation"}


def normalize_claim(text):
    norm = normalize.norm_text(text)
    if not norm:
        return "unknown"
    if "deviat" in norm:
        return "deviation"
    if "comply" in norm or "compliant" in norm or "adopt" in norm:
        return "comply"
    return "unknown"


def original_text(cells):
    return " | ".join(str(c) for c in cells)


def chunk_rows(rows, size=40):
    """Chunks of <= size rows; a merged row never starts a chunk (it may be
    a continuation of the previous row and must stay in the same request)."""
    chunks, current = [], []
    for row in rows:
        if len(current) >= size and not row.get("merged"):
            chunks.append(current)
            current = []
        current.append(row)
    if current:
        chunks.append(current)
    return chunks


def build_record(table, row, sub_index, fields, field_provenance,
                 extra_fields, interpretation_note, context_grouping):
    raw = original_text(row["cells"])
    rec = {f: "" for f in CANONICAL_DATA_FIELDS}
    for k, v in (fields or {}).items():
        rec[k] = common.fold_ws(v)
    rec["record_id"] = common.record_id(
        table["table_index"], row["row_index"], sub_index, raw)
    rec["row_id"] = common.row_id(table["table_index"], row["row_index"], raw)
    rec["context_grouping"] = context_grouping or ""
    rec["claim_normalized"] = normalize_claim(rec["company_compliance_claim"])
    rec["extra_fields"] = dict(extra_fields or {})
    rec["interpretation_note"] = interpretation_note or ""
    rec["field_provenance"] = dict(field_provenance or {})
    rec["source_reference"] = {
        "table_index": table["table_index"], "row_index": row["row_index"],
        "sub_index": sub_index,
        "sheet_or_section": table["sheet_or_section"],
        "table_title": context_grouping or ""}
    rec["original_company_text"] = raw
    rec["status"] = "ok"
    rec["notes"] = ""
    return rec


def failed_record(table, row, note):
    rec = build_record(table, row, 0, {}, {}, {}, "", "")
    rec["status"] = "extraction-failed"
    rec["notes"] = note
    return rec


def reconcile(table, dispositions):
    """dispositions: {row_index(int): disposition}. Returns row indexes
    present in the table but never accounted for by any response."""
    expected = {r["row_index"] for r in table["rows"]}
    return sorted(expected - set(dispositions))
