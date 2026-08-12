"""Feedback ingestion. Reviewer feedback is stored VERBATIM.

Python never interprets a reviewer's classification or comment: no regex
parsing, no rule drafting, no keyed verdict overrides. Each item becomes
(1) an audit record under feedback/, (2) a precedent line in
feedback/precedents.jsonl — mechanically keyed by official row and injected
verbatim into future comparison requests, where the LLM judges whether it
applies — and (3) an advisory regression case under tests/regression/ that
regression.py can replay through the normal LLM comparison pass.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import common

PKG_ROOT = Path(__file__).resolve().parent.parent


def ingest(feedback_path, run_dir, package_root):
    run_dir = Path(run_dir)
    package_root = Path(package_root)
    feedback_dir = package_root / "feedback"
    regression_dir = package_root / "tests" / "regression"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    regression_dir.mkdir(parents=True, exist_ok=True)

    fb_data = json.loads(Path(feedback_path).read_text(encoding="utf-8"))
    run_meta = fb_data.get("run") or {}
    run_started = run_meta.get("started")
    items = fb_data.get("feedback", []) or []

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    manifest = final.get("manifest", {}) or {}
    findings_by_id = {f["finding_id"]: f
                      for f in final.get("findings", []) or []}
    rollups_by_id = {r["rollup_id"]: r
                     for r in final.get("rule_rollups", []) or []}

    stored, cases, precedent_ids, errors = [], [], [], []
    precedents_path = feedback_dir / "precedents.jsonl"
    new_precedents = []

    for item in items:
        fid = item.get("finding_id")
        classification = item.get("classification")
        comment = item.get("comment", "") or ""

        finding = findings_by_id.get(fid)
        rollup = rollups_by_id.get(fid) if finding is None else None
        if finding is None and rollup is None:
            errors.append(f"unknown finding_id: {fid}")
            continue

        fb_id = "FB-" + common.short_hash(fid, classification, run_started)
        fb_path = feedback_dir / f"{fb_id}.json"
        if fb_path.exists():
            errors.append(f"duplicate-feedback: {fb_id} (finding {fid})")
            continue

        kind = "comparison" if finding is not None else "rollup"
        target = finding if finding is not None else rollup

        # 1. Audit record: the reviewer's words plus the finding VERBATIM
        # (the finding already carries the complete company row and every
        # official column — never whole documents).
        fb_record = {
            "feedback_id": fb_id,
            "finding_id": fid,
            "kind": kind,
            "classification": classification,
            "comment": comment,
            "run": {"started": run_started,
                    "official_sha256": manifest.get("official_sha256"),
                    "company_sha256": manifest.get("company_sha256")},
            "snapshot": target,
        }
        fb_path.write_text(json.dumps(fb_record, indent=1), encoding="utf-8")
        stored.append(fb_id)

        # 2. Precedent line: mechanically keyed by official row; the LLM
        # decides applicability when a future comparison cites this row.
        new_precedents.append({
            "feedback_id": fb_id,
            "official_row_id": target.get("official_row_id"),
            "display_id": target.get("display_id"),
            "official_sha256": manifest.get("official_sha256"),
            "classification": classification,
            "comment": comment,
            "prior_verdict": target.get("verdict"),
        })
        precedent_ids.append(fb_id)

        # 3. Advisory regression case: frozen inputs for an LLM replay.
        rc_id = "RC-" + fb_id[3:]
        rc_record = {
            "case_id": rc_id,
            "feedback_id": fb_id,
            "kind": kind,
            "classification": classification,
            "comment": comment,
            "advisory": True,
            "snapshot": target,
            "manifest": {"official_sha256": manifest.get("official_sha256"),
                         "company_sha256": manifest.get("company_sha256"),
                         "versions": manifest.get("versions", {}) or {}},
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        (regression_dir / f"{rc_id}.json").write_text(
            json.dumps(rc_record, indent=1), encoding="utf-8")
        cases.append(rc_id)

    if new_precedents:
        existing = []
        if precedents_path.exists():
            existing = common.read_jsonl(precedents_path)
        common.write_jsonl(precedents_path, existing + new_precedents)

    return {"stored": stored, "cases": cases, "precedents": precedent_ids,
            "errors": errors}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_ingest(args):
    package_root = Path(args.package_root) if args.package_root else PKG_ROOT
    result = ingest(args.feedback_path, args.run_dir, package_root)
    print(f"ingest: stored={len(result['stored'])} cases={len(result['cases'])} "
          f"precedents={len(result['precedents'])} "
          f"errors={len(result['errors'])}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="feedback")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("feedback_path")
    p_ingest.add_argument("--run-dir", required=True)
    p_ingest.add_argument("--package-root", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "ingest":
        return cmd_ingest(args)
    raise ValueError(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
