import pytest

from fixtures.build_fixtures import build_all
import extract


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("fx"))


@pytest.mark.parametrize("key", ["company_docx", "company_xlsx"])
def test_clean_company_extraction(fx, key):
    result = extract.extract_company(fx[key])
    records = result["records"]
    assert len(records) == 4
    assert all(r["status"] == "ok" for r in records)
    r1 = records[0]
    assert r1["context_grouping"] == "High"
    assert r1["stig_objective_or_requirement"] == "Password reuse must be restricted"
    assert r1["stig_command_or_value"] == "Run SHOW PARAMETER password_reuse_max"
    assert r1["company_approved_setting_or_expected_value"] == "9 or more"
    assert r1["observed_value_or_evidence"] == "9"
    assert r1["row_id"].startswith("R-")
    assert r1["source_reference"]["row_index"] == 1
    assert "password_reuse_max" in r1["original_company_text"]


def test_row_ids_stable_across_extractions(fx):
    a = extract.extract_company(fx["company_docx"])["records"]
    b = extract.extract_company(fx["company_docx"])["records"]
    assert [r["row_id"] for r in a] == [r["row_id"] for r in b]


def test_vague_row_has_empty_observed_value(fx):
    records = extract.extract_company(fx["company_docx"])["records"]
    vague = records[2]
    assert vague["stig_objective_or_requirement"] == "Logging checked"
    assert vague["observed_value_or_evidence"] == ""


def test_messy_headers_need_structuring(fx):
    result = extract.extract_company(fx["company_docx_messy"])
    statuses = [r["status"] for r in result["records"]]
    assert statuses.count("needs-structuring") == 4
    assert statuses.count("extraction-failed") == 1     # the empty row
    assert any(w["code"] == "unmapped-headers" for w in result["warnings"])
    failed = [r for r in result["records"] if r["status"] == "extraction-failed"]
    assert failed[0]["notes"] == "empty-row"
