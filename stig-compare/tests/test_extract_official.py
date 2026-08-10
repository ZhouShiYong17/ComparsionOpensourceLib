import pytest

from fixtures.build_fixtures import build_all
import extract


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("fx"))


@pytest.mark.parametrize("key", ["official_csv", "official_json", "official_xlsx"])
def test_extract_official_all_formats(fx, key):
    result = extract.extract_official(fx[key])
    records = result["records"]
    assert len(records) == 5
    by_id = {r["rule_id"]: r for r in records}
    assert "password_reuse_max" in by_id["V-1001"]["check_text"]
    assert by_id["V-1001"]["expected_value"] == "9 or more"
    assert by_id["V-1001"]["severity"] == "high"
    assert result["warnings"] == []
    assert records[0]["provenance"]["source_file"] == fx[key].name


def test_duplicate_rule_ids_warn(fx):
    result = extract.extract_official(fx["official_dup_ids_csv"])
    codes = [w["code"] for w in result["warnings"]]
    assert "duplicate-rule-id" in codes
    assert len(result["records"]) == 2      # both kept, never dropped


def test_empty_official_warns(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("Rule ID,Title\n", encoding="utf-8")
    result = extract.extract_official(p)
    assert result["records"] == []
    assert any(w["code"] == "empty-official-file" for w in result["warnings"])


def test_csv_with_blank_rows_warns(tmp_path):
    p = tmp_path / "blank_rows.csv"
    p.write_text("Rule ID,Title\n\n  \n", encoding="utf-8")
    result = extract.extract_official(p)
    assert result["records"] == []
    assert any(w["code"] == "empty-official-file" for w in result["warnings"])


def test_json_with_unmapped_keys_warns(tmp_path):
    # Minor finding 7: records parse, but none of their keys match any
    # canonical field name -- every mapped field of every record is empty.
    # Must not silently produce N all-blank records with zero warnings.
    import json
    p = tmp_path / "unmapped.json"
    p.write_text(json.dumps([
        {"identifier": "V-1001", "name": "Password reuse"},
        {"identifier": "V-1002", "name": "Password age"},
    ]), encoding="utf-8")
    result = extract.extract_official(p)
    assert len(result["records"]) == 2
    assert all(not r["rule_id"] and not r["title"] for r in result["records"])
    codes = [w["code"] for w in result["warnings"]]
    assert "unmapped-json-keys" in codes
    w = next(w for w in result["warnings"] if w["code"] == "unmapped-json-keys")
    assert "2" in w["detail"]
