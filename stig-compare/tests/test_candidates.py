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


def test_all_caps_stopword_not_a_technical_token():
    # Review finding: a shouted generic word ("SHOW") must never itself be
    # treated as a technical signature -- it's excluded (stopword) from the
    # ALL-CAPS branch entirely, unlike a real technical signature such as
    # "PASSWORD_LIFE_TIME" (has an underscore, survives regardless of case).
    t = candidates.technical_tokens("Please SHOW the current NOTE banner")
    assert "show" not in t


def test_all_caps_stopword_gives_no_t1_match_or_technical_score():
    # A row and a rule that share ONLY a shouted generic word ("SHOW") in
    # all caps must not produce a silent, unreviewed T1 match, and the
    # "technical" feature must score 0 for that pair.
    official = [{"rule_id": "V-9001", "title": "Banner display",
                "severity": "low",
                "check_text": "Run SHOW to inspect the banner setting.",
                "fix_text": "No fix needed.", "expected_value": ""}]
    row = {"row_id": "R-shoutcap1", "status": "ok", "context_grouping": "",
          "stig_description": "", "stig_objective_or_requirement": "",
          "stig_command_or_value": "",
          "company_approved_setting_or_expected_value": "",
          "observed_value_or_evidence": "",
          "original_company_text": "Admin must SHOW the current banner text"}
    results = candidates.generate([row], official)
    assert results[0]["tier"] is None
    assert results[0]["matched_rule_id"] is None

    idf = candidates.build_idf(official)
    scored = candidates.score_row(row, official[0], idf)
    assert scored["features"]["technical"] == 0.0


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


def test_paraphrased_row_with_token_overlap_only(data):
    # Regression: paraphrased row using only ordinary words (no technical tokens,
    # no value overlap, non-matching severity) must still appear in shortlist.
    # This tests the recall mechanism that stopword filtering must preserve.
    official, _ = data
    row = {"row_id": "R-test0002", "status": "ok", "context_grouping": "High",
           "stig_description": "User sessions should terminate after idle time",
           "stig_objective_or_requirement": "User sessions must end after a short period of inactivity",
           "stig_command_or_value": "Check session timeout settings",
           "company_approved_setting_or_expected_value": "",
           "observed_value_or_evidence": "",
           "original_company_text": "User sessions must end after a short period of inactivity"}
    results = candidates.generate([row], official)
    # V-1004 is "Session timeout must be enforced" (severity medium)
    # Should appear in shortlist via token overlap despite context mismatch
    ids = [c["rule_id"] for c in results[0]["candidates"]]
    assert "V-1004" in ids
