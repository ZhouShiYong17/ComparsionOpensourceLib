import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all, _write_docx
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


@pytest.fixture(scope="module")
def fixture_paths(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("fx"))


def test_start_writes_skeleton_and_mapping_requests(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start",
                        "--official", str(fx["official_csv"]),
                        "--company", str(fx["company_real_docx"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["official_sha256"]) == 64
    assert "skill_version" in manifest["versions"]
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    assert len(skel["tables"]) == 4
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    assert len(reqs) == 4
    assert reqs[2]["header_row"][0] == "STIG REQUIREMENT"
    assert reqs[2]["instructions_file"] == "prompts/table_mapping.md"
    assert "header_hints" in reqs[2]
    tstate = common.read_jsonl(run_dir / "table_state.jsonl")
    assert all(t["classification"] is None for t in tstate)
    assert common.read_jsonl(run_dir / "match_state.jsonl") == []
    assert common.read_jsonl(run_dir / "company_records.jsonl") == []
    assert not (run_dir / "company_rows.jsonl").exists()
    assert not (run_dir / "structuring_requests.jsonl").exists()
    assert not (run_dir / "matching_requests.jsonl").exists()


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


def test_skeptic_merge_rejects_bad_outcome_bad_reason_and_unknown_finding(run):
    """Minor finding 5: the skeptic merge must not merge an out-of-enum
    outcome, a non-string reason, or an unknown finding_id -- each must be
    recorded as a validation failure (malformed-response / no-such-request)
    instead of being merged onto a finding or silently dropped."""
    common.write_jsonl(run / "matching_responses.jsonl", [])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    det = [f for f in final["findings"] if f["row_id"] == "R-c390d3d4"][0]
    assert det["skeptic"] is None

    bad_outcome = {"finding_id": det["finding_id"], "outcome": "maybe",
                  "reason": "not a real outcome value"}
    bad_reason_type = {"finding_id": det["finding_id"], "outcome": "upheld",
                       "reason": ["not", "a", "string"]}
    unknown_fid = {"finding_id": "F-doesnotexist00", "outcome": "upheld",
                  "reason": "fine but nothing to attach to"}
    common.write_jsonl(run / "skeptic_responses.jsonl",
                       [bad_outcome, bad_reason_type, unknown_fid])
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final2 = json.loads((run / "final.json").read_text(encoding="utf-8"))
    det2 = [f for f in final2["findings"]
            if f["finding_id"] == det["finding_id"]][0]
    assert det2["skeptic"] is None                 # none of the three merged
    assert det2["disputed"] is False

    failures = common.read_jsonl(run / "validation_failures.jsonl")
    skeptic_failures = [f for f in failures if f["kind"] == "skeptic"]
    malformed = [f for f in skeptic_failures if "malformed-response" in f["errors"]]
    no_such = [f for f in skeptic_failures if "no-such-request" in f["errors"]]
    assert len(malformed) == 2       # bad_outcome + bad_reason_type
    assert len(no_such) == 1         # unknown_fid


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


def test_needs_structuring_row_matched_by_raw_text_counts_as_matched(tmp_path):
    """Re-review regression: a needs-structuring row whose raw text quotes a
    real rule id (T0) is matched via candidates.generate() before it is ever
    structured. It must be counted as matched in coverage (not folded into
    needs_structuring_unresolved), its rule must show as addressed
    (coverage.official agreeing with unaddressed_rules), it must not appear
    in unresolved_rows, and its finding must still be present -- previously
    the coverage-input filter excluded every needs-structuring row by status
    alone, producing self-contradictory fields in the same final.json."""
    fx = build_all(tmp_path / "fx")
    # Messy (unmappable) headers force needs-structuring; the row text
    # quotes V-1001 verbatim so T0 detection fires despite never being
    # structured.
    company_path = tmp_path / "company_v1001.docx"
    _write_docx(company_path, ["Area", "What we did", "How we checked", "Value"],
               [["High", "See V-1001 for details", "manual review", ""]])

    run_dir = tmp_path / "run"
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(company_path), "--run-dir", str(run_dir)])
    assert rc == 0
    state = common.read_jsonl(run_dir / "match_state.jsonl")
    assert len(state) == 1 and state[0]["tier"] == "T0"
    assert state[0]["matched_rule_id"] == "V-1001"
    row_id = state[0]["row_id"]
    rows = common.read_jsonl(run_dir / "company_rows.jsonl")
    assert rows[0]["status"] == "needs-structuring"     # never structured

    rc = pipeline.main(["resolve", "--run-dir", str(run_dir)])
    assert rc == 0
    findings = common.read_jsonl(run_dir / "findings.jsonl")
    assert any(f["row_id"] == row_id and f["rule_id"] == "V-1001"
              for f in findings)

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["company"]["matched"] == 1
    assert final["coverage"]["company"]["needs_structuring_unresolved"] == 0
    assert final["coverage"]["official"]["addressed"] == 1
    unaddressed_ids = {r["rule_id"] for r in final["unaddressed_rules"]}
    assert "V-1001" not in unaddressed_ids
    assert not any(r["row_id"] == row_id for r in final["unresolved_rows"])
    assert any(f["row_id"] == row_id for f in final["findings"])


def test_finalize_without_resolve_still_computes_deterministic_verdicts(run):
    """Important finding 1: `finalize` must never silently skip the
    deterministic-verdict pass for a matched row just because `resolve` was
    never called. Row 1 of company_docx is a T1 raw-text match to V-1001
    (assigned during `start`, before any Claude round-trip) -- calling
    `finalize --allow-pending` directly, with no `resolve` in between, must
    still produce V-1001's deterministic Compliant finding instead of
    silently leaving matched=1 with zero findings."""
    state = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    t1_rows = [rid for rid, m in state.items() if m["tier"] == "T1"
              and m.get("matched_rule_id") == "V-1001"]
    assert t1_rows                              # sanity: fixture still T1s row 1
    row_id = t1_rows[0]
    assert not state[row_id].get("verdict_done")    # never resolved

    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["company"]["matched"] >= 1

    matches = [f for f in final["findings"]
              if f["row_id"] == row_id and f["rule_id"] == "V-1001"]
    assert matches, "finalize without resolve must still emit V-1001's finding"
    f = matches[0]
    assert f["verdict"] == "Compliant"
    assert f["deterministic"] is True
    assert f["basis"] == "value-comparison"

    state2 = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state2[row_id]["verdict_done"] is True


# --------------------------------------------------------------------------
# Important finding 4: the structuring response path had zero committed
# tests. Cover both the verbatim-accepted and the paraphrase-rejected path.
# --------------------------------------------------------------------------

def test_structuring_response_verbatim_accepted_and_paraphrase_rejected(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(fx["company_docx_messy"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    struct_reqs = common.read_jsonl(run_dir / "structuring_requests.jsonl")
    assert len(struct_reqs) >= 2          # messy headers force structuring

    # row_a: the password-reuse row -- its raw text literally contains
    # "Run SHOW PARAMETER password_reuse_max", a verbatim substring.
    row_a = struct_reqs[0]
    verbatim_snippet = "Run SHOW PARAMETER password_reuse_max"
    assert verbatim_snippet in row_a["original_company_text"]
    resp_a = {"row_id": row_a["row_id"],
             "stig_command_or_value": verbatim_snippet}

    # row_b: answered with a paraphrase that is NOT a verbatim substring of
    # its original_company_text.
    row_b = struct_reqs[1]
    paraphrase = "This describes a sixty day password rotation policy, " \
                 "paraphrased and not quoted from the source text at all."
    assert paraphrase not in row_b["original_company_text"]
    resp_b = {"row_id": row_b["row_id"],
             "stig_command_or_value": paraphrase}

    common.write_jsonl(run_dir / "structuring_responses.jsonl", [resp_a, resp_b])
    rc = pipeline.main(["resolve", "--run-dir", str(run_dir)])
    assert rc == 0

    rows = {r["row_id"]: r for r in common.read_jsonl(run_dir / "company_rows.jsonl")}

    # (a) verbatim substring -> accepted: status "ok", field set, and the
    # row must have advanced past needs-structuring into either a fresh
    # matching request or a deterministic T0/T1 match.
    row_a_after = rows[row_a["row_id"]]
    assert row_a_after["status"] == "ok"
    assert row_a_after["stig_command_or_value"] == verbatim_snippet

    match_state = {m["row_id"]: m for m in common.read_jsonl(
        run_dir / "match_state.jsonl")}
    m_a = match_state[row_a["row_id"]]
    new_matching_requests = common.read_jsonl(run_dir / "matching_requests.jsonl")
    if m_a["tier"] in ("T0", "T1"):
        assert m_a["matched_rule_id"] is not None
    else:
        assert any(r["row_id"] == row_a["row_id"] for r in new_matching_requests), \
            "structured row must get a new matching request or a T0/T1 tier"

    # (b) paraphrase -> rejected: extraction-failed, notes explain why, and
    # a validation_failures.jsonl entry records a not-verbatim: code.
    row_b_after = rows[row_b["row_id"]]
    assert row_b_after["status"] == "extraction-failed"
    assert "structuring-rejected" in row_b_after["notes"]

    failures = common.read_jsonl(run_dir / "validation_failures.jsonl")
    b_failures = [f for f in failures if f["row_id"] == row_b["row_id"]]
    assert b_failures
    assert any(any(e.startswith("not-verbatim:") for e in f["errors"])
              for f in b_failures)


# --------------------------------------------------------------------------
# Minor finding 6: cmd_start must wrap its extract calls the same way
# extract.py's own CLI handler does -- a typed, content-free stderr message
# and exit code 2, never a raw traceback.
# --------------------------------------------------------------------------

def test_start_wraps_unreadable_official_file_as_typed_error(tmp_path, capsys):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    missing_official = tmp_path / "does-not-exist.csv"
    rc = pipeline.main(["start", "--official", str(missing_official),
                        "--company", str(fx["company_docx"]),
                        "--run-dir", str(run_dir)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "pipeline: cannot read file: FileNotFoundError" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_start_wraps_unreadable_company_file_as_typed_error(tmp_path, capsys):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    bad_company = tmp_path / "unsupported.txt"
    bad_company.write_text("not a real submission", encoding="utf-8")
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(bad_company),
                        "--run-dir", str(run_dir)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "pipeline: cannot read file: ValueError" in captured.err
    assert "not a real submission" not in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------
# Task 11: resolve's table-mapping and canonicalize passes
# --------------------------------------------------------------------------

def _mapping_answer(req, classification="stig_relevant", mapping=None,
                    reason=""):
    return {"table_index": req["table_index"],
            "classification": classification,
            "irrelevant_reason": reason,
            "column_mapping": mapping or {},
            "context_grouping": ""}


def _canon_answer(req):
    """Mechanical fake-Claude: apply the column mapping verbatim."""
    entries = []
    for row in req["rows"]:
        fields, prov = {}, {}
        empty = True
        for k, target in req["column_mapping"].items():
            i = int(k)
            if target in ("extra_field", "ignore"):
                continue
            val = row["cells"][i] if i < len(row["cells"]) else ""
            if val.strip():
                empty = False
                fields[target] = val
                prov[target] = {"row_index": row["row_index"],
                                "cell_index": i}
        if empty:
            entries.append({"row_index": row["row_index"],
                            "disposition": "separator",
                            "separator_text": ""})
        else:
            entries.append({"row_index": row["row_index"],
                            "disposition": "record",
                            "records": [{"sub_index": 0, "fields": fields,
                                         "field_provenance": prov,
                                         "interpretation_note": ""}]})
    return {"chunk_id": req["chunk_id"], "rows": entries}


EX1_MAPPING = {"0": "stig_objective_or_requirement", "1": "stig_description",
               "2": "stig_command_or_value",
               "3": "company_approved_setting_or_expected_value"}
EX2_MAPPING = {"0": "ignore", "1": "stig_command_or_value",
               "2": "stig_description", "3": "extra_field",
               "4": "extra_field", "5": "company_compliance_claim",
               "6": "company_approved_setting_or_expected_value",
               "7": "company_severity", "8": "observed_value_or_evidence",
               "9": "remarks_or_justification"}


def _answer_extraction(run_dir):
    """Answer table-mapping for the real fixture, resolve, then answer
    canonicalize chunks, resolve again. Tables 1-2 irrelevant."""
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    answers = []
    for r in reqs:
        if r["table_index"] == 1:
            answers.append(_mapping_answer(r, "irrelevant",
                                           reason="general-info"))
        elif r["table_index"] == 2:
            answers.append(_mapping_answer(r, "irrelevant",
                                           reason="instructions"))
        elif r["table_index"] == 3:
            answers.append(_mapping_answer(r, mapping=EX1_MAPPING))
        else:
            answers.append(_mapping_answer(r, mapping=EX2_MAPPING))
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    canon_reqs = common.read_jsonl(run_dir / "canonicalize_requests.jsonl")
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in canon_reqs])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_resolve_builds_canonical_records(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    records = common.read_jsonl(run_dir / "company_records.jsonl")
    assert len(records) == 4          # 2 EX1 rows + 2 EX2 rows
    ex2 = [r for r in records
           if r["source_reference"]["table_index"] == 4]
    dev = next(r for r in ex2 if r["claim_normalized"] == "deviation")
    assert dev["company_severity"] == "HIGH"
    assert dev["observed_value_or_evidence"] == "10"
    assert dev["extra_fields"]["REPORTING yes/no"] == "YES"

    tstate = {t["table_index"]: t
              for t in common.read_jsonl(run_dir / "table_state.jsonl")}
    assert tstate[1]["classification"] == "irrelevant"
    assert tstate[3]["row_dispositions"] == {"1": "record", "2": "record"}

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    assert len(match_state) == 4
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert all("record" in r and "candidates" in r for r in m_reqs)


def test_third_resolve_after_canonicalize_is_noop(tmp_path, fixture_paths):
    """Regression: once the canonicalize pass appends _matching_request-
    shaped entries (record_id, no row_id) to matching_requests.jsonl, a
    later status-check resolve with no new responses of any kind must not
    crash while building requested_ids from the mixed-shape file."""
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    # no new responses of any kind: a status-check resolve must not crash
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_mapping_two_strikes_marks_table_failed(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    bad = {"table_index": 1, "classification": "nonsense",
           "irrelevant_reason": "", "column_mapping": {},
           "context_grouping": ""}
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl", [bad])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    assert any(r.get("retry") for r in reqs if r["table_index"] == 1)
    with open(run_dir / "table_mapping_responses.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps(dict(bad, classification="still-bad")) + "\n")
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    tstate = {t["table_index"]: t
              for t in common.read_jsonl(run_dir / "table_state.jsonl")}
    assert tstate[1]["classification"] == "mapping-failed"


def test_build_table_records_separator_continuation_split():
    table = {"table_index": 1, "sheet_or_section": "document-body",
             "preceding_narrative": "", "header_row": ["A", "B"],
             "rows": [
                 {"row_index": 1, "cells": ["SECTION X", ""], "merged": True},
                 {"row_index": 2, "cells": ["timeout 15", "length 14"],
                  "merged": False},
                 {"row_index": 3, "cells": ["continued detail", ""],
                  "merged": True}]}
    ts = {"table_index": 1, "classification": "stig_relevant",
          "irrelevant_reason": "", "column_mapping": {"0": "stig_description"},
          "context_grouping": "Base", "mapping_failures": 0,
          "row_dispositions": {}, "parent_of": {},
          "chunks": {"T1-C0": {"row_indexes": [1, 2, 3], "done": True,
                               "failures": 0, "entries": [
              {"row_index": 1, "disposition": "separator",
               "separator_text": "SECTION X"},
              {"row_index": 2, "disposition": "record", "records": [
                  {"sub_index": 0,
                   "fields": {"stig_description": "timeout 15"},
                   "field_provenance": {"stig_description":
                                        {"row_index": 2, "cell_index": 0}},
                   "interpretation_note": ""},
                  {"sub_index": 1,
                   "fields": {"stig_description": "length 14"},
                   "field_provenance": {"stig_description":
                                        {"row_index": 2, "cell_index": 1}},
                   "interpretation_note": ""}]},
              {"row_index": 3, "disposition": "continuation"}]}}}
    records = pipeline._build_table_records(table, ts)
    assert len(records) == 2
    assert [r["source_reference"]["sub_index"] for r in records] == [0, 1]
    assert all(r["context_grouping"] == "Base | SECTION X" for r in records)
    assert records[0]["record_id"] != records[1]["record_id"]
    assert records[0]["row_id"] == records[1]["row_id"]
    assert ts["parent_of"] == {"3": 2}
    assert ts["row_dispositions"] == {"1": "separator", "2": "record",
                                      "3": "continuation"}
