import coverage


def _table(ti, n_rows, cls="stig_relevant", disps=None, parents=None):
    return ({"table_index": ti, "sheet_or_section": "document-body",
             "preceding_narrative": "", "header_row": ["A"],
             "rows": [{"row_index": i, "cells": ["x"], "merged": False}
                      for i in range(1, n_rows + 1)]},
            {"table_index": ti, "classification": cls,
             "irrelevant_reason": "", "column_mapping": {},
             "context_grouping": "", "mapping_failures": 0,
             "row_dispositions": disps or {}, "parent_of": parents or {},
             "chunks": {}})


def _rec(rid, ti, ri, status="ok", sub=0):
    return {"record_id": rid, "row_id": "R-" + rid, "status": status,
            "source_reference": {"table_index": ti, "row_index": ri,
                                 "sub_index": sub}}


def _match(rid, tier, matched=(), ):
    return {"record_id": rid, "tier": tier,
            "matched_rule_ids": list(matched), "candidates": []}


OFFICIAL = [{"rule_id": "V-1"}, {"rule_id": "V-2"}, {"rule_id": "V-3"}]


def test_buckets_sum_and_classify():
    t1, ts1 = _table(1, 2, cls="irrelevant")
    t2, ts2 = _table(2, 4, disps={"1": "record", "2": "separator",
                                   "3": "record", "4": "record"})
    skeleton = [t1, t2]
    tstate = {1: ts1, 2: ts2}
    records = [_rec("a", 2, 1), _rec("b", 2, 3),
               _rec("c", 2, 4, status="extraction-failed")]
    matches = [_match("a", "T2", ["V-1", "V-2"]), _match("b", "T3")]
    out = coverage.compute(skeleton, tstate, records, OFFICIAL, matches, set())
    assert out["ok"]
    c = out["company"]
    assert c["total"] == 6
    assert c["ignored_irrelevant_table"] == 2
    assert c["separator"] == 1
    assert c["matched"] == 1 and c["ambiguous"] == 1
    assert c["extraction_failed"] == 1
    assert out["official"]["addressed"] == 2
    assert out["official"]["unaddressed"] == 1


def test_continuation_takes_parent_bucket_and_split_rows_aggregate():
    t, ts = _table(1, 2, disps={"1": "record", "2": "continuation"},
                   parents={"2": 1})
    records = [_rec("a", 1, 1, sub=0), _rec("b", 1, 1, sub=1)]
    matches = [_match("a", "T4"), _match("b", "T2", ["V-1"])]
    out = coverage.compute([t], {1: ts}, records, OFFICIAL, matches, set())
    assert out["company"]["matched"] == 2  # row 1 aggregates to matched; row 2 follows parent
    assert out["ok"]


def test_unanswered_table_rows_are_extraction_failed():
    t, ts = _table(1, 3, cls=None)
    out = coverage.compute([t], {1: ts}, [], OFFICIAL, [], set())
    assert out["company"]["extraction_failed"] == 3
    assert out["ok"]


def test_red_banner_excludes_irrelevant_tables():
    t1, ts1 = _table(1, 50, cls="irrelevant")
    t2, ts2 = _table(2, 2, disps={"1": "record", "2": "record"})
    records = [_rec("a", 2, 1), _rec("b", 2, 2)]
    matches = [_match("a", "T2", ["V-1"]), _match("b", "T2", ["V-2"])]
    out = coverage.compute([t1, t2], {1: ts1, 2: ts2}, records, OFFICIAL,
                           matches, set())
    assert not any(w["code"] == "low-coverage-red-banner"
                   for w in out["warnings"])


def test_duplicate_coverage_flagged():
    t, ts = _table(1, 2, disps={"1": "record", "2": "record"})
    records = [_rec("a", 1, 1), _rec("b", 1, 2)]
    matches = [_match("a", "T2", ["V-1"]), _match("b", "T2", ["V-1"])]
    out = coverage.compute([t], {1: ts}, records, OFFICIAL, matches, set())
    assert out["official"]["duplicate_coverage_rule_ids"] == ["V-1"]
