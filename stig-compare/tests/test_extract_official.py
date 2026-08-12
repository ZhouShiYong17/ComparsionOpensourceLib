import pytest

import extract
from fixtures import build_fixtures


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    return build_fixtures.build_all(tmp_path_factory.mktemp("fx"))


def test_csv_keeps_all_columns_verbatim(paths):
    result = extract.extract_official(paths["official_csv"])
    rows = result["rows"]
    assert len(rows) == 5
    r = rows[0]
    assert r["headers"] == ["Rule ID", "Title", "Severity", "Check Text",
                            "Fix Text", "Expected Value"]
    assert len(r["cells"]) == 6
    assert r["raw_record"]["Rule ID"] == "V-1001"
    assert r["raw_record"]["Fix Text"] == \
        "Set password_reuse_max to 9 or more."
    # Severity is NOT lowercased or otherwise touched.
    assert r["raw_record"]["Severity"] == "high"
    assert r["cells"] == [r["raw_record"][h] for h in r["headers"]]


def test_no_canonical_reduction_or_display_id(paths):
    result = extract.extract_official(paths["official_csv"])
    r = result["rows"][0]
    # Column semantics are the LLM structure pass's job, not extraction's.
    assert r["display_id"] is None
    assert r["column_roles"] is None
    assert "rule_id" not in r
    assert not hasattr(extract, "OFFICIAL_HEADER_SYNONYMS")


def test_official_row_ids_stable_and_unique(paths):
    a = extract.extract_official(paths["official_csv"])["rows"]
    b = extract.extract_official(paths["official_csv"])["rows"]
    ids_a = [r["official_row_id"] for r in a]
    ids_b = [r["official_row_id"] for r in b]
    assert ids_a == ids_b
    assert len(set(ids_a)) == len(ids_a)
    assert all(i.startswith("OR-") for i in ids_a)


def test_provenance_and_row_numbers(paths):
    rows = extract.extract_official(paths["official_csv"])["rows"]
    assert rows[0]["provenance"]["locator"] == "csv,row=2"
    assert rows[0]["row_number"] == 2
    assert rows[0]["sheet_or_section"] == "csv"


def test_xlsx_per_sheet(paths):
    rows = extract.extract_official(paths["official_xlsx"])["rows"]
    assert len(rows) == 5
    assert rows[0]["sheet_or_section"] == "sheet=Rules"
    assert rows[0]["provenance"]["locator"] == "sheet=Rules,row=2"


def test_json_keeps_all_keys(paths):
    rows = extract.extract_official(paths["official_json"])["rows"]
    assert len(rows) == 5
    assert rows[0]["raw_record"]["rule_id"] == "V-1001"
    assert rows[0]["headers"] == list(build_fixtures.OFFICIAL_RULES[0].keys())
    assert rows[0]["provenance"]["locator"] == "json,index=0"


def test_duplicate_and_empty_headers_disambiguated(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("A,,A\n1,2,3\n", encoding="utf-8")
    rows = extract.extract_official(p)["rows"]
    raw = rows[0]["raw_record"]
    assert len(raw) == 3            # nothing shadowed
    assert raw["A"] == "1"
    assert raw["col1"] == "2"
    assert raw["A#col2"] == "3"


def test_blank_rows_skipped_and_empty_file_warns(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("A,B\n , \n", encoding="utf-8")
    result = extract.extract_official(p)
    assert result["rows"] == []
    p2 = tmp_path / "empty.csv"
    p2.write_text("A,B\n", encoding="utf-8")
    result2 = extract.extract_official(p2)
    assert any(w["code"] == "empty-official-file"
               for w in result2["warnings"])


def test_unsupported_suffix_raises(tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError):
        extract.extract_official(bad)
