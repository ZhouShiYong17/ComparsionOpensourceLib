from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all


@pytest.fixture(scope="session")
def fixture_files(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("fx"))


def test_all_fixtures_exist(fixture_files):
    expected = {
        "official_csv", "official_json", "official_xlsx", "official_dup_ids_csv",
        "company_docx", "company_docx_messy", "company_xlsx",
    }
    assert expected == set(fixture_files)
    for path in fixture_files.values():
        assert Path(path).stat().st_size > 0


def test_official_csv_has_five_rules(fixture_files):
    text = Path(fixture_files["official_csv"]).read_text(encoding="utf-8")
    assert "V-1001" in text and "password_reuse_max" in text
    assert text.count("\n") >= 5  # header + 5 rules


def test_company_docx_table_shape(fixture_files):
    import docx
    d = docx.Document(str(fixture_files["company_docx"]))
    table = d.tables[0]
    assert len(table.rows) == 5          # header + 4 data rows
    assert table.rows[0].cells[0].text == "Group"
