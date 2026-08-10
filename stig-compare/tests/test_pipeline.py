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
