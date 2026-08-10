import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all, _write_docx, _write_official_csv
import common
import pipeline


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


# --------------------------------------------------------------------------
# Task 12: multi-select matching pass and per-pair deterministic verdicts
# --------------------------------------------------------------------------

def _match_answer(req, rule_ids):
    if not rule_ids:
        return {"record_id": req["record_id"], "decision": "none",
                "selections": [], "ambiguous_rule_ids": [], "basis": "none"}
    sels = []
    for rid in rule_ids:
        rule = next(c for c in req["candidates"] if c["rule_id"] == rid)
        sels.append({"rule_id": rid,
                     "row_quote": req["record"]["original_company_text"]
                     .split(" | ")[0],
                     "rule_quote": rule["title"]})
    return {"record_id": req["record_id"], "decision": "match",
            "selections": sels, "ambiguous_rule_ids": [], "basis": "content"}


def test_multi_select_match_produces_pair_findings(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = []
    for req in m_reqs:
        # NOTE: the fixture's "password reuse" row is auto-tiered to T1 by
        # candidates.generate()'s technical-token uniqueness check (its raw
        # text uniquely overlaps V-1001's "password_reuse_max"/"PARAMETER"
        # tokens) before it ever reaches a matching request, so it can never
        # be the row this test picks 2 selections for. Any record that
        # reaches this pass with >= 2 shortlisted candidates works just as
        # well to exercise multi-select.
        cand_ids = [c["rule_id"] for c in req["candidates"]]
        picks = cand_ids[:2] if len(cand_ids) >= 2 else cand_ids[:1]
        answers.append(_match_answer(req, picks))
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    multi = [m for m in match_state if len(m["matched_rule_ids"]) == 2]
    assert multi, "expected at least one two-rule match"
    findings = common.read_jsonl(run_dir / "findings.jsonl")
    sem_reqs = (common.read_jsonl(run_dir / "semantic_requests.jsonl")
                if (run_dir / "semantic_requests.jsonl").exists() else [])
    m0 = multi[0]
    covered = {f["rule_id"] for f in findings
               if f["record_id"] == m0["record_id"]} | \
              {r["rule_id"] for r in sem_reqs
               if r["record_id"] == m0["record_id"]}
    assert covered == set(m0["matched_rule_ids"])
    for f in findings:
        assert "record_id" in f and "row_id" in f


# --------------------------------------------------------------------------
# Task 13: sweep command and sweep-response processing
# --------------------------------------------------------------------------

def _finish_matching_as_none(run_dir):
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = [_match_answer(r, []) for r in m_reqs]
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_sweep_generates_requests_then_injects(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    _finish_matching_as_none(run_dir)

    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    s_reqs = common.read_jsonl(run_dir / "sweep_requests.jsonl")
    assert s_reqs and s_reqs[0]["sweep_id"] == "S0"
    assert all(len(b["records"]) <= 20 for b in s_reqs)
    assert {"rule_id", "title", "expected_value", "tech_tokens"} <= \
        set(s_reqs[0]["rules_index"][0])

    # second invocation is a no-op
    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    assert common.read_jsonl(run_dir / "sweep_requests.jsonl") == s_reqs

    batch = s_reqs[0]
    rec_id = batch["records"][0]["record_id"]
    rule_id = batch["rules_index"][0]["rule_id"]
    common.write_jsonl(run_dir / "sweep_responses.jsonl",
                       [{"sweep_id": batch["sweep_id"],
                         "proposals": [{"record_id": rec_id,
                                        "rule_id": rule_id}]}])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    state = {m["record_id"]: m
             for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    m = state[rec_id]
    assert m["tier"] is None
    assert rule_id in m["sweep_origin_rule_ids"]
    assert any(c["rule_id"] == rule_id for c in m["candidates"])
    reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert any(r.get("sweep_round") and r["record_id"] == rec_id
               for r in reqs)


# --------------------------------------------------------------------------
# Task 14: cmd_finalize rewrite -- per-pair semantic, claim flags,
# confidence, coverage, triage
# --------------------------------------------------------------------------

def _full_run(tmp_path, fixture_paths, match_picks=1):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = [_match_answer(r, [c["rule_id"]
                                 for c in r["candidates"]][:match_picks])
               for r in m_reqs]
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    return run_dir


def test_finalize_claim_flags_and_triage(tmp_path, fixture_paths):
    run_dir = _full_run(tmp_path, fixture_paths)
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))

    triage = {t["table_index"]: t for t in final["table_triage"]}
    assert triage[1]["classification"] == "irrelevant"
    assert triage[4]["classification"] == "stig_relevant"

    cov = final["coverage"]["company"]
    assert cov["ignored_irrelevant_table"] == 4   # 2 general-info + 2 instructions rows
    assert cov["total"] == 8

    dev_findings = [f for f in final["findings"]
                    if f["claim_normalized"] == "deviation"]
    assert dev_findings
    for f in dev_findings:
        assert "company-declared-deviation" in f["claim_flags"]
        assert f["human_review_needed"] is True

    comply_bad = [f for f in final["findings"]
                  if f["claim_normalized"] == "comply"
                  and f["verdict"] == "Non-Compliant"]
    for f in comply_bad:
        assert "claim-contradicted" in f["claim_flags"]


def test_finalize_refuses_on_pending_extraction(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report"])
    assert rc == 4


def test_sweep_originated_findings_capped_medium(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    _finish_matching_as_none(run_dir)
    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    s_reqs = common.read_jsonl(run_dir / "sweep_requests.jsonl")
    batch = s_reqs[0]
    rec = batch["records"][0]
    rule_id = batch["rules_index"][0]["rule_id"]
    common.write_jsonl(run_dir / "sweep_responses.jsonl",
                       [{"sweep_id": batch["sweep_id"],
                         "proposals": [{"record_id": rec["record_id"],
                                        "rule_id": rule_id}]}])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    m_reqs = [r for r in
              common.read_jsonl(run_dir / "matching_requests.jsonl")
              if r.get("sweep_round")]
    answers = [_match_answer(r, [rule_id]) for r in m_reqs
               if r["record_id"] == rec["record_id"]]
    with open(run_dir / "matching_responses.jsonl", "a",
              encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    swept = [f for f in final["findings"] if f["sweep_originated"]]
    assert swept
    for f in swept:
        assert f["confidence"] in ("Medium", "Low")
        assert f["human_review_needed"] is True


# --------------------------------------------------------------------------
# Task 14 review, Finding 1: --allow-pending mutation paths (mapping,
# canonicalize, matching) had zero test exercise.
# --------------------------------------------------------------------------

def _answer_extraction_partial(run_dir, skip_tables=()):
    """Like _answer_extraction, but leaves `skip_tables` table-mapping
    requests unanswered (so their table_state classification stays None)."""
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    answers = []
    for r in reqs:
        if r["table_index"] in skip_tables:
            continue
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


def test_finalize_allow_pending_marks_unmapped_table(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction_partial(run_dir, skip_tables={1})

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 4

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0

    tstate = {t["table_index"]: t
             for t in common.read_jsonl(run_dir / "table_state.jsonl")}
    assert tstate[1]["classification"] == "mapping-pass-not-run"

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    triage = {t["table_index"]: t for t in final["table_triage"]}
    assert triage[1]["classification"] == "mapping-pass-not-run"
    assert final["coverage"]["company"]["extraction_failed"] == 2  # table 1's 2 rows
    assert any(w.get("code") == "mapping-failed" and w.get("detail") == "table=1"
               for w in final["warnings"])


def _answer_extraction_skip_chunk(run_dir, skip_chunk_table_index):
    """Like _answer_extraction, but answers every table-mapping request and
    then leaves `skip_chunk_table_index`'s canonicalize chunk(s) unanswered."""
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
    keep = [r for r in canon_reqs
           if r["table_index"] != skip_chunk_table_index]
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in keep])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_finalize_allow_pending_marks_unanswered_chunk(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction_skip_chunk(run_dir, skip_chunk_table_index=4)

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 4

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    t4_unresolved = [r for r in final["unresolved_rows"]
                     if r["source_reference"].get("table_index") == 4]
    assert len(t4_unresolved) == 2                     # EX2 has 2 rows
    for r in t4_unresolved:
        assert r["status"] == "extraction-failed"
        assert "canonicalize-pass-not-run" in r["notes"]


def test_finalize_allow_pending_marks_unanswered_matching(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    # matching_requests.jsonl exists but is never answered

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 4

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    requested_ids = {r["record_id"] for r in m_reqs}
    assert requested_ids
    match_state = {m["record_id"]: m
                   for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    pending = [match_state[rid] for rid in requested_ids]
    for m in pending:
        assert m["tier"] == "T4"
        assert "matching-pass-not-run" in m["warnings"]

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["company"]["unmatched"] >= len(pending)


# --------------------------------------------------------------------------
# Task 14 review, Finding 2: regression coverage rebuilt (against the new
# record_id/two-phase-extraction flow) for six behaviors that lost coverage
# when the 15 old-shape tests were deleted.
# --------------------------------------------------------------------------

def test_second_strike_matching_forces_t4(tmp_path, fixture_paths):
    """(1) Two genuinely different invalid matching responses for the same
    record -> tier T4, warning llm-output-rejected, 2 matching validation
    failures, no finding."""
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert m_reqs
    req = m_reqs[0]

    bad1 = {"record_id": req["record_id"], "decision": "match",
            "selections": [{"rule_id": "V-9999", "row_quote": "x",
                            "rule_quote": "y"}],
            "ambiguous_rule_ids": [], "basis": "invented-1"}
    common.write_jsonl(run_dir / "matching_responses.jsonl", [bad1])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    retry_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert any(r.get("retry") and r["record_id"] == req["record_id"]
              for r in retry_reqs)
    state = {m["record_id"]: m
             for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    assert state[req["record_id"]]["tier"] is None
    assert state[req["record_id"]]["match_failures"] == 1

    bad2 = {"record_id": req["record_id"], "decision": "match",
            "selections": [{"rule_id": "V-8888", "row_quote": "x",
                            "rule_quote": "y"}],
            "ambiguous_rule_ids": [], "basis": "invented-2"}
    common.write_jsonl(run_dir / "matching_responses.jsonl", [bad2])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    state2 = {m["record_id"]: m
             for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    m = state2[req["record_id"]]
    assert m["tier"] == "T4"
    assert "llm-output-rejected" in m["warnings"]
    findings = common.read_jsonl(run_dir / "findings.jsonl")
    assert not any(f["record_id"] == req["record_id"] for f in findings)

    failures = common.read_jsonl(run_dir / "validation_failures.jsonl")
    matching_failures = [f for f in failures if f["kind"] == "matching"
                         and f["row_id"] == req["record_id"]]
    assert len(matching_failures) == 2


def test_margin_flag_downgrades_to_t3(tmp_path):
    """(2) Two official rules with byte-identical distinctive text score
    exactly tied, so candidates.generate() sets margin_flag; when Claude
    accepts one of them with a rule_quote that is also verbatim in the
    runner-up's text, resolve downgrades T2 -> T3 instead of trusting the
    single selection."""
    shared = {"title": "Widget frobnicator level must be configured",
             "severity": "medium",
             "check_text": "Verify the widget_frobnicator_level parameter is set",
             "fix_text": "Set widget_frobnicator_level to 5",
             "expected_value": "5"}
    rules = [dict(shared, rule_id="V-9001"), dict(shared, rule_id="V-9002")]
    official_path = tmp_path / "official_margin.csv"
    _write_official_csv(official_path, rules)

    headers = ["STIG REQUIREMENT", "DESCRIPTION", "COMMAND TO VERIFY",
              "APPROVED SETTING"]
    rows = [["Widget config", "Widget must be configured per policy",
            "Verify the widget_frobnicator_level parameter is set", "5"]]
    company_path = tmp_path / "company_margin.docx"
    _write_docx(company_path, headers, rows)

    run_dir = tmp_path / "run"
    assert pipeline.main(["start", "--official", str(official_path),
                          "--company", str(company_path),
                          "--run-dir", str(run_dir)]) == 0

    mreqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    mapping = {"0": "stig_objective_or_requirement", "1": "stig_description",
              "2": "stig_command_or_value",
              "3": "company_approved_setting_or_expected_value"}
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl",
                       [_mapping_answer(mreqs[0], mapping=mapping)])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    canon_reqs = common.read_jsonl(run_dir / "canonicalize_requests.jsonl")
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in canon_reqs])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    assert len(match_state) == 1
    m = match_state[0]
    assert m["tier"] is None
    assert m["margin_flag"] is True
    assert {c["rule_id"] for c in m["candidates"]} == {"V-9001", "V-9002"}

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    req = m_reqs[0]
    chosen_id = m["candidates"][0]["rule_id"]
    shared_quote = "Verify the widget_frobnicator_level parameter is set"
    resp = {"record_id": req["record_id"], "decision": "match",
            "selections": [{
                "rule_id": chosen_id,
                "row_quote":
                    req["record"]["original_company_text"].split(" | ")[0],
                "rule_quote": shared_quote}],
            "ambiguous_rule_ids": [], "basis": "shared text"}
    common.write_jsonl(run_dir / "matching_responses.jsonl", [resp])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    state2 = {m2["record_id"]: m2
             for m2 in common.read_jsonl(run_dir / "match_state.jsonl")}
    m2 = state2[req["record_id"]]
    assert m2["tier"] == "T3"
    assert set(m2["ambiguous_rule_ids"]) == {"V-9001", "V-9002"}


def test_rule_equivalence_and_missing_evidence_guard(tmp_path, fixture_paths,
                                                      monkeypatch):
    """(3) An injected equivalent-terminology rule produces a Compliant /
    rule-equivalence finding with the rule id recorded in applied_rules when
    there is evidence -- but every EX1 record (no observed-value column
    mapped at all) still lands on Cannot Assess / missing-evidence, proving
    the equivalence shortcut is never consulted when evidence is empty."""
    fake_registry = {"registry_version": 1, "rules": [
        {"rule_id": "EQ-1", "category": "equivalent-terminology",
         "status": "active", "scope": {"level": "global"},
         "payload": {"a": "10", "b": "14 or more"}}]}
    monkeypatch.setattr(pipeline.rules_mod, "load_registry",
                        lambda path: fake_registry)

    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = []
    minlen_record_id = None
    for req in m_reqs:
        if "Minimum password length" in req["record"]["original_company_text"]:
            minlen_record_id = req["record_id"]
            answers.append(_match_answer(req, ["V-1005"]))
        else:
            cand_ids = [c["rule_id"] for c in req["candidates"]]
            answers.append(_match_answer(req, cand_ids[:1]))
    assert minlen_record_id is not None
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    findings = common.read_jsonl(run_dir / "findings.jsonl")
    eq_finding = [f for f in findings if f["record_id"] == minlen_record_id
                 and f["rule_id"] == "V-1005"][0]
    assert eq_finding["verdict"] == "Compliant"
    assert eq_finding["basis"] == "rule-equivalence"
    assert eq_finding["applied_rules"] == ["EQ-1"]

    ex1_findings = [f for f in findings
                   if f["company_row"]["source_reference"].get("table_index") == 3]
    assert ex1_findings
    for f in ex1_findings:
        assert f["verdict"] == "Cannot Assess"
        assert f["basis"] == "missing-evidence"
        assert f["applied_rules"] == []


def test_skeptic_merge_disputes_finding_and_records_bad_responses(tmp_path):
    """(4) A semantic (non-deterministic) finding refuted by the skeptic is
    marked disputed with human_review_needed True; a malformed-outcome line
    and an unknown finding_id in the same skeptic_responses.jsonl batch are
    each recorded as their own "skeptic" validation failure instead of
    silently merging or crashing."""
    official_path = tmp_path / "official_skeptic.csv"
    _write_official_csv(official_path, [
        {"rule_id": "V-7001", "title": "Audit logging must be enabled",
         "severity": "high",
         "check_text": "Verify audit logging is enabled for all systems",
         "fix_text": "Enable audit logging", "expected_value": "enabled"}])
    headers = ["Requirement", "Description", "Command", "Approved Setting",
              "Observed"]
    rows = [["Audit logging must be enabled", "Ensure audit trail captured",
            "Verify audit logging is enabled for all systems", "enabled",
            "see attached evidence"]]
    company_path = tmp_path / "company_skeptic.docx"
    _write_docx(company_path, headers, rows)

    run_dir = tmp_path / "run"
    assert pipeline.main(["start", "--official", str(official_path),
                          "--company", str(company_path),
                          "--run-dir", str(run_dir)]) == 0

    mreqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    mapping = {"0": "stig_objective_or_requirement", "1": "stig_description",
              "2": "stig_command_or_value",
              "3": "company_approved_setting_or_expected_value",
              "4": "observed_value_or_evidence"}
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl",
                       [_mapping_answer(mreqs[0], mapping=mapping)])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    canon_reqs = common.read_jsonl(run_dir / "canonicalize_requests.jsonl")
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in canon_reqs])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert len(m_reqs) == 1
    common.write_jsonl(run_dir / "matching_responses.jsonl",
                       [_match_answer(m_reqs[0], ["V-7001"])])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    sem_reqs = common.read_jsonl(run_dir / "semantic_requests.jsonl")
    assert len(sem_reqs) == 1                  # non-numeric -> semantic path
    sreq = sem_reqs[0]
    common.write_jsonl(run_dir / "semantic_responses.jsonl", [{
        "record_id": sreq["record_id"], "rule_id": sreq["rule_id"],
        "finding_type": "cannot-determine", "verdict": "Cannot Assess",
        "row_quote": "see attached evidence",
        "rule_quote": "Verify audit logging is enabled for all systems",
        "interpretation": "Evidence reference only; cannot verify without "
                          "the attachment."}])
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    det = [f for f in final["findings"]
          if f["record_id"] == sreq["record_id"]][0]
    fid = det["finding_id"]

    good = {"finding_id": fid, "outcome": "refuted", "reason": "misquoted"}
    bad_outcome = {"finding_id": fid, "outcome": "maybe", "reason": "n/a"}
    unknown_fid = {"finding_id": "F-doesnotexist00", "outcome": "upheld",
                  "reason": "nothing to attach to"}
    common.write_jsonl(run_dir / "skeptic_responses.jsonl",
                       [good, bad_outcome, unknown_fid])
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report",
                        "--allow-pending"])
    assert rc == 0
    final2 = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    det2 = [f for f in final2["findings"] if f["finding_id"] == fid][0]
    assert det2["disputed"] is True
    assert det2["skeptic"]["outcome"] == "refuted"
    assert det2["human_review_needed"] is True

    failures = common.read_jsonl(run_dir / "validation_failures.jsonl")
    skeptic_failures = [f for f in failures if f["kind"] == "skeptic"]
    assert any("malformed-response" in f["errors"] for f in skeptic_failures)
    assert any("no-such-request" in f["errors"] for f in skeptic_failures)


# --------------------------------------------------------------------------
# Task 17 review: semantic strike-1-retry regression guard. The old
# test_end_to_end.py::test_semantic_retry_not_swept_by_allow_pending had no
# equivalent under the new record_id-based schema after Task 17's e2e
# rewrite -- rebuilt here against the current pipeline.
# --------------------------------------------------------------------------

def test_semantic_strike1_retry_not_swept_by_allow_pending(tmp_path):
    """A semantic response that fails validation on strike 1 must get its
    documented retry chance via `finalize` (no --allow-pending) refusing
    with exit 4 -- it must NOT be immediately, silently swept into a
    permanent, falsely-labeled "semantic-pass-not-run"/"llm-output-rejected"
    finding just because a still-pending pair happens to look answerable.
    This guards the SKILL.md-documented compare-mode flow (step 8's retry
    loop must run to completion, without --allow-pending, before any
    pending semantic pair may legitimately be treated as unanswerable)."""
    official_path = tmp_path / "official_semretry.csv"
    _write_official_csv(official_path, [
        {"rule_id": "V-7001", "title": "Audit logging must be enabled",
         "severity": "high",
         "check_text": "Verify audit logging is enabled for all systems",
         "fix_text": "Enable audit logging", "expected_value": "enabled"}])
    headers = ["Requirement", "Description", "Command", "Approved Setting",
              "Observed"]
    rows = [["Audit logging must be enabled", "Ensure audit trail captured",
            "Verify audit logging is enabled for all systems", "enabled",
            "see attached evidence"]]
    company_path = tmp_path / "company_semretry.docx"
    _write_docx(company_path, headers, rows)

    run_dir = tmp_path / "run"
    assert pipeline.main(["start", "--official", str(official_path),
                          "--company", str(company_path),
                          "--run-dir", str(run_dir)]) == 0

    mreqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    mapping = {"0": "stig_objective_or_requirement", "1": "stig_description",
              "2": "stig_command_or_value",
              "3": "company_approved_setting_or_expected_value",
              "4": "observed_value_or_evidence"}
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl",
                       [_mapping_answer(mreqs[0], mapping=mapping)])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    canon_reqs = common.read_jsonl(run_dir / "canonicalize_requests.jsonl")
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in canon_reqs])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert len(m_reqs) == 1
    common.write_jsonl(run_dir / "matching_responses.jsonl",
                       [_match_answer(m_reqs[0], ["V-7001"])])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    sem_reqs = common.read_jsonl(run_dir / "semantic_requests.jsonl")
    assert len(sem_reqs) == 1                  # non-numeric -> semantic path
    sreq = sem_reqs[0]

    # Strike 1: an invalid semantic response -- row_quote is fabricated, not
    # a verbatim substring of the record's original_company_text, so it is
    # rejected by validate.validate_semantic_output.
    responses = [{"record_id": sreq["record_id"], "rule_id": sreq["rule_id"],
                 "finding_type": "cannot-determine", "verdict": "Cannot Assess",
                 "row_quote": "this exact phrase never appears in the row",
                 "rule_quote": "Verify audit logging is enabled for all systems",
                 "interpretation": "n/a"}]
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)

    # finalize WITHOUT --allow-pending must refuse (exit 4), not sweep the
    # still-retriable pair into a finding.
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 4

    final_path = run_dir / "final.json"
    assert not final_path.exists()

    # The retry must have been queued, not discarded, and the strike-1
    # rejection must be on the audit trail.
    sem_reqs2 = common.read_jsonl(run_dir / "semantic_requests.jsonl")
    retry_reqs = [r for r in sem_reqs2 if r.get("retry")]
    assert len(retry_reqs) == 1
    assert retry_reqs[0]["record_id"] == sreq["record_id"]
    assert retry_reqs[0]["rule_id"] == sreq["rule_id"]
    assert "previous_errors" in retry_reqs[0]
    assert retry_reqs[0]["previous_errors"]

    vfails = common.read_jsonl(run_dir / "validation_failures.jsonl")
    assert any(v["kind"] == "semantic" and v["row_id"] == sreq["record_id"]
               for v in vfails)

    # Strike 2 (the retry): a valid semantic response this time.
    responses.append({"record_id": sreq["record_id"], "rule_id": sreq["rule_id"],
                      "finding_type": "weaker", "verdict": "Cannot Assess",
                      "row_quote": "see attached evidence",
                      "rule_quote": "Verify audit logging is enabled for all "
                                    "systems",
                      "interpretation": "evidence references an external "
                                        "artifact, not a verifiable value"})
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)

    # No pending work remains once the retry is answered -- --allow-pending
    # is not needed here.
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir), "--no-report"])
    assert rc == 0

    final = json.loads(final_path.read_text(encoding="utf-8"))
    findings = [f for f in final["findings"] if f["rule_id"] == "V-7001"]
    assert len(findings) == 1
    f = findings[0]
    assert f["finding_type"] == "weaker"
    assert f["verdict"] == "Cannot Assess"
    assert f["basis"] == "semantic-comparison"
    assert f["basis"] != "semantic-pass-not-run"
    assert f["basis"] != "llm-output-rejected"


def _read_jsonl_or_empty(path):
    return common.read_jsonl(path) if path.exists() else []


def test_replay_idempotent_across_resolve_and_finalize(tmp_path, fixture_paths):
    """(5) Re-running resolve and finalize --allow-pending with every
    response file unchanged must not duplicate findings, change coverage,
    or add new validation failures."""
    run_dir = _full_run(tmp_path, fixture_paths)
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final1 = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    failures1 = _read_jsonl_or_empty(run_dir / "validation_failures.jsonl")

    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final2 = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    failures2 = _read_jsonl_or_empty(run_dir / "validation_failures.jsonl")

    ids1 = [f["finding_id"] for f in final1["findings"]]
    ids2 = [f["finding_id"] for f in final2["findings"]]
    assert len(ids2) == len(ids1)
    assert set(ids2) == set(ids1)
    assert len(ids2) == len(set(ids2))                 # no duplicates
    assert final2["coverage"] == final1["coverage"]
    assert len(failures2) == len(failures1)


def test_malformed_jsonl_matching_response_tolerated(tmp_path, fixture_paths):
    """(6) A syntactically-broken line in matching_responses.jsonl is
    recorded as a validation failure (never a crash) and does not block the
    rest of the batch from being applied."""
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    req = m_reqs[0]
    good = _match_answer(req, [c["rule_id"] for c in req["candidates"]][:1])
    path = run_dir / "matching_responses.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write("{this is not valid json,,,\n")
        f.write(json.dumps(good) + "\n")

    rc = pipeline.main(["resolve", "--run-dir", str(run_dir)])
    assert rc == 0
    failures = common.read_jsonl(run_dir / "validation_failures.jsonl")
    assert any(f["kind"] == "matching" and "malformed-json" in f["errors"]
              for f in failures)
    state = {m["record_id"]: m
            for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    assert state[req["record_id"]]["tier"] is not None
