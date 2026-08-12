"""Scripted, mechanically-valid Claude answers for pipeline tests.

These are deterministic TEST STUBS standing in for the LLM — string
containment here is test scaffolding, not product logic. Every answer
respects the validators' contracts (verbatim quotes, echoes, exactly-once
accounting) so tests can drive the state machine end to end.
"""
import json
from pathlib import Path

import pipeline

ROLE_MAP = {"Rule ID": "id", "Title": "title", "Severity": "severity",
            "Check Text": "check", "Fix Text": "fix",
            "Expected Value": "expected"}

FIELD_MAP = {
    "STIG REQUIREMENT": "stig_objective_or_requirement",
    "STIG Requirement": "stig_objective_or_requirement",
    "DESCRIPTION": "stig_description",
    "Description": "stig_description",
    "COMMAND TO VERIFY": "stig_command_or_value",
    "Command to Verify": "stig_command_or_value",
    "APPROVED SETTING": "company_approved_setting_or_expected_value",
    "Approved Setting": "company_approved_setting_or_expected_value",
    "Observed Value": "observed_value_or_evidence",
    "System Value/Parameter": "stig_objective_or_requirement",
    "ADOPT COMPANY STANDARDS DEVIATION/COMPLY": "company_compliance_claim",
    "COMPANY AGREED SETTING/COMMAND TO IMPLEMENT":
        "company_approved_setting_or_expected_value",
    "SEVERITY": "company_severity",
    "CURRENT SETTING": "observed_value_or_evidence",
    "REMARKS/JUSTIFICATION": "remarks_or_justification",
}


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def write_responses(run_dir, name, answers):
    with open(Path(run_dir) / name, "w", encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")


def append_response(run_dir, name, answer):
    with open(Path(run_dir) / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(answer) + "\n")


def run(cmd, expect=0):
    code = pipeline.main([str(c) for c in cmd])
    assert code == expect, f"pipeline {cmd} -> {code}, expected {expect}"
    return code


def _echo(req, answer):
    if req.get("retry"):
        answer["retry"] = True
    return answer


def title_of(row):
    return row["raw_record"].get("Title", "")


def record_text(rec):
    parts = list(rec.get("cells", []))
    for c in rec.get("continuation_cells", []):
        parts.extend(c["cells"])
    return " ".join(parts)


def answer_structure(run_dir):
    answers = []
    for req in read_jsonl(Path(run_dir) / "official_structure_requests.jsonl"):
        roles = {h: ROLE_MAP.get(h, "other") for h in req["headers"]}
        answers.append(_echo(req, {
            "structure_id": req["structure_id"],
            "display_id_column": "Rule ID" if "Rule ID" in req["headers"]
            else None,
            "column_roles": roles, "notes": ""}))
    write_responses(run_dir, "official_structure_responses.jsonl", answers)


def default_classify(req):
    narrative = req.get("preceding_narrative", "")
    if "Instructions" in narrative:
        return "irrelevant", "instructions"
    if "General Information" in narrative:
        return "irrelevant", "general-info"
    return "stig_relevant", "other"


def answer_mapping(run_dir, classify=None):
    classify = classify or default_classify
    answers = []
    for req in read_jsonl(Path(run_dir) / "table_mapping_requests.jsonl"):
        cls, reason = classify(req)
        cm, seen = {}, set()
        for i, h in enumerate(req["header_row"]):
            target = FIELD_MAP.get(h, "other")
            if target != "other" and target in seen:
                target = "other"
            seen.add(target)
            cm[str(i)] = target
        answers.append(_echo(req, {
            "table_index": req["table_index"], "classification": cls,
            "irrelevant_reason": reason, "column_mapping": cm,
            "context_grouping": req.get("preceding_narrative", "") or ""}))
    write_responses(run_dir, "table_mapping_responses.jsonl", answers)


def answer_interpretation(run_dir):
    """Default: merged rows are continuations of the previous row; every
    other row is one record."""
    answers = []
    for req in read_jsonl(Path(run_dir) / "interpretation_requests.jsonl"):
        rows_out = []
        for row in req["rows"]:
            if row.get("merged") and rows_out:
                rows_out.append({"row_index": row["row_index"],
                                 "disposition": "continuation"})
                continue
            fields, prov = {}, {}
            claim = "none"
            for i, cell in enumerate(row["cells"]):
                if not cell.strip():
                    continue
                target = req["column_mapping"].get(str(i), "other")
                if target != "other" and target not in fields:
                    fields[target] = cell
                    prov[target] = {"row_index": row["row_index"],
                                    "cell_index": i}
                if cell.strip() == "DEVIATION":
                    claim = "deviation"
                elif cell.strip() == "COMPLY":
                    claim = "comply"
            rows_out.append({"row_index": row["row_index"],
                             "disposition": "record",
                             "records": [{"sub_index": 0, "fields": fields,
                                          "field_provenance": prov,
                                          "company_claim_reading": claim,
                                          "interpretation_note": ""}]})
        answers.append(_echo(req, {"chunk_id": req["chunk_id"],
                                   "rows": rows_out}))
    write_responses(run_dir, "interpretation_responses.jsonl", answers)


def default_nominate(rec, official_rows):
    text = record_text(rec).lower()
    return [row["official_row_id"] for row in official_rows
            if title_of(row) and title_of(row).lower() in text]


def answer_scoping(run_dir, nominate=None):
    nominate = nominate or default_nominate
    answers = []
    for req in read_jsonl(Path(run_dir) / "scoping_requests.jsonl"):
        noms = []
        for rec in req["records"]:
            for oid in nominate(rec, req["official_rows"]):
                noms.append({"record_id": rec["record_id"],
                             "official_row_id": oid, "note": "stub"})
        answers.append(_echo(req, {"scoping_id": req["scoping_id"],
                                   "nominations": noms}))
    write_responses(run_dir, "scoping_responses.jsonl", answers)


def default_decide(req):
    rec = req["record"]
    sels = []
    for row in req["nominated_rows"]:
        title = title_of(row)
        quote_cell = next(
            (c for c in rec["cells"] if title.lower() in c.lower()), None)
        if quote_cell:
            sels.append({"official_row_id": row["official_row_id"],
                         "row_quote": quote_cell, "official_quote": title})
    return {"record_id": req["record_id"],
            "decision": "match" if sels else "none",
            "selections": sels, "ambiguous_official_row_ids": [],
            "basis": "title equality"}


def answer_adjudication(run_dir, decide=None):
    decide = decide or default_decide
    answers = []
    for req in read_jsonl(Path(run_dir) / "adjudication_requests.jsonl"):
        a = decide(req)
        if req.get("sweep_round"):
            a["sweep_round"] = True
        answers.append(_echo(req, a))
    write_responses(run_dir, "adjudication_responses.jsonl", answers)


def answer_sweep(run_dir, propose=None):
    answers = []
    for req in read_jsonl(Path(run_dir) / "sweep_requests.jsonl"):
        props = propose(req) if propose else []
        answers.append({"sweep_id": req["sweep_id"], "proposals": props})
    write_responses(run_dir, "sweep_responses.jsonl", answers)


def comparison_answer(req, verdict="Compliant", human_review=False,
                      claim_consistency="no-claim"):
    rec = req["record"]
    per_rule = []
    for row in req["official_rows"]:
        title = title_of(row) or row["cells"][0]
        quote_cell = next(
            (c for c in rec["cells"] if c.strip()), "")
        per_rule.append({
            "official_row_id": row["official_row_id"],
            "match_rationale": "same requirement text",
            "field_alignment": [
                {"company_ref": "cell", "official_column": "Title",
                 "company_quote": quote_cell, "official_quote": title,
                 "relation": "equivalent"}],
            "semantic_differences": "none noted",
            "change_analysis": [],
            "verdict": verdict,
            "confidence": "High",
            "human_review": human_review,
            "row_quote": quote_cell,
            "official_quote": title,
            "reasoning": "requirement text matches"})
    return {"comparison_id": req["comparison_id"],
            "record_id": req["record_id"], "per_rule": per_rule,
            "claim_consistency": claim_consistency, "record_notes": ""}


def answer_comparison(run_dir, mutate=None, **kw):
    answers = []
    for req in read_jsonl(Path(run_dir) / "comparison_requests.jsonl"):
        a = comparison_answer(req, **kw)
        if mutate:
            a = mutate(req, a)
        answers.append(_echo(req, a))
    write_responses(run_dir, "comparison_responses.jsonl", answers)


def answer_rollup(run_dir, joint_verdict="Compliant"):
    answers = []
    for req in read_jsonl(Path(run_dir) / "rollup_requests.jsonl"):
        answers.append(_echo(req, {
            "rollup_id": req["rollup_id"],
            "contributing_record_ids":
                [r["record_id"] for r in req["company_records"]],
            "joint_verdict": joint_verdict,
            "coverage_of_requirement": "fully-covered",
            "reasoning": "records jointly satisfy the requirement",
            "confidence": "High", "human_review": False}))
    write_responses(run_dir, "rollup_responses.jsonl", answers)


def validation_answer(req, outcome="upheld"):
    a = {"validation_id": req["validation_id"],
         "finding_id": req["finding_id"],
         "independent_verdict": req["claimed"]["verdict"],
         "outcome": outcome, "revised_verdict": None,
         "revised_change_analysis": None,
         "reason": "independent review agrees", "evidence_quote": ""}
    return a


def answer_validation(run_dir, mutate=None):
    answers = []
    for req in read_jsonl(Path(run_dir) / "validation_requests.jsonl"):
        a = validation_answer(req)
        if mutate:
            a = mutate(req, a)
        answers.append(_echo(req, a))
    write_responses(run_dir, "validation_responses.jsonl", answers)


def drive_chain(official, company, run_dir, classify=None, nominate=None,
                decide=None, comparison_kw=None, validation_mutate=None):
    """Drive a full happy-path run and return final.json as a dict."""
    rd = str(run_dir)
    run(["start", "--official", official, "--company", company,
         "--run-dir", rd])
    answer_structure(rd)
    answer_mapping(rd, classify=classify)
    run(["resolve", "--run-dir", rd])
    answer_interpretation(rd)
    run(["resolve", "--run-dir", rd])
    answer_scoping(rd, nominate=nominate)
    run(["resolve", "--run-dir", rd])
    answer_adjudication(rd, decide=decide)
    run(["resolve", "--run-dir", rd])
    run(["sweep", "--run-dir", rd])
    answer_sweep(rd)
    run(["resolve", "--run-dir", rd])
    answer_adjudication(rd, decide=decide)   # sweep-round retries, if any
    run(["resolve", "--run-dir", rd])
    answer_comparison(rd, **(comparison_kw or {}))
    run(["resolve", "--run-dir", rd])
    run(["rollup", "--run-dir", rd])
    answer_rollup(rd)
    run(["resolve", "--run-dir", rd])
    code = pipeline.main(["finalize", "--run-dir", rd, "--no-report"])
    if code == 4:
        answer_validation(rd, mutate=validation_mutate)
        run(["resolve", "--run-dir", rd])
        run(["finalize", "--run-dir", rd, "--no-report"])
    else:
        assert code == 0
    return json.loads((Path(rd) / "final.json").read_text(encoding="utf-8"))
