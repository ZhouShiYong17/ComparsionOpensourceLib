import pytest
import tempfile
from pathlib import Path

import docx

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


def test_merged_cells_force_needs_structuring():
    """Merged cells in DOCX row should force status=needs-structuring with warning."""
    from docx.oxml.ns import qn
    from docx.oxml import parse_xml

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "merged.docx"
        d = docx.Document()
        t = d.add_table(rows=1, cols=6)
        # Header row
        headers = ["Group", "STIG Requirement", "Description",
                   "Command to Verify", "Approved Setting", "Observed Value"]
        for i, h in enumerate(headers):
            t.rows[0].cells[i].text = h

        # Normal row (should extract ok)
        r1 = t.add_row()
        r1.cells[0].text = "High"
        r1.cells[1].text = "Normal requirement"
        r1.cells[2].text = "Normal description"
        r1.cells[3].text = "How to check"
        r1.cells[4].text = "expected"
        r1.cells[5].text = "actual"

        # Row with merged cells (should force needs-structuring)
        r2 = t.add_row()
        r2.cells[0].text = "Medium"
        r2.cells[1].text = "Merged text spans"
        r2.cells[2].text = "Merged text spans"
        r2.cells[3].text = "Check"
        r2.cells[4].text = "Value"
        r2.cells[5].text = "Result"

        # Add gridSpan=2 to cell 1 to indicate it spans 2 columns
        tcPr = r2.cells[1]._element.find(qn('w:tcPr'))
        if tcPr is None:
            tcPr = parse_xml('<w:tcPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
            r2.cells[1]._element.insert(0, tcPr)
        gridSpan = parse_xml('<w:gridSpan xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="2"/>')
        tcPr.append(gridSpan)

        d.save(str(path))

        result = extract.extract_company(path)
        records = result["records"]

        # Normal row should be ok
        normal = records[0]
        assert normal["status"] == "ok"
        assert normal["notes"] == ""

        # Merged row should be needs-structuring
        merged = records[1]
        assert merged["status"] == "needs-structuring"
        assert merged["notes"] == "merged-cells"
        assert merged["context_grouping"] == "Medium"

        # Should have merged-cells warning
        assert any(w["code"] == "merged-cells" for w in result["warnings"])
