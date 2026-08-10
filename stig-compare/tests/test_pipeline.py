import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all
import common
import pipeline


@pytest.fixture()
def run(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(fx["company_docx"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    return run_dir


def test_start_produces_artifacts_and_t1_match(run):
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["official_sha256"]) == 64
    assert "skill_version" in manifest["versions"]
    state = common.read_jsonl(run / "match_state.jsonl")
    by_tier = {}
    for m in state:
        by_tier.setdefault(m["tier"], []).append(m)
    assert len(by_tier.get("T1", [])) >= 1          # password_reuse_max row
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    assert all(r["candidates"] for r in requests)


def test_resolve_accepts_valid_match_and_rejects_invented_rule(run):
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = requests[0]
    good = {"row_id": req["row_id"], "decision": "match",
            "rule_id": req["candidates"][0]["rule_id"],
            "ambiguous_rule_ids": [],
            "row_quote": req["row"]["original_company_text"][:20],
            "rule_quote": req["candidates"][0]["title"][:20],
            "basis": "same requirement"}
    bad_req = requests[1] if len(requests) > 1 else req
    bad = {"row_id": bad_req["row_id"], "decision": "match",
           "rule_id": "V-9999", "ambiguous_rule_ids": [],
           "row_quote": "x", "rule_quote": "y", "basis": "invented"}
    common.write_jsonl(run / "matching_responses.jsonl", [good, bad])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state[good["row_id"]]["tier"] == "T2"
    failures = common.read_jsonl(run / "validation_failures.jsonl")
    assert any(f["row_id"] == bad["row_id"] and
               "rule-not-in-shortlist" in f["errors"] for f in failures)
    retry = common.read_jsonl(run / "matching_requests.jsonl")
    assert any(r.get("retry") for r in retry if r["row_id"] == bad["row_id"])


def test_finalize_refuses_pending_requests(run):
    # no matching responses provided -> pending matching requests exist
    common.write_jsonl(run / "matching_responses.jsonl", [])
    pipeline.main(["resolve", "--run-dir", str(run)])
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report"])
    assert rc == 4


def test_finalize_allow_pending_yields_cannot_assess(run):
    common.write_jsonl(run / "matching_responses.jsonl", [])
    pipeline.main(["resolve", "--run-dir", str(run)])
    rc = pipeline.main(["finalize", "--run-dir", str(run),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["ok"] is True
    for f in final["findings"]:
        if f.get("basis") == "semantic-pass-not-run":
            assert f["verdict"] == "Cannot Assess"
            assert f["human_review_needed"] is True


def test_assign_confidence():
    t1 = {"tier": "T1", "margin_flag": False}
    det = {"deterministic": True}
    sem = {"deterministic": False}
    assert pipeline.assign_confidence(t1, det, None) == "High"
    t2 = {"tier": "T2", "margin_flag": False}
    assert pipeline.assign_confidence(t2, det, None) == "High"
    assert pipeline.assign_confidence(t2, sem, "upheld") == "Medium"
    assert pipeline.assign_confidence(t2, sem, "undetermined") == "Low"
    t2m = {"tier": "T2", "margin_flag": True}
    assert pipeline.assign_confidence(t2m, det, None) == "Low"


# --------------------------------------------------------------------------
# Regression tests for the review's Important findings (containment behaviors)
# --------------------------------------------------------------------------

def test_second_strike_forces_t4_and_retried(run):
    """(a) Two genuinely different invalid matching responses for the same
    row -> tier T4, warning llm-output-rejected, retried True, no finding."""
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = requests[0]
    bad1 = {"row_id": req["row_id"], "decision": "match", "rule_id": "V-9999",
            "ambiguous_rule_ids": [], "row_quote": "x", "rule_quote": "y",
            "basis": "invented-1"}
    common.write_jsonl(run / "matching_responses.jsonl", [bad1])
    pipeline.main(["resolve", "--run-dir", str(run)])
    state = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state[req["row_id"]]["tier"] is None
    assert state[req["row_id"]]["match_failures"] == 1

    bad2 = {"row_id": req["row_id"], "decision": "match", "rule_id": "V-8888",
            "ambiguous_rule_ids": [], "row_quote": "x", "rule_quote": "y",
            "basis": "invented-2"}
    common.write_jsonl(run / "matching_responses.jsonl", [bad2])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state2 = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    m = state2[req["row_id"]]
    assert m["tier"] == "T4"
    assert m["retried"] is True
    assert "llm-output-rejected" in m["warnings"]
    findings = common.read_jsonl(run / "findings.jsonl")
    assert not any(f["row_id"] == req["row_id"] for f in findings)


def test_margin_downgrade_to_t3(run):
    """(b) A margin_flag row whose accepted match's rule_quote also exists in
    the runner-up candidate's text is downgraded from T2 to T3."""
    state = common.read_jsonl(run / "match_state.jsonl")
    for m in state:
        if m["row_id"] == "R-e8bf0dc9":
            assert len(m["candidates"]) >= 2
            m["margin_flag"] = True
    common.write_jsonl(run / "match_state.jsonl", state)

    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = [r for r in requests if r["row_id"] == "R-e8bf0dc9"][0]
    chosen = req["candidates"][0]
    resp = {"row_id": req["row_id"], "decision": "match",
            "rule_id": chosen["rule_id"], "ambiguous_rule_ids": [],
            "row_quote": req["row"]["original_company_text"][:15],
            "rule_quote": "password",  # shared by every password-related rule
            "basis": "overlap"}
    common.write_jsonl(run / "matching_responses.jsonl", [resp])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state2 = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    m = state2["R-e8bf0dc9"]
    assert m["tier"] == "T3"
    assert chosen["rule_id"] in m["ambiguous_rule_ids"]
    assert len(m["ambiguous_rule_ids"]) == 2


def test_rule_equivalence_and_missing_evidence_guard(run, monkeypatch):
    """(c) An injected equivalent-terminology rule produces a Compliant /
    rule-equivalence finding with the rule id recorded in applied_rules when
    there is evidence -- but is never consulted when observed evidence is
    empty (the missing-evidence hard rule always wins)."""
    fake_registry = {"registry_version": 1, "rules": [
        {"rule_id": "EQ-1", "category": "equivalent-terminology",
         "status": "active", "scope": {"level": "global"},
         "payload": {"a": "nine", "b": "9 or more"}}]}
    monkeypatch.setattr(pipeline.rules_mod, "load_registry",
                        lambda path: fake_registry)

    rows = common.read_jsonl(run / "company_rows.jsonl")
    for r in rows:
        if r["row_id"] == "R-c390d3d4":       # T1 row, matched to V-1001
            r["observed_value_or_evidence"] = "nine"
    common.write_jsonl(run / "company_rows.jsonl", rows)
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    findings = common.read_jsonl(run / "findings.jsonl")
    f = [f for f in findings if f["row_id"] == "R-c390d3d4"][0]
    assert f["verdict"] == "Compliant"
    assert f["basis"] == "rule-equivalence"
    assert f["applied_rules"] == ["EQ-1"]


def test_rule_equivalence_guard_blocks_empty_evidence(run, monkeypatch):
    fake_registry = {"registry_version": 1, "rules": [
        {"rule_id": "EQ-BUG", "category": "equivalent-terminology",
         "status": "active", "scope": {"level": "global"},
         "payload": {"a": "", "b": "9 or more"}}]}
    monkeypatch.setattr(pipeline.rules_mod, "load_registry",
                        lambda path: fake_registry)

    rows = common.read_jsonl(run / "company_rows.jsonl")
    for r in rows:
        if r["row_id"] == "R-c390d3d4":
            r["observed_value_or_evidence"] = ""   # no evidence at all
    common.write_jsonl(run / "company_rows.jsonl", rows)
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    findings = common.read_jsonl(run / "findings.jsonl")
    f = [f for f in findings if f["row_id"] == "R-c390d3d4"][0]
    assert f["verdict"] == "Cannot Assess"
    assert f["basis"] == "missing-evidence"
    assert f["applied_rules"] == []


def test_skeptic_refuted_marks_disputed_but_keeps_finding(run):
    """(d) A refuted skeptic outcome disputes a finding without dropping it
    or altering its verdict."""
    common.write_jsonl(run / "matching_responses.jsonl", [])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    det = [f for f in final["findings"] if f["row_id"] == "R-c390d3d4"][0]
    assert det["verdict"] == "Compliant"

    skeptic = {"finding_id": det["finding_id"], "outcome": "refuted",
               "reason": "misquoted"}
    common.write_jsonl(run / "skeptic_responses.jsonl", [skeptic])
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final2 = json.loads((run / "final.json").read_text(encoding="utf-8"))
    det2 = [f for f in final2["findings"]
            if f["finding_id"] == det["finding_id"]][0]
    assert det2["disputed"] is True
    assert det2["skeptic"]["outcome"] == "refuted"
    assert det2["verdict"] == "Compliant"           # kept, not overwritten


def test_replayed_matching_response_is_a_no_op(run):
    """(e) Re-running resolve with an unchanged matching_responses.jsonl must
    not re-apply, re-fail, or otherwise disturb an already-consumed
    response (regression: previously flipped a clean T2 finding's
    human_review_needed to True on the second run via a spurious
    no-such-request entry)."""
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = requests[0]
    good = {"row_id": req["row_id"], "decision": "match",
            "rule_id": req["candidates"][0]["rule_id"],
            "ambiguous_rule_ids": [],
            "row_quote": req["row"]["original_company_text"][:20],
            "rule_quote": req["candidates"][0]["title"][:20],
            "basis": "same requirement"}
    common.write_jsonl(run / "matching_responses.jsonl", [good])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state1 = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state1[good["row_id"]]["tier"] == "T2"
    failures_path = run / "validation_failures.jsonl"
    failures1 = common.read_jsonl(failures_path) if failures_path.exists() else []
    assert not any(f["row_id"] == good["row_id"] for f in failures1)

    # replay the identical, unchanged responses file
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state2 = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state2[good["row_id"]]["tier"] == "T2"
    assert state2[good["row_id"]]["match_failures"] == 0
    failures2 = common.read_jsonl(failures_path) if failures_path.exists() else []
    assert not any(f["row_id"] == good["row_id"] for f in failures2)

    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    f = [f for f in final["findings"] if f["row_id"] == good["row_id"]][0]
    assert f["confidence"] == "High"
    assert f["human_review_needed"] is False


def test_malformed_jsonl_line_recorded_batch_still_applied(run):
    """(f) A syntactically-broken line in matching_responses.jsonl is
    recorded as a validation failure (never a crash) and does not block the
    rest of the batch from being applied."""
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = requests[0]
    good = {"row_id": req["row_id"], "decision": "match",
            "rule_id": req["candidates"][0]["rule_id"],
            "ambiguous_rule_ids": [],
            "row_quote": req["row"]["original_company_text"][:20],
            "rule_quote": req["candidates"][0]["title"][:20],
            "basis": "same requirement"}
    path = run / "matching_responses.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{this is not valid json,,,\n")
        f.write(json.dumps(good) + "\n")

    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    failures = common.read_jsonl(run / "validation_failures.jsonl")
    assert any("malformed-json" in f["errors"] for f in failures)
    state = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state[good["row_id"]]["tier"] == "T2"


def test_unanswered_structuring_rows_counted_and_listed(tmp_path):
    """(g) Rows that never receive a structuring response stay bucketed as
    needs_structuring_unresolved in coverage and are listed in
    final.json's unresolved_rows."""
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(fx["company_docx_messy"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    struct_reqs = common.read_jsonl(run_dir / "structuring_requests.jsonl")
    assert struct_reqs                      # messy headers need structuring

    rc = pipeline.main(["resolve", "--run-dir", str(run_dir)])
    assert rc == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["company"]["needs_structuring_unresolved"] >= 1

    unresolved_ids = {r["row_id"] for r in final["unresolved_rows"]
                      if r["status"] == "needs-structuring"}
    assert unresolved_ids
    requested_ids = {r["row_id"] for r in struct_reqs}
    assert unresolved_ids <= requested_ids
