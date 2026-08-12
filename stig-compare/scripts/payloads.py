"""Complete-row payload builders — the information-preservation invariant.

Every request kind that references a company record or an official row must
embed the payload built here, and only here. The shapes are explicit field
allowlists so tests can assert that no request ever carries a reduced view
of either side.
"""

_OFFICIAL_FIELDS = [
    "official_row_id", "display_id", "headers", "cells", "raw_record",
    "sheet_or_section", "row_number", "provenance", "column_roles"]

_COMPANY_FIELDS = [
    "record_id", "row_id", "source_reference", "header_row", "cells",
    "continuation_cells", "merged", "preceding_narrative",
    "context_grouping", "canonical_fields", "field_provenance",
    "interpretation_note", "company_claim_reading",
    "original_company_text", "status", "notes"]


def official_row_payload(row):
    """The COMPLETE official row as embedded in every request that cites it:
    all columns verbatim (cells + raw_record), headers, provenance, plus the
    additive structure-pass annotations (display_id, column_roles)."""
    return {k: row.get(k) for k in _OFFICIAL_FIELDS}


def company_record_payload(record):
    """The COMPLETE company record as embedded in every request that cites
    it: the verbatim parent-row cells, ALL continuation-row cells, the header
    row, surrounding narrative, provenance, and the additive interpretation
    aids (canonical_fields, claim reading, note)."""
    return {k: record.get(k) for k in _COMPANY_FIELDS}
