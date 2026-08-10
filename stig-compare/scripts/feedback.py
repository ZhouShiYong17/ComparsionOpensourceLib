"""Feedback ingestion. Feedback NEVER becomes an active rule directly
(spec section 9): it always becomes a regression case, and at most a
candidate rule draft awaiting the Task 14 review gate."""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import candidates as candidates_mod
import common

PKG_ROOT = Path(__file__).resolve().parent.parent

_RULE_MAPPING = {"wrong match": "matching-key", "not meaningful": "ignore-field"}

# Fields a company row may carry (see candidates._ROW_TEXT_FIELDS and
# pipeline._COMPANY_NORM_FIELDS), other than the default ignore-field target
# (observed_value_or_evidence). Used only to detect whether a "not
# meaningful" comment names a field other than the default ignore target,
# in which case drafting an ignore-field candidate would be a guess and is
# skipped instead. Each field maps to its snake_case identifier plus the
# natural-language aliases a human reviewer is likely to type instead of the
# raw field name -- a raw substring/identifier match alone is near-inert on
# free text (spec review finding: "the description" doesn't contain
# "stig_description").
_FIELD_ALIASES = {
    "stig_description": ["stig_description", "description"],
    "stig_objective_or_requirement": [
        "stig_objective_or_requirement", "objective", "requirement"],
    "stig_command_or_value": [
        "stig_command_or_value", "command", "verification method",
        "check command"],
    "company_approved_setting_or_expected_value": [
        "company_approved_setting_or_expected_value", "approved setting",
        "expected value", "baseline"],
    "context_grouping": ["context_grouping", "group", "grouping", "category"],
}

_OTHER_FIELD_PATTERNS = [
    re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
    for aliases in _FIELD_ALIASES.values() for alias in aliases]


def _expected_for(classification, finding):
    if classification == "wrong match":
        return {"not_matched_rule_id": finding["rule_id"]}
    if classification in ("incorrect", "wrong classification"):
        return {"not_verdict": finding["verdict"]}
    if classification == "missed difference":
        return {"needs_human_review": True}
    if classification == "correct":
        return {"verdict": finding["verdict"],
                "matched_rule_id": finding["rule_id"]}
    return {"note_only": True}


def _build_snapshot(finding, manifest):
    """Minimal excerpt: the finding (with its company row trimmed to raw
    text + source_reference, and official rule/match as already carried on
    the finding), plus a manifest subset of hashes + versions. Never whole
    documents (spec section 9)."""
    company_row = finding.get("company_row", {}) or {}
    return {
        "finding": {
            "finding_id": finding.get("finding_id"),
            "row_id": finding.get("row_id"),
            "rule_id": finding.get("rule_id"),
            "verdict": finding.get("verdict"),
            "match": finding.get("match", {}) or {},
            "company_row": {
                "original_company_text": company_row.get(
                    "original_company_text", ""),
                "source_reference": company_row.get("source_reference", {}) or {},
            },
            "official_rule": finding.get("official_rule", {}) or {},
        },
        "manifest": {
            "official_sha256": manifest.get("official_sha256"),
            "company_sha256": manifest.get("company_sha256"),
            "versions": manifest.get("versions", {}) or {},
        },
    }


def _comment_names_other_field(comment):
    text = comment or ""
    return any(p.search(text) for p in _OTHER_FIELD_PATTERNS)


def _candidate_draft(classification, comment, finding, snapshot, fb_id):
    """Returns (category, scope, payload) or (None, None, None) when this
    classification drafts no rule -- the common case (spec section 9: a
    candidate is drafted only for classifications that map to a category)."""
    category = _RULE_MAPPING.get(classification)
    if category == "matching-key":
        row_text = snapshot["finding"]["company_row"]["original_company_text"]
        payload = {"exclude_rule_id": finding.get("rule_id"),
                  "row_technical_tokens": sorted(
                      candidates_mod.technical_tokens(row_text))}
        scope = {"level": "field", "value": "stig_command_or_value"}
        return category, scope, payload
    if category == "ignore-field":
        if _comment_names_other_field(comment):
            return None, None, None
        payload = {"field": "observed_value_or_evidence"}
        scope = {"level": "field", "value": "observed_value_or_evidence"}
        return category, scope, payload
    return None, None, None


def ingest(feedback_path, run_dir, package_root):
    run_dir = Path(run_dir)
    package_root = Path(package_root)
    feedback_dir = package_root / "feedback"
    regression_dir = package_root / "tests" / "regression"
    candidates_dir = package_root / "rules" / "candidates"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    regression_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    fb_data = json.loads(Path(feedback_path).read_text(encoding="utf-8"))
    run_started = (fb_data.get("run") or {}).get("started")
    items = fb_data.get("feedback", []) or []

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    manifest = final.get("manifest", {}) or {}
    findings_by_id = {f["finding_id"]: f for f in final.get("findings", []) or []}

    stored, cases, candidates_out, errors = [], [], [], []

    for item in items:
        fid = item.get("finding_id")
        classification = item.get("classification")
        comment = item.get("comment", "") or ""

        finding = findings_by_id.get(fid)
        if finding is None:
            errors.append(f"unknown finding_id: {fid}")
            continue

        fb_id = "FB-" + common.short_hash(fid, classification, run_started)
        suffix = fb_id[3:]
        fb_path = feedback_dir / f"{fb_id}.json"
        if fb_path.exists():
            errors.append(f"duplicate-feedback: {fb_id} (finding {fid})")
            continue

        snapshot = _build_snapshot(finding, manifest)

        # 1. Store the feedback item itself, always.
        fb_record = {
            "feedback_id": fb_id,
            "finding_id": fid,
            "classification": classification,
            "comment": comment,
            "run": {"started": run_started},
            "snapshot": snapshot,
        }
        fb_path.write_text(json.dumps(fb_record, indent=1), encoding="utf-8")
        stored.append(fb_id)

        # 2. Always write a regression case.
        rc_id = "RC-" + suffix
        rc_record = {
            "case_id": rc_id,
            "feedback_id": fb_id,
            "snapshot": snapshot,
            "expected": _expected_for(classification, finding),
        }
        (regression_dir / f"{rc_id}.json").write_text(
            json.dumps(rc_record, indent=1), encoding="utf-8")
        cases.append(rc_id)

        # 3. Draft a candidate rule only for classifications that map to a
        # category. It is NEVER active: status is always "candidate" here,
        # and this module never touches registry.json.
        category, scope, payload = _candidate_draft(
            classification, comment, finding, snapshot, fb_id)
        if category is not None:
            rl_id = "RL-" + suffix
            rl_record = {
                "rule_id": rl_id,
                "version": 1,
                "category": category,
                "scope": scope,
                "status": "candidate",
                "payload": payload,
                "provenance": {
                    "feedback_ids": [fb_id],
                    "approved_by": None,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "approved": None,
                },
            }
            (candidates_dir / f"{rl_id}.json").write_text(
                json.dumps(rl_record, indent=1), encoding="utf-8")
            candidates_out.append(rl_id)

    return {"stored": stored, "cases": cases, "candidates": candidates_out,
            "errors": errors}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_ingest(args):
    package_root = Path(args.package_root) if args.package_root else PKG_ROOT
    result = ingest(args.feedback_path, args.run_dir, package_root)
    print(f"ingest: stored={len(result['stored'])} cases={len(result['cases'])} "
          f"candidates={len(result['candidates'])} errors={len(result['errors'])}")
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
