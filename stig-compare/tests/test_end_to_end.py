import json

from fixtures.build_fixtures import build_all
import common
import pipeline
from test_pipeline import _answer_extraction, _match_answer, EX1_MAPPING, EX2_MAPPING


def test_end_to_end_real_format(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fx["official_csv"]),
                          "--company",
                          str(fx["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = [_match_answer(r, [c["rule_id"]
                                 for c in r["candidates"]][:1])
               for r in m_reqs]
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0

    # answer any semantic requests mechanically as cannot-determine
    sem_path = run_dir / "semantic_requests.jsonl"
    if sem_path.exists():
        sems = [{"record_id": r["record_id"], "rule_id": r["rule_id"],
                 "finding_type": "cannot-determine",
                 "verdict": "Cannot Assess",
                 "row_quote": r["record"]["original_company_text"]
                 .split(" | ")[0],
                 "rule_quote": r["rule"]["title"],
                 "interpretation": "insufficient evidence"}
                for r in common.read_jsonl(sem_path)]
        common.write_jsonl(run_dir / "semantic_responses.jsonl", sems)

    rc = pipeline.main(["finalize", "--run-dir", str(run_dir)])
    if rc == 4:
        rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                            "--allow-pending"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["ok"]
    assert final["coverage"]["company"]["ignored_irrelevant_table"] == 4
    assert (run_dir / "report.html").exists()
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Table triage" in html
