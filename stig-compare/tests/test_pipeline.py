import json
from pathlib import Path

import pytest

import pipeline
import helpers
from fixtures import build_fixtures
from helpers import (answer_structure, answer_mapping, answer_interpretation,
                     answer_scoping, answer_adjudication, answer_sweep,
                     answer_comparison, answer_rollup, answer_validation,
                     read_jsonl, write_responses, append_response, run,
                     title_of)


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build_fixtures.build_all(tmp_path_factory.mktemp("fx"))


def _start(fx, rd, company="company_docx", official="official_csv"):
    run(["start", "--official", str(fx[official]), "--company",
         str(fx[company]), "--run-dir", str(rd)])


def _resolve(rd):
    run(["resolve", "--run-dir", str(rd)])


def _row_for(rd, display_id):
    for r in read_jsonl(Path(rd) / "official_rows.jsonl"):
        if r["raw_record"].get("Rule ID") == display_id:
            return r
    raise AssertionError(f"no official row {display_id}")


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def test_start_artifacts(fx, tmp_path):
    _start(fx, tmp_path)
    rows = read_jsonl(tmp_path / "official_rows.jsonl")
    assert len(rows) == 5
    assert all(r["raw_record"] and r["cells"] and r["headers"] for r in rows)
    structure = read_jsonl(tmp_path / "official_structure_requests.jsonl")
    assert len(structure) == 1
    assert structure[0]["headers"][0] == "Rule ID"
    mapping = read_jsonl(tmp_path / "table_mapping_requests.jsonl")
    assert mapping[0]["row_count"] == 4
    assert "total_bytes" in mapping[0]
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert "registry_version" not in manifest
    assert "rule_conflicts" not in manifest


def test_start_unreadable_exits_2(fx, tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_text("not a docx", encoding="utf-8")
    code = pipeline.main(["start", "--official", str(fx["official_csv"]),
                          "--company", str(bad),
                          "--run-dir", str(tmp_path / "r")])
    assert code == 2


# --------------------------------------------------------------------------
# structure pass applies annotations
# --------------------------------------------------------------------------

def test_structure_annotations_applied(fx, tmp_path):
    _start(fx, tmp_path)
    answer_structure(tmp_path)
    answer_mapping(tmp_path)
    _resolve(tmp_path)
    rows = read_jsonl(tmp_path / "official_rows.jsonl")
    assert all(r["display_id"] == r["raw_record"]["Rule ID"] for r in rows)
    assert all(r["column_roles"]["Title"] == "title" for r in rows)


def test_duplicate_display_ids_warned(fx, tmp_path):
    _start(fx, tmp_path, official="official_dup_ids_csv")
    answer_structure(tmp_path)
    answer_mapping(tmp_path)
    _resolve(tmp_path)
    warnings = read_jsonl(tmp_path / "run_warnings.jsonl")
    assert any(w["code"] == "duplicate-display-id" and "V-2001" in w["detail"]
               for w in warnings)


# --------------------------------------------------------------------------
# two-strike protocol + retry echo
# --------------------------------------------------------------------------

def test_mapping_two_strikes_and_retry_echo(fx, tmp_path):
    _start(fx, tmp_path)
    answer_structure(tmp_path)
    # Strike 1: bad classification.
    req = read_jsonl(tmp_path / "table_mapping_requests.jsonl")[0]
    write_responses(tmp_path, "table_mapping_responses.jsonl", [
        {"table_index": req["table_index"], "classification": "nonsense",
         "irrelevant_reason": "other", "column_mapping": {},
         "context_grouping": ""}])
    _resolve(tmp_path)
    reqs = read_jsonl(tmp_path / "table_mapping_requests.jsonl")
    assert reqs[-1].get("retry") is True
    assert reqs[-1].get("previous_errors")
    # Strike 2: valid-looking answer but WITHOUT the required retry echo
    # -> rejected -> settled as mapping-failed.
    append_response(tmp_path, "table_mapping_responses.jsonl",
                    {"table_index": req["table_index"],
                     "classification": "stig_relevant",
                     "irrelevant_reason": "other", "column_mapping": {},
                     "context_grouping": ""})
    _resolve(tmp_path)
    ts = read_jsonl(tmp_path / "table_state.jsonl")[0]
    assert ts["classification"] == "mapping-failed"
    failures = read_jsonl(tmp_path / "validation_failures.jsonl")
    assert any("retry-echo-mismatch" in f["errors"] for f in failures)


def test_malformed_response_line_tolerated(fx, tmp_path):
    _start(fx, tmp_path)
    (tmp_path / "table_mapping_responses.jsonl").write_text(
        "{not json\n", encoding="utf-8")
    _resolve(tmp_path)
    failures = read_jsonl(tmp_path / "validation_failures.jsonl")
    assert any("malformed-json" in f["errors"] for f in failures)


# --------------------------------------------------------------------------
# scoping -> adjudication
# --------------------------------------------------------------------------

def _to_adjudication(fx, rd, nominate=None, company="company_docx"):
    _start(fx, rd, company=company)
    answer_structure(rd)
    answer_mapping(rd)
    _resolve(rd)
    answer_interpretation(rd)
    _resolve(rd)
    answer_scoping(rd, nominate=nominate)
    _resolve(rd)


def test_no_nominations_is_llm_none(fx, tmp_path):
    _to_adjudication(fx, tmp_path, nominate=lambda rec, rows: [])
    match_state = read_jsonl(tmp_path / "match_state.jsonl")
    assert match_state
    assert all(m["decision"] == "none" and m["basis"] == "no-nominations"
               for m in match_state)
    assert not (tmp_path / "adjudication_requests.jsonl").exists() or \
        read_jsonl(tmp_path / "adjudication_requests.jsonl") == []


def test_nominations_union_across_chunks_reaches_adjudication(fx, tmp_path):
    _to_adjudication(fx, tmp_path)
    reqs = read_jsonl(tmp_path / "adjudication_requests.jsonl")
    assert len(reqs) == 1                     # only the V-1001 row matches
    assert reqs[0]["nominated_rows"][0]["raw_record"]["Rule ID"] == "V-1001"
    assert reqs[0]["sweep_round"] is False


def test_adjudication_two_strikes_settles_unresolved(fx, tmp_path):
    _to_adjudication(fx, tmp_path)
    req = read_jsonl(tmp_path / "adjudication_requests.jsonl")[0]
    bad = {"record_id": req["record_id"], "decision": "match",
           "selections": [{"official_row_id": "OR-nope",
                           "row_quote": "x", "official_quote": "y"}],
           "ambiguous_official_row_ids": [], "basis": ""}
    write_responses(tmp_path, "adjudication_responses.jsonl", [bad])
    _resolve(tmp_path)
    bad2 = dict(bad, retry=True)
    write_responses(tmp_path, "adjudication_responses.jsonl", [bad2])
    _resolve(tmp_path)
    m = next(m for m in read_jsonl(tmp_path / "match_state.jsonl")
             if m["record_id"] == req["record_id"])
    assert m["decision"] == "unresolved-llm-output-rejected"
    assert "llm-output-rejected" in m["warnings"]


def test_ambiguous_decision_recorded(fx, tmp_path):
    def nominate(rec, rows):
        if "password reuse" in helpers.record_text(rec).lower():
            return [r["official_row_id"] for r in rows
                    if r["raw_record"].get("Rule ID") in ("V-1001", "V-1002")]
        return []
    _to_adjudication(fx, tmp_path, nominate=nominate)
    req = read_jsonl(tmp_path / "adjudication_requests.jsonl")[0]
    ids = [r["official_row_id"] for r in req["nominated_rows"]]
    write_responses(tmp_path, "adjudication_responses.jsonl", [
        {"record_id": req["record_id"], "decision": "ambiguous",
         "selections": [], "ambiguous_official_row_ids": ids,
         "basis": "cannot discriminate"}])
    _resolve(tmp_path)
    m = next(m for m in read_jsonl(tmp_path / "match_state.jsonl")
             if m["record_id"] == req["record_id"])
    assert m["decision"] == "ambiguous"
    assert sorted(m["ambiguous_official_row_ids"]) == sorted(ids)


# --------------------------------------------------------------------------
# sweep
# --------------------------------------------------------------------------

def _settled_run(fx, rd):
    _to_adjudication(fx, rd)
    answer_adjudication(rd)
    _resolve(rd)


def test_sweep_not_ready_before_adjudication(fx, tmp_path):
    _to_adjudication(fx, tmp_path)
    code = pipeline.main(["sweep", "--run-dir", str(tmp_path)])
    assert code == 4


def test_sweep_proposal_reopens_with_echo_enforced(fx, tmp_path):
    _settled_run(fx, tmp_path)
    run(["sweep", "--run-dir", str(tmp_path)])
    sweep_reqs = read_jsonl(tmp_path / "sweep_requests.jsonl")
    assert sweep_reqs
    assert all(r["official_rows"][0]["raw_record"] for r in sweep_reqs)
    target = _row_for(tmp_path, "V-1002")
    unmatched = [m["record_id"] for m in
                 read_jsonl(tmp_path / "match_state.jsonl")
                 if m["decision"] == "none"]

    def propose(req):
        rids = [r["record_id"] for r in req["records"]
                if r["record_id"] in unmatched]
        oids = [r["official_row_id"] for r in req["official_rows"]
                if r["official_row_id"] == target["official_row_id"]]
        return [{"record_id": rid, "official_row_id": oid}
                for rid in rids[:1] for oid in oids]

    answer_sweep(tmp_path, propose=propose)
    _resolve(tmp_path)
    sweep_adj = [r for r in
                 read_jsonl(tmp_path / "adjudication_requests.jsonl")
                 if r.get("sweep_round")]
    assert sweep_adj
    req = sweep_adj[-1]
    # Answering WITHOUT the sweep_round echo is rejected.
    good = {"record_id": req["record_id"], "decision": "match",
            "selections": [{"official_row_id": target["official_row_id"],
                            "row_quote": req["record"]["cells"][1],
                            "official_quote": title_of(target)}],
            "ambiguous_official_row_ids": [], "basis": "sweep match"}
    write_responses(tmp_path, "adjudication_responses.jsonl", [good])
    _resolve(tmp_path)
    failures = read_jsonl(tmp_path / "validation_failures.jsonl")
    assert any("sweep-round-echo-mismatch" in f["errors"] for f in failures)
    # With the echo (and retry echo for strike 2) it is accepted.
    good2 = dict(good, sweep_round=True, retry=True)
    write_responses(tmp_path, "adjudication_responses.jsonl", [good2])
    _resolve(tmp_path)
    m = next(m for m in read_jsonl(tmp_path / "match_state.jsonl")
             if m["record_id"] == req["record_id"])
    assert m["decision"] == "match"
    assert target["official_row_id"] in m["sweep_origin_row_ids"]
    # The comparison for the sweep-originated match was emitted.
    cmps = read_jsonl(tmp_path / "comparison_requests.jsonl")
    assert any(c["record_id"] == req["record_id"] for c in cmps)


# --------------------------------------------------------------------------
# comparison -> findings
# --------------------------------------------------------------------------

def test_comparison_builds_findings_with_full_payloads(fx, tmp_path):
    _settled_run(fx, tmp_path)
    answer_comparison(tmp_path)
    _resolve(tmp_path)
    findings = read_jsonl(tmp_path / "findings.jsonl")
    assert len(findings) == 1
    f = findings[0]
    assert f["verdict"] == "Compliant"
    assert f["verdict_source"] == "comparison"
    assert f["company_row"]["cells"]
    assert f["official_row"]["raw_record"]
    assert f["display_id"] == "V-1001"
    assert f["claim_reading"] == "none"
    assert f["match_basis"]["basis"] == "title equality"


def test_comparison_two_strikes_lands_in_unresolved_pairs(fx, tmp_path):
    _settled_run(fx, tmp_path)
    req = read_jsonl(tmp_path / "comparison_requests.jsonl")[0]
    bad = {"comparison_id": req["comparison_id"],
           "record_id": req["record_id"], "per_rule": [],
           "claim_consistency": "no-claim", "record_notes": ""}
    write_responses(tmp_path, "comparison_responses.jsonl", [bad])
    _resolve(tmp_path)
    write_responses(tmp_path, "comparison_responses.jsonl",
                    [dict(bad, retry=True)])
    _resolve(tmp_path)
    run(["sweep", "--run-dir", str(tmp_path)])
    answer_sweep(tmp_path)
    _resolve(tmp_path)
    run(["rollup", "--run-dir", str(tmp_path)])
    code = pipeline.main(["finalize", "--run-dir", str(tmp_path),
                          "--no-report"])
    assert code == 0          # no findings -> no validations pending
    final = json.loads((tmp_path / "final.json").read_text("utf-8"))
    assert final["findings"] == []
    assert len(final["unresolved_pairs"]) == 1
    assert final["unresolved_pairs"][0]["status"] == \
        "comparison-unresolved/llm-output-rejected"


# --------------------------------------------------------------------------
# rollup (1:N)
# --------------------------------------------------------------------------

def _password_nominate(rec, rows):
    if "password" in helpers.record_text(rec).lower():
        return [r["official_row_id"] for r in rows
                if r["raw_record"].get("Rule ID") == "V-1001"]
    return []


def _first_cell_decide(req):
    sels = [{"official_row_id": row["official_row_id"],
             "row_quote": next(c for c in req["record"]["cells"]
                               if c.strip()),
             "official_quote": title_of(row)}
            for row in req["nominated_rows"]]
    return {"record_id": req["record_id"], "decision": "match",
            "selections": sels, "ambiguous_official_row_ids": [],
            "basis": "stub"}


def _rollup_ready(fx, rd):
    _to_adjudication(fx, rd, nominate=_password_nominate)
    answer_adjudication(rd, decide=_first_cell_decide)
    _resolve(rd)
    answer_comparison(rd)
    _resolve(rd)
    run(["sweep", "--run-dir", str(rd)])
    answer_sweep(rd)
    _resolve(rd)


def test_rollup_groups_multi_matched_rows(fx, tmp_path):
    _rollup_ready(fx, tmp_path)
    run(["rollup", "--run-dir", str(tmp_path)])
    reqs = read_jsonl(tmp_path / "rollup_requests.jsonl")
    assert len(reqs) == 1
    assert len(reqs[0]["company_records"]) == 2
    assert len(reqs[0]["per_record_findings"]) == 2
    assert reqs[0]["official_row"]["raw_record"]["Rule ID"] == "V-1001"


def test_rollup_disagreement_warns_and_flags(fx, tmp_path):
    _rollup_ready(fx, tmp_path)
    run(["rollup", "--run-dir", str(tmp_path)])
    answer_rollup(tmp_path, joint_verdict="Deviating")
    _resolve(tmp_path)
    code = pipeline.main(["finalize", "--run-dir", str(tmp_path),
                          "--no-report"])
    assert code == 4
    answer_validation(tmp_path)
    _resolve(tmp_path)
    run(["finalize", "--run-dir", str(tmp_path), "--no-report"])
    final = json.loads((tmp_path / "final.json").read_text("utf-8"))
    assert len(final["rule_rollups"]) == 1
    ru = final["rule_rollups"][0]
    assert ru["verdict"] == "Deviating"
    assert "rollup-verdict-differs" in ru["review_reasons"]
    assert any(w["code"] == "rollup-verdict-differs"
               for w in final["warnings"])
    assert all("rollup-verdict-differs" in f["review_reasons"]
               for f in final["findings"])
    assert final["coverage"]["official"]["multi_matched_row_ids"]


def test_rollup_not_ready_before_comparisons(fx, tmp_path):
    _to_adjudication(fx, tmp_path, nominate=_password_nominate)
    answer_adjudication(tmp_path, decide=_first_cell_decide)
    _resolve(tmp_path)
    run(["sweep", "--run-dir", str(tmp_path)])
    code = pipeline.main(["rollup", "--run-dir", str(tmp_path)])
    assert code == 4


# --------------------------------------------------------------------------
# validation merge
# --------------------------------------------------------------------------

def _validated_run(fx, rd, mutate):
    _settled_run(fx, rd)
    answer_comparison(rd)
    _resolve(rd)
    run(["sweep", "--run-dir", str(rd)])
    answer_sweep(rd)
    _resolve(rd)
    run(["rollup", "--run-dir", str(rd)])
    code = pipeline.main(["finalize", "--run-dir", str(rd), "--no-report"])
    assert code == 4
    answer_validation(rd, mutate=mutate)
    _resolve(rd)
    run(["finalize", "--run-dir", str(rd), "--no-report"])
    return json.loads((Path(rd) / "final.json").read_text("utf-8"))


def test_validation_revised_swaps_verdict(fx, tmp_path):
    def mutate(req, a):
        a["outcome"] = "revised"
        a["independent_verdict"] = "Deviating"
        a["revised_verdict"] = "Deviating"
        a["reason"] = "evidence points the other way"
        return a
    final = _validated_run(fx, tmp_path, mutate)
    f = final["findings"][0]
    assert f["verdict"] == "Deviating"
    assert f["first_pass_verdict"] == "Compliant"
    assert f["verdict_source"] == "validation-revised"
    assert "validation-revised" in f["review_reasons"]
    assert f["human_review_needed"] is True


def test_validation_refuted_marks_disputed(fx, tmp_path):
    def mutate(req, a):
        a["outcome"] = "refuted"
        a["independent_verdict"] = "Cannot Assess"
        a["reason"] = "quote does not support the verdict"
        return a
    final = _validated_run(fx, tmp_path, mutate)
    f = final["findings"][0]
    assert f["disputed"] is True
    assert f["verdict"] == "Compliant"        # verdict stays, shown disputed
    assert "validation-refuted" in f["review_reasons"]


def test_uphold_contradiction_gets_retry(fx, tmp_path):
    _settled_run(fx, tmp_path)
    answer_comparison(tmp_path)
    _resolve(tmp_path)
    run(["sweep", "--run-dir", str(tmp_path)])
    answer_sweep(tmp_path)
    _resolve(tmp_path)
    run(["rollup", "--run-dir", str(tmp_path)])
    assert pipeline.main(["finalize", "--run-dir", str(tmp_path),
                          "--no-report"]) == 4

    def mutate(req, a):
        a["independent_verdict"] = "Deviating"   # contradicts upheld claim
        return a
    answer_validation(tmp_path, mutate=mutate)
    _resolve(tmp_path)
    failures = read_jsonl(tmp_path / "validation_failures.jsonl")
    assert any("uphold-contradicts-own-verdict" in f["errors"]
               for f in failures)
    reqs = read_jsonl(tmp_path / "validation_requests.jsonl")
    assert reqs[-1].get("retry") is True


# --------------------------------------------------------------------------
# idempotency + allow-pending
# --------------------------------------------------------------------------

def test_resolve_replay_is_noop(fx, tmp_path):
    _settled_run(fx, tmp_path)
    answer_comparison(tmp_path)
    _resolve(tmp_path)
    state1 = (tmp_path / "match_state.jsonl").read_text("utf-8")
    consumed1 = (tmp_path / "consumed_responses.json").read_text("utf-8")
    _resolve(tmp_path)
    assert (tmp_path / "match_state.jsonl").read_text("utf-8") == state1
    assert (tmp_path / "consumed_responses.json").read_text("utf-8") == \
        consumed1
    assert len(read_jsonl(tmp_path / "findings.jsonl")) == 1


def test_finalize_refuses_pending_then_allow_pending_marks(fx, tmp_path):
    _to_adjudication(fx, tmp_path)
    code = pipeline.main(["finalize", "--run-dir", str(tmp_path),
                          "--no-report"])
    assert code == 4
    run(["finalize", "--run-dir", str(tmp_path), "--no-report",
         "--allow-pending"])
    final = json.loads((tmp_path / "final.json").read_text("utf-8"))
    assert final["coverage"]["company"]["unresolved"] >= 1
    unresolved = [r for r in final["unresolved_rows"]
                  if r["status"] == "match-pass-not-run"]
    assert unresolved
    match_state = read_jsonl(tmp_path / "match_state.jsonl")
    pending = [m for m in match_state if m["decision"] is None]
    assert all("adjudication-pass-not-run" in m["warnings"]
               for m in pending if m["adjudication_emitted"])
