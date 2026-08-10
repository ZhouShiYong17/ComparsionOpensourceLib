import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all
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
