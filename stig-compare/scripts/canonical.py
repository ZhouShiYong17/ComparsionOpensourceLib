"""Company record mechanics: shape, chunking, count reconciliation.

All interpretation happens in Claude passes; this module only builds the
stored record shape. A record carries the COMPLETE verbatim row (cells,
continuation cells, header row, narrative, provenance) — the canonical
fields the interpretation pass extracts are an additive aid nested under
`canonical_fields`, never a replacement for the raw row.
"""
import common
import schema

CANONICAL_DATA_FIELDS = schema.CANONICAL_DATA_FIELDS


def original_text(cells):
    return " | ".join(str(c) for c in cells)


def chunk_rows(rows, size=schema.INTERPRETATION_CHUNK_ROWS):
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
                 interpretation_note, context_grouping, claim_reading):
    raw = original_text(row["cells"])
    rec = {
        "record_id": common.record_id(
            table["table_index"], row["row_index"], sub_index, raw),
        "row_id": common.row_id(table["table_index"], row["row_index"], raw),
        "source_reference": {
            "table_index": table["table_index"],
            "row_index": row["row_index"],
            "sub_index": sub_index,
            "sheet_or_section": table["sheet_or_section"],
            "table_title": context_grouping or ""},
        "header_row": list(table.get("header_row", [])),
        "cells": [str(c) for c in row["cells"]],
        "continuation_cells": [],
        "merged": bool(row.get("merged")),
        "preceding_narrative": table.get("preceding_narrative", ""),
        "context_grouping": context_grouping or "",
        "canonical_fields": {k: common.fold_ws(v)
                             for k, v in (fields or {}).items()
                             if common.fold_ws(v or "")},
        "field_provenance": dict(field_provenance or {}),
        "interpretation_note": interpretation_note or "",
        "company_claim_reading": claim_reading or "none",
        "original_company_text": raw,
        "status": "ok",
        "notes": "",
    }
    return rec


def failed_record(table, row, note):
    rec = build_record(table, row, 0, {}, {}, "", "", "none")
    rec["status"] = "extraction-failed"
    rec["notes"] = note
    return rec


def reconcile(table, dispositions):
    """dispositions: {row_index(int): disposition}. Returns row indexes
    present in the table but never accounted for by any response."""
    expected = {r["row_index"] for r in table["rows"]}
    return sorted(expected - set(dispositions))
