import canonical


TABLE = {"table_index": 3, "sheet_or_section": "document-body",
         "preceding_narrative": "JB.1.1 STIG HARDEING- SEVERITY HIGH",
         "header_row": ["STIG REQUIREMENT", "DESCRIPTION",
                        "COMMAND TO VERIFY", "APPROVED SETTING"],
         "rows": [{"row_index": 1,
                   "cells": ["Password reuse must be restricted",
                             "Users should not reuse passwords",
                             "Run SHOW PARAMETER password_reuse_max",
                             "9 or more"],
                   "merged": False}]}


def test_normalize_claim():
    assert canonical.normalize_claim("COMPLY") == "comply"
    assert canonical.normalize_claim("Deviation") == "deviation"
    assert canonical.normalize_claim(
        "DEVIATION - cannot comply") == "deviation"
    assert canonical.normalize_claim("Adopt company standards") == "comply"
    assert canonical.normalize_claim("") == "unknown"
    assert canonical.normalize_claim("see remarks") == "unknown"


def test_chunk_rows_respects_size_and_merged_rows():
    rows = [{"row_index": i, "cells": [], "merged": i == 41}
            for i in range(1, 44)]
    chunks = canonical.chunk_rows(rows, size=40)
    assert [len(c) for c in chunks] == [41, 2]
    assert chunks[1][0]["row_index"] == 42


def test_build_record_shape_and_ids():
    rec = canonical.build_record(
        TABLE, TABLE["rows"][0], 0,
        {"stig_objective_or_requirement": "Password reuse must be restricted",
         "company_compliance_claim": ""},
        {"stig_objective_or_requirement": {"row_index": 1, "cell_index": 0}},
        {"REPORTING yes/no": "YES"}, "note text",
        "JB.1.1 STIG HARDEING- SEVERITY HIGH")
    assert rec["record_id"].startswith("CR-")
    assert rec["row_id"].startswith("R-")
    assert rec["status"] == "ok"
    assert rec["claim_normalized"] == "unknown"
    assert rec["stig_description"] == ""
    assert rec["extra_fields"] == {"REPORTING yes/no": "YES"}
    assert rec["source_reference"]["sub_index"] == 0
    assert "password_reuse_max" in rec["original_company_text"]


def test_failed_record():
    rec = canonical.failed_record(TABLE, TABLE["rows"][0], "canonicalize-rejected")
    assert rec["status"] == "extraction-failed"
    assert rec["notes"] == "canonicalize-rejected"


def test_reconcile_reports_missing():
    assert canonical.reconcile(TABLE, {}) == [1]
    assert canonical.reconcile(TABLE, {1: "record"}) == []
