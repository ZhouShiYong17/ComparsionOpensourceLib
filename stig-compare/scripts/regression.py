"""Advisory regression replay through the normal LLM comparison pass.

There is no deterministic replay and no approval gate any more: semantic
decisions belong to the LLM, so the only honest way to re-check a past
finding is to re-run the LLM comparison on the frozen inputs and DIFF the
answer against the reviewer's feedback. Everything here is ADVISORY — it
informs a human, it never gates or rewrites anything.

Flow (driven by the skill agent, replay mode):
1. build_replay(package_root, replay_dir) — freeze every replayable
   comparison case into <replay_dir>/replay_requests.jsonl (same shape as
   comparison_requests.jsonl, ids prefixed RPL-).
2. The agent answers them exactly like a comparison pass, writing
   <replay_dir>/replay_responses.jsonl.
3. evaluate_replay(package_root, replay_dir) — mechanically validate each
   response against the frozen payloads, then report agreement/disagreement
   with the prior verdict alongside the reviewer's classification, verbatim.
"""
import json
from pathlib import Path

import common
import validate


def _cases(package_root):
    regression_dir = Path(package_root) / "tests" / "regression"
    out = []
    for cf in sorted(regression_dir.glob("RC-*.json")):
        try:
            out.append(json.loads(cf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            out.append({"case_id": cf.stem, "unreadable": True})
    return out


def build_replay(package_root, replay_dir):
    """Freeze replayable cases into comparison-shaped requests. Rollup
    cases are not replayable in isolation (a rollup depends on every
    contributor's fresh comparison) and are listed as skipped."""
    replay_dir = Path(replay_dir)
    replay_dir.mkdir(parents=True, exist_ok=True)
    requests, skipped = [], []
    for case in _cases(package_root):
        cid = case.get("case_id", "unknown")
        snap = case.get("snapshot") or {}
        if case.get("unreadable") or case.get("kind") != "comparison" or \
                not snap.get("company_row") or not snap.get("official_row"):
            skipped.append(cid)
            continue
        requests.append({
            "comparison_id": f"RPL-{cid}",
            "case_id": cid,
            "record_id": snap.get("record_id"),
            "record": snap["company_row"],
            "official_rows": [snap["official_row"]],
            "match_basis": snap.get("match_basis", {}),
            "sweep_origin_row_ids": [],
            "precedents": [],
            "instructions_file": "prompts/comparison.md",
        })
    common.write_jsonl(replay_dir / "replay_requests.jsonl", requests)
    (replay_dir / "replay_manifest.json").write_text(
        json.dumps({"requests": len(requests), "skipped": skipped},
                   indent=1), encoding="utf-8")
    return {"requests": len(requests), "skipped": skipped}


def evaluate_replay(package_root, replay_dir):
    """Validate replay responses mechanically, then diff each fresh verdict
    against the frozen one. Output is advisory prose data — no gate."""
    replay_dir = Path(replay_dir)
    req_by_id = {r["comparison_id"]: r for r in
                 common.read_jsonl(replay_dir / "replay_requests.jsonl")}
    cases_by_id = {c.get("case_id"): c for c in _cases(package_root)}

    results, invalid = [], []
    responses_path = replay_dir / "replay_responses.jsonl"
    lines = []
    if responses_path.exists():
        lines = [l.strip() for l in
                 responses_path.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    seen = set()
    for raw in lines:
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError:
            invalid.append({"errors": ["malformed-json"]})
            continue
        if not isinstance(resp, dict):
            invalid.append({"errors": ["malformed-json"]})
            continue
        cid = resp.get("comparison_id")
        req = req_by_id.get(cid) if isinstance(cid, str) else None
        if req is None or cid in seen:
            invalid.append({"errors": ["no-such-request"], "id": cid})
            continue
        row = req["official_rows"][0]
        errs = validate.validate_comparison_output(
            resp, req["record"], {row["official_row_id"]: row},
            [row["official_row_id"]])
        if errs:
            invalid.append({"errors": errs, "id": cid})
            continue
        seen.add(cid)
        case = cases_by_id.get(req["case_id"], {})
        snap = case.get("snapshot", {})
        fresh = resp["per_rule"][0]
        results.append({
            "case_id": req["case_id"],
            "prior_verdict": snap.get("verdict"),
            "fresh_verdict": fresh["verdict"],
            "agrees_with_prior": fresh["verdict"] == snap.get("verdict"),
            "reviewer_classification": case.get("classification"),
            "reviewer_comment": case.get("comment"),
            "fresh_reasoning": fresh["reasoning"],
        })

    unanswered = sorted(set(req_by_id) - seen)
    report = {"advisory": True,
              "total_requests": len(req_by_id),
              "answered": len(results),
              "invalid": invalid,
              "unanswered": unanswered,
              "results": results}
    (replay_dir / "replay_report.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    return report
