import json
from pathlib import Path

import pytest

import helpers
from fixtures import build_fixtures
from helpers import run


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build_fixtures.build_all(tmp_path_factory.mktemp("fx"))


def test_full_chain_company_real(fx, tmp_path):
    final = helpers.drive_chain(str(fx["official_csv"]),
                                str(fx["company_real_docx"]), tmp_path)
    cov = final["coverage"]
    assert cov["ok"]
    assert cov["company"]["ignored_irrelevant_table"] == 4
    assert cov["company"]["matched"] == 4
    assert cov["company"]["unresolved"] == 0
    assert cov["official"]["addressed"] == 4
    assert len(final["findings"]) == 4
    assert all(f["validation"]["outcome"] == "upheld"
               for f in final["findings"])
    assert all(f["verdict"] == "Compliant" for f in final["findings"])
    # EX2 row 2 declares a DEVIATION; the claim reading must survive to the
    # finding untouched by any Python classifier.
    deviating_claims = [f for f in final["findings"]
                        if f["claim_reading"] == "deviation"]
    assert len(deviating_claims) == 1
    # Full render.
    run(["finalize", "--run-dir", str(tmp_path), "--allow-pending"])
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Table triage" in html
    assert "http://" not in html and "https://" not in html


def test_merged_rows_preserved_as_continuations(fx, tmp_path):
    rd = str(tmp_path)
    run(["start", "--official", str(fx["official_csv"]),
         "--company", str(fx["company_merged_docx"]), "--run-dir", rd])
    helpers.answer_structure(rd)
    helpers.answer_mapping(rd, classify=lambda req: ("stig_relevant",
                                                     "other"))
    run(["resolve", "--run-dir", rd])
    helpers.answer_interpretation(rd)
    run(["resolve", "--run-dir", rd])
    records = helpers.read_jsonl(Path(rd) / "company_records.jsonl")
    assert len(records) == 1
    rec = records[0]
    assert rec["continuation_cells"], "continuation cells were lost"
    assert "Merged A2" in helpers.record_text(rec)
    # The continuation row's verbatim text is legitimate quote evidence.
    import validate
    assert validate.quote_exists("Merged A2",
                                 validate.company_quote_source(rec))
    # Coverage: continuation row inherits the parent's bucket.
    helpers.answer_scoping(rd, nominate=lambda r, rows: [])
    run(["resolve", "--run-dir", rd])
    run(["finalize", "--run-dir", rd, "--no-report", "--allow-pending"])
    final = json.loads((Path(rd) / "final.json").read_text("utf-8"))
    assert final["coverage"]["ok"]
    assert final["coverage"]["company"]["unmatched"] == 2


def test_unmatched_and_unaddressed_surface(fx, tmp_path):
    final = helpers.drive_chain(str(fx["official_csv"]),
                                str(fx["company_docx"]), tmp_path)
    cov = final["coverage"]
    assert cov["ok"]
    assert cov["company"]["matched"] == 1
    assert cov["company"]["unmatched"] == 3
    assert cov["official"]["unaddressed"] == 4
    assert len(final["unmatched_rows"]) == 3
    assert len(final["unaddressed_rules"]) == 4
    # Unaddressed rows keep ALL their columns for the report.
    assert all(r["raw_record"] for r in final["unaddressed_rules"])
