import coverage


def _rec(rid, ti, ri, status="ok"):
    return {"record_id": rid, "status": status,
            "source_reference": {"table_index": ti, "row_index": ri}}


def _match(rid, decision, selected=()):
    return {"record_id": rid, "decision": decision,
            "selected_official_row_ids": list(selected)}


def test_bucket_priorities():
    m = {"a": _match("a", "match", ["OR-1"]), "b": _match("b", "ambiguous"),
         "c": _match("c", "none"), "d": _match("d", None)}
    assert coverage.bucket_for_records(
        [_rec("a", 1, 1), _rec("c", 1, 1)], m) == "matched"
    assert coverage.bucket_for_records(
        [_rec("b", 1, 1), _rec("c", 1, 1)], m) == "ambiguous"
    assert coverage.bucket_for_records([_rec("c", 1, 1)], m) == "unmatched"
    # A None decision (pass never ran) makes the row unresolved, never
    # silently unmatched.
    assert coverage.bucket_for_records(
        [_rec("c", 1, 1), _rec("d", 1, 1)], m) == "unresolved"
    assert coverage.bucket_for_records(
        [_rec("e", 1, 1)],
        {"e": _match("e", "unresolved-llm-output-rejected")}) == "unresolved"


def test_bucket_extraction_failed():
    assert coverage.bucket_for_records([], {}) == "extraction_failed"
    assert coverage.bucket_for_records(
        [_rec("x", 1, 1, status="extraction-failed")], {}) == \
        "extraction_failed"


def _mini_run():
    tables = [{"table_index": 1, "rows": [
        {"row_index": 1}, {"row_index": 2}, {"row_index": 3},
        {"row_index": 4}]}]
    tstate = {1: {"classification": "stig_relevant",
                  "row_dispositions": {"1": "record", "2": "record",
                                       "3": "separator", "4": "continuation"},
                  "parent_of": {"4": 2}}}
    records = [_rec("a", 1, 1), _rec("b", 1, 2)]
    official = [{"official_row_id": "OR-1"}, {"official_row_id": "OR-2"}]
    matches = [_match("a", "match", ["OR-1"]), _match("b", "match", ["OR-1"])]
    return tables, tstate, records, official, matches


def test_compute_sums_and_continuation_inherits():
    tables, tstate, records, official, matches = _mini_run()
    cov = coverage.compute(tables, tstate, records, official, matches)
    c = cov["company"]
    assert c["total"] == 4
    # continuation row 4 inherits its parent row 2's "matched" bucket
    assert c["matched"] == 3
    assert c["separator"] == 1
    assert cov["ok"]


def test_official_side_counts_multi_matched():
    tables, tstate, records, official, matches = _mini_run()
    cov = coverage.compute(tables, tstate, records, official, matches)
    o = cov["official"]
    assert o["addressed"] == 1
    assert o["unaddressed"] == 1
    assert o["multi_matched_row_ids"] == ["OR-1"]


def test_irrelevant_and_unprocessable_tables():
    tables = [{"table_index": 1, "rows": [{"row_index": 1}]},
              {"table_index": 2, "rows": [{"row_index": 1}]}]
    tstate = {1: {"classification": "irrelevant"},
              2: {"classification": "mapping-failed"}}
    cov = coverage.compute(tables, tstate, [], [], [])
    assert cov["company"]["ignored_irrelevant_table"] == 1
    assert cov["company"]["extraction_failed"] == 1
    assert cov["ok"]


def test_red_banner_counts_unresolved():
    tables = [{"table_index": 1, "rows": [{"row_index": 1}]}]
    tstate = {1: {"classification": "stig_relevant",
                  "row_dispositions": {"1": "record"}, "parent_of": {}}}
    records = [_rec("a", 1, 1)]
    cov = coverage.compute(tables, tstate, records, [],
                           [_match("a", None)])
    assert cov["company"]["unresolved"] == 1
    assert any(w["code"] == "low-coverage-red-banner"
               for w in cov["warnings"])


def test_no_ignored_by_rule_bucket():
    tables, tstate, records, official, matches = _mini_run()
    cov = coverage.compute(tables, tstate, records, official, matches)
    assert "ignored_by_rule" not in cov["company"]
