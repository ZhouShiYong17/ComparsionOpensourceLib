"""The information-preservation invariant: every request kind embeds the
COMPLETE rows of both sides, built only by payloads.py."""
import json

import pytest

import payloads
from fixtures import build_fixtures
import helpers


def test_official_payload_is_complete():
    row = {"official_row_id": "OR-1", "display_id": "V-1", "headers": ["A"],
           "cells": ["x"], "raw_record": {"A": "x"},
           "sheet_or_section": "csv", "row_number": 2,
           "provenance": {"source_file": "f", "locator": "csv,row=2"},
           "column_roles": {"A": "title"}, "internal_bookkeeping": 1}
    p = payloads.official_row_payload(row)
    for k in ("official_row_id", "display_id", "headers", "cells",
              "raw_record", "sheet_or_section", "row_number", "provenance",
              "column_roles"):
        assert p[k] == row[k]
    assert "internal_bookkeeping" not in p


def test_company_payload_is_complete():
    rec = {"record_id": "CR-1", "row_id": "R-1",
           "source_reference": {"table_index": 1}, "header_row": ["A"],
           "cells": ["x"], "continuation_cells": [{"row_index": 2,
                                                   "cells": ["y"]}],
           "merged": False, "preceding_narrative": "narr",
           "context_grouping": "g", "canonical_fields": {},
           "field_provenance": {}, "interpretation_note": "",
           "company_claim_reading": "none", "original_company_text": "x",
           "status": "ok", "notes": "", "match_bookkeeping": 1}
    p = payloads.company_record_payload(rec)
    assert p["cells"] == ["x"]
    assert p["continuation_cells"] == [{"row_index": 2, "cells": ["y"]}]
    assert p["header_row"] == ["A"]
    assert p["preceding_narrative"] == "narr"
    assert "match_bookkeeping" not in p


@pytest.fixture(scope="module")
def chain_run(tmp_path_factory):
    fx = build_fixtures.build_all(tmp_path_factory.mktemp("fx"))
    rd = tmp_path_factory.mktemp("run")
    final = helpers.drive_chain(str(fx["official_csv"]),
                                str(fx["company_real_docx"]), rd)
    return rd, final


def _assert_company_complete(rec):
    for k in ("cells", "continuation_cells", "header_row",
              "preceding_narrative", "record_id", "source_reference"):
        assert k in rec, f"company payload missing {k}"
    assert rec["cells"]


def _assert_official_complete(row):
    for k in ("official_row_id", "headers", "cells", "raw_record",
              "provenance", "row_number"):
        assert k in row, f"official payload missing {k}"
    assert row["raw_record"]


def test_every_request_kind_embeds_complete_rows(chain_run):
    rd, _final = chain_run
    scoping = helpers.read_jsonl(rd / "scoping_requests.jsonl")
    assert scoping
    for req in scoping:
        for rec in req["records"]:
            _assert_company_complete(rec)
        for row in req["official_rows"]:
            _assert_official_complete(row)
    adjudication = helpers.read_jsonl(rd / "adjudication_requests.jsonl")
    assert adjudication
    for req in adjudication:
        _assert_company_complete(req["record"])
        for row in req["nominated_rows"]:
            _assert_official_complete(row)
    comparison = helpers.read_jsonl(rd / "comparison_requests.jsonl")
    assert comparison
    for req in comparison:
        _assert_company_complete(req["record"])
        for row in req["official_rows"]:
            _assert_official_complete(row)
    validation = helpers.read_jsonl(rd / "validation_requests.jsonl")
    assert validation
    for req in validation:
        _assert_company_complete(req["record"])
        for row in req["official_rows"]:
            _assert_official_complete(row)


def test_findings_carry_complete_payloads(chain_run):
    _rd, final = chain_run
    assert final["findings"]
    for f in final["findings"]:
        _assert_company_complete(f["company_row"])
        _assert_official_complete(f["official_row"])
