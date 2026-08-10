import pytest

import skeleton
from fixtures import build_fixtures


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    return build_fixtures.build_all(tmp_path_factory.mktemp("fx"))


def test_docx_skeleton_captures_all_tables_and_narrative(paths):
    skel = skeleton.extract_skeleton(paths["company_real_docx"])
    tables = skel["tables"]
    assert [t["table_index"] for t in tables] == [1, 2, 3, 4]
    assert "JB.1.1 STIG HARDEING- SEVERITY HIGH" in tables[2]["preceding_narrative"]
    assert "IM-1.1" in tables[3]["preceding_narrative"]
    assert tables[2]["header_row"] == build_fixtures.EX1_HEADERS
    assert len(tables[3]["rows"]) == len(build_fixtures.EX2_ROWS)
    assert tables[3]["rows"][0]["row_index"] == 1
    assert tables[3]["rows"][0]["cells"][1] == build_fixtures.EX2_ROWS[0][1]
    assert all(t["sheet_or_section"] == "document-body" for t in tables)


def test_narrative_resets_between_tables(paths):
    skel = skeleton.extract_skeleton(paths["company_real_docx"])
    assert "General Information" not in skel["tables"][2]["preceding_narrative"]


def test_xlsx_skeleton_one_table_per_sheet(paths):
    skel = skeleton.extract_skeleton(paths["company_xlsx"])
    assert len(skel["tables"]) == 1
    t = skel["tables"][0]
    assert t["sheet_or_section"] == "sheet=Submission"
    assert t["header_row"][0] == "Group"
    assert len(t["rows"]) == 4


def test_unsupported_suffix_raises(paths, tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError):
        skeleton.extract_skeleton(bad)


def test_merged_cells_flagged(paths):
    skel = skeleton.extract_skeleton(paths["company_merged_docx"])
    rows = skel["tables"][0]["rows"]
    assert rows[0]["merged"] is False
    assert rows[1]["merged"] is True
