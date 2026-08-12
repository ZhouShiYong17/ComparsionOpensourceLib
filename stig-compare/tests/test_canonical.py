import canonical
import schema


_TABLE = {"table_index": 3, "sheet_or_section": "document-body",
          "preceding_narrative": "JB.1.1 SECTION",
          "header_row": ["A", "B"],
          "rows": [{"row_index": 1, "cells": ["x", "y"], "merged": False}]}
_ROW = _TABLE["rows"][0]


def test_build_record_carries_complete_row():
    rec = canonical.build_record(
        _TABLE, _ROW, 0, {"stig_description": "x"},
        {"stig_description": {"row_index": 1, "cell_index": 0}},
        "note", "JB.1.1 SECTION", "comply")
    assert rec["cells"] == ["x", "y"]
    assert rec["header_row"] == ["A", "B"]
    assert rec["preceding_narrative"] == "JB.1.1 SECTION"
    assert rec["continuation_cells"] == []
    assert rec["canonical_fields"] == {"stig_description": "x"}
    assert rec["company_claim_reading"] == "comply"
    assert rec["original_company_text"] == "x | y"
    assert rec["record_id"].startswith("CR-")
    assert rec["source_reference"]["table_index"] == 3
    assert rec["status"] == "ok"


def test_canonical_fields_sparse_and_folded():
    rec = canonical.build_record(
        _TABLE, _ROW, 0, {"stig_description": "  x  ", "company_severity": ""},
        {}, "", "", "none")
    assert rec["canonical_fields"] == {"stig_description": "x"}


def test_failed_record():
    rec = canonical.failed_record(_TABLE, _ROW, "interpretation-rejected")
    assert rec["status"] == "extraction-failed"
    assert rec["notes"] == "interpretation-rejected"
    assert rec["cells"] == ["x", "y"]   # raw row still preserved


def test_chunk_rows_merged_never_starts_chunk():
    rows = [{"row_index": i, "cells": [], "merged": i == 3}
            for i in range(1, 6)]
    chunks = canonical.chunk_rows(rows, size=2)
    # row 3 is merged: it must stay in the chunk of row 2.
    assert [r["row_index"] for r in chunks[0]] == [1, 2, 3]


def test_chunk_size_default_from_schema():
    rows = [{"row_index": i, "cells": [], "merged": False}
            for i in range(schema.INTERPRETATION_CHUNK_ROWS + 1)]
    chunks = canonical.chunk_rows(rows)
    assert len(chunks) == 2


def test_reconcile_reports_unaccounted_rows():
    table = {"rows": [{"row_index": 1}, {"row_index": 2}, {"row_index": 3}]}
    assert canonical.reconcile(table, {1: "record"}) == [2, 3]
    assert canonical.reconcile(table, {1: "a", 2: "b", 3: "c"}) == []


def test_no_claim_regex_left():
    assert not hasattr(canonical, "normalize_claim")
    assert not hasattr(canonical, "_NEGATED_COMPLIANCE")
