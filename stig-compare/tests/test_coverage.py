import coverage


def _rows(n, status="ok"):
    return [{"row_id": f"R-{i:08d}", "status": status} for i in range(n)]


def _rules(n):
    return [{"rule_id": f"V-{1000+i}"} for i in range(n)]


def _match(rid, tier, rule=None):
    return {"row_id": rid, "tier": tier, "matched_rule_id": rule,
            "ambiguous_rule_ids": []}


def test_buckets_and_sum():
    rows = _rows(5)
    rows[4]["status"] = "extraction-failed"
    matches = [_match("R-00000000", "T1", "V-1000"),
               _match("R-00000001", "T2", "V-1001"),
               _match("R-00000002", "T3"),
               _match("R-00000003", "T4")]
    cov = coverage.compute(rows, _rules(3), matches, ignored_row_ids=set())
    c = cov["company"]
    assert (c["matched"], c["ambiguous"], c["unmatched"],
            c["extraction_failed"]) == (2, 1, 1, 1)
    assert cov["ok"] is True
    assert cov["official"]["addressed"] == 2
    assert cov["official"]["unaddressed"] == 1
    assert any(w["code"] == "extraction-failures" for w in cov["warnings"])


def test_duplicate_coverage_flagged():
    rows = _rows(2)
    matches = [_match("R-00000000", "T1", "V-1000"),
               _match("R-00000001", "T2", "V-1000")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert cov["official"]["duplicate_coverage_rule_ids"] == ["V-1000"]


def test_red_banner_over_ten_percent():
    rows = _rows(10)
    for r in rows[:2]:
        r["status"] = "extraction-failed"
    matches = [_match(r["row_id"], "T4") for r in rows[2:]]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert any(w["code"] == "low-coverage-red-banner" for w in cov["warnings"])


def test_unaccounted_row_fails_loudly():
    rows = _rows(3)          # one row has no match result and status ok
    matches = [_match("R-00000000", "T4"), _match("R-00000001", "T4")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    # missing rows are counted as unmatched, never silently dropped
    assert cov["company"]["unmatched"] == 3
    assert cov["ok"] is True


def test_needs_structuring_unresolved_counts():
    rows = _rows(2)
    rows[1]["status"] = "needs-structuring"
    matches = [_match("R-00000000", "T4")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert cov["company"]["needs_structuring_unresolved"] == 1
