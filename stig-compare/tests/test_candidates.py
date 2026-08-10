import pytest

from fixtures.build_fixtures import build_all
import candidates
import extract


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    fx = build_all(tmp_path_factory.mktemp("fx"))
    official = extract.extract_official(fx["official_csv"])["records"]
    company = extract.extract_company(fx["company_docx"])["records"]
    return official, company


def test_technical_tokens():
    t = candidates.technical_tokens(
        "Run SHOW PARAMETER password_reuse_max and check PASSWORD_LIFE_TIME")
    assert "password_reuse_max" in t
    assert "password_life_time" in t
    assert "run" not in t and "and" not in t


def test_t1_unique_technical_signature(data):
    official, company = data
    results = candidates.generate(company, official)
    r1 = results[0]                          # password-reuse row
    assert r1["tier"] == "T1"
    assert r1["matched_rule_id"] == "V-1001"


def test_shortlist_recall_for_paraphrased_row(data):
    # candidate-generation recall: the correct rule must appear in the shortlist
    official, company = data
    results = candidates.generate(company, official)
    r2 = results[1]                          # paraphrased password-age row
    assert r2["tier"] is None                # goes to Claude (T2)
    ids = [c["rule_id"] for c in r2["candidates"]]
    assert "V-1002" in ids


def test_no_plausible_candidate_gives_empty_list(data):
    official, company = data
    results = candidates.generate(company, official)
    r4 = results[3]                          # screensaver row matches nothing
    assert r4["tier"] is None
    assert r4["matched_rule_id"] is None
    assert r4["candidates"] == []            # -> T4 unmatched downstream


def test_t0_exact_id_wins(data):
    official, company = data
    row = dict(company[0])
    row["original_company_text"] += " (ref V-1005)"
    results = candidates.generate([row], official)
    assert results[0]["tier"] == "T0"
    assert results[0]["matched_rule_id"] == "V-1005"


def test_severity_alone_never_creates_candidate(data):
    official, _ = data
    row = {"row_id": "R-test0001", "status": "ok", "context_grouping": "High",
           "stig_description": "", "stig_objective_or_requirement": "",
           "stig_command_or_value": "",
           "company_approved_setting_or_expected_value": "",
           "observed_value_or_evidence": "",
           "original_company_text": "High"}
    results = candidates.generate([row], official)
    assert results[0]["candidates"] == []
