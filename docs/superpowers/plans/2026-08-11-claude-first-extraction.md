# Claude-First Company Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic company-side extraction in `stig-compare` with a lossless skeleton dump + two-phase Claude canonicalization (table triage/column mapping, then chunked row canonicalization), multi-select matching with a one-round LLM sweep, and company compliance-claim capture — per the approved spec `docs/superpowers/specs/2026-08-11-claude-first-extraction-design.md`.

**Architecture:** Python's company-side job shrinks to a zero-interpretation skeleton dump (`skeleton.py`). Claude interprets it via two new request/response JSONL stages (`table_mapping_*`, `canonicalize_*`) validated by cell-verbatim checks and per-chunk count reconciliation, producing `company_records.jsonl` (the extended canonical record). Downstream stages (candidates → matching → sweep → compare → semantic → skeptic → coverage → report) are adapted for `record_id` keys and 0..N multi-select matches. The existing `start`/`resolve`/`finalize` orchestration pattern (fingerprinted consumed responses, two-strike retries, untrusted-LLM-output posture) is retained; a new `sweep` command joins the CLI.

**Tech Stack:** Python 3.10, `python-docx`, `openpyxl`, pytest. No network access anywhere. All work happens in `stig-compare/`; run pytest and scripts from that package root.

## Global Constraints

- Never remove the hard rule: missing `observed_value_or_evidence` → `Cannot Assess`, deterministically (spec §4 stage 8).
- The company's own compliance claim NEVER produces a verdict by itself; it only produces flags and review triggers (spec §2 decision 4).
- Every canonical data-field value must be a verbatim (whitespace-folded via `common.fold_ws`) substring of the cell named in `field_provenance` (spec §3).
- `interpretation_note` and `extra_fields` are excluded from candidate scoring and matching quotes (spec §3, §4 stage 5).
- Exactly ONE sweep round; sweep proposals become shortlist candidates, never matches directly; sweep-originated matches cap at Medium confidence and force human review (spec §4 stage 7, §5).
- No document text in error output or logs — exception type names only (existing codebase rule, see `extract.py:238`).
- New run-dir artifacts: `skeleton.json`, `table_state.jsonl`, `table_mapping_requests/responses.jsonl`, `canonicalize_requests/responses.jsonl`, `company_records.jsonl`, `sweep_requests/responses.jsonl`, `sweep_state.json`. Retained: `manifest.json`, `official_rules.jsonl`, `match_state.jsonl`, `matching_*`, `semantic_*`, `skeptic_responses.jsonl`, `findings.jsonl`, `validation_failures.jsonl`, `consumed_responses.json`, `final.json`, `report.html`, `extract_warnings.json`. Removed: `company_rows.jsonl`, `structuring_requests/responses.jsonl`.
- `consumed_responses.json` keys become: `table_mapping`, `canonicalize`, `matching`, `sweep`, `semantic`, `skeptic` (drop `structuring`).
- Old runs are NOT resumable across this version boundary — `VERSIONS.json` bumps make that visible; no back-compat shims inside run dirs.
- Commit after every task with the message given in its final step. All commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- All test commands run from `stig-compare/`: `python -m pytest tests/<file> -v`.

## Canonical shapes used by every task

**Canonical company record** (in `company_records.jsonl`):

```json
{
  "record_id": "CR-xxxxxxxx", "row_id": "R-xxxxxxxx",
  "context_grouping": "JB.1.1 STIG HARDEING- SEVERITY HIGH",
  "stig_description": "", "stig_objective_or_requirement": "",
  "stig_command_or_value": "", "company_approved_setting_or_expected_value": "",
  "observed_value_or_evidence": "", "company_compliance_claim": "",
  "company_severity": "", "remarks_or_justification": "",
  "claim_normalized": "comply | deviation | unknown",
  "extra_fields": {"REPORTING yes/no": "YES"},
  "interpretation_note": "",
  "field_provenance": {"stig_description": {"row_index": 1, "cell_index": 2}},
  "source_reference": {"table_index": 1, "row_index": 1, "sub_index": 0,
                        "sheet_or_section": "document-body",
                        "table_title": "..."},
  "original_company_text": "cell0 | cell1 | cell2",
  "status": "ok | extraction-failed", "notes": "",
  "normalized": {"...": "..."}
}
```

**match_state record** (multi-match):

```json
{
  "record_id": "CR-xxxxxxxx", "tier": null,
  "matched_rule_ids": [], "margin_flag": false,
  "candidates": [{"rule_id": "V-1001", "score": 1.2, "features": {}}],
  "row_quotes": {}, "rule_quotes": {}, "ambiguous_rule_ids": [],
  "match_failures": 0, "semantic_failures": {}, "retried": false,
  "verdict_done_rules": [], "sweep_origin_rule_ids": [], "warnings": []
}
```

**table_state record**:

```json
{
  "table_index": 1,
  "classification": null,
  "irrelevant_reason": "", "column_mapping": {}, "context_grouping": "",
  "mapping_failures": 0,
  "row_dispositions": {"1": "record"}, "parent_of": {"5": 4},
  "chunks": {"T1-C0": {"row_indexes": [1, 2], "done": false, "failures": 0,
                        "entries": []}}
}
```

`classification` values over its lifecycle: `null` (unanswered) → one of `"stig_relevant" | "irrelevant" | "uncertain"` (valid Claude answer) or `"mapping-failed"` (two strikes) or `"mapping-pass-not-run"` (finalize `--allow-pending` on a never-answered table). Coverage treats anything other than the three valid Claude answers as extraction-failed rows, and `irrelevant` as `ignored_irrelevant_table`.

---

### Task 1: `common.record_id`

**Files:**
- Modify: `stig-compare/scripts/common.py`
- Test: `stig-compare/tests/test_common.py`

**Interfaces:**
- Consumes: `common.short_hash` (existing).
- Produces: `common.record_id(table_index, row_index, sub_index, raw_text) -> "CR-" + 8-hex` — stable, used by every later task. `common.row_id` is unchanged.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_common.py`)

```python
def test_record_id_stable_and_prefixed():
    a = common.record_id(1, 2, 0, "some | row | text")
    b = common.record_id(1, 2, 0, "some | row | text")
    assert a == b
    assert a.startswith("CR-") and len(a) == 3 + 8


def test_record_id_varies_by_sub_index():
    a = common.record_id(1, 2, 0, "text")
    b = common.record_id(1, 2, 1, "text")
    assert a != b
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_common.py -v -k record_id`
Expected: FAIL with `AttributeError: module 'common' has no attribute 'record_id'`

- [ ] **Step 3: Implement** (in `scripts/common.py`, directly under `row_id`)

```python
def record_id(table_index, row_index, sub_index, raw_text):
    return "CR-" + short_hash(table_index, row_index, sub_index, raw_text)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_common.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/common.py stig-compare/tests/test_common.py
git commit -m "feat(stig-compare): add record_id for split-capable canonical records"
```

---

### Task 2: Real-format fixtures

**Files:**
- Modify: `stig-compare/tests/fixtures/build_fixtures.py`
- Test: `stig-compare/tests/test_fixtures.py`

**Interfaces:**
- Consumes: existing `build_all(out_dir) -> dict[str, Path]`, `_write_docx`, `OFFICIAL_RULES`.
- Produces: `build_all` gains key `"company_real_docx"` — a docx containing, in document order: heading paragraph `"General Information"` + GENERAL_INFO table; heading `"Instructions"` + INSTRUCTIONS table; heading `"JB.1.1 STIG HARDEING- SEVERITY HIGH"` + EX1 table (4 cols); heading `"IM-1.1 Settings related to Policy or Standards"` + EX2 table (10 cols). Module constants `EX1_HEADERS`, `EX1_ROWS`, `EX2_HEADERS`, `EX2_ROWS`, `INSTRUCTIONS_ROWS`, `GENERAL_INFO_ROWS` are importable by later tests.

- [ ] **Step 1: Write the failing test** (append to `tests/test_fixtures.py`)

```python
import docx as docx_lib
from fixtures import build_fixtures


def test_company_real_docx_built(tmp_path):
    paths = build_fixtures.build_all(tmp_path)
    p = paths["company_real_docx"]
    d = docx_lib.Document(str(p))
    assert len(d.tables) == 4
    texts = [para.text for para in d.paragraphs if para.text.strip()]
    assert "JB.1.1 STIG HARDEING- SEVERITY HIGH" in texts
    assert "IM-1.1 Settings related to Policy or Standards" in texts
    ex2 = d.tables[3]
    assert len(ex2.rows[0].cells) == len(build_fixtures.EX2_HEADERS)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_fixtures.py -v -k company_real`
Expected: FAIL with `KeyError: 'company_real_docx'`

- [ ] **Step 3: Implement** (append to `build_fixtures.py`; content reuses `OFFICIAL_RULES` wording so lexical shortlisting finds candidates in later tests)

```python
EX1_HEADERS = ["STIG REQUIREMENT", "DESCRIPTION", "COMMAND TO VERIFY",
               "APPROVED SETTING"]
EX1_ROWS = [
    ["Password reuse must be restricted",
     "Database users should not reuse recent passwords",
     "Run SHOW PARAMETER password_reuse_max", "9 or more"],
    ["Audit logging must be enabled",
     "Audit logging is required for all databases",
     "Verify audit logging is enabled", "enabled"],
]

EX2_HEADERS = ["", "System Value/Parameter", "Description",
               "REPORTING yes/no", "ENFORCING YES/NO",
               "ADOPT COMPANY STANDARDS DEVIATION/COMPLY",
               "COMPANY AGREED SETTING/COMMAND TO IMPLEMENT", "SEVERITY",
               "CURRENT SETTING", "REMARKS/JUSTIFICATION"]
EX2_ROWS = [
    ["1", "Session timeout must be enforced",
     "Idle session timeout is 15 minutes or less", "YES", "YES", "COMPLY",
     "Set session timeout to 15 minutes", "MEDIUM", "15", ""],
    ["2", "Minimum password length must be enforced",
     "Minimum password length is at least 14 characters", "YES", "NO",
     "DEVIATION", "Set minimum password length to 14", "HIGH", "10",
     "Legacy app cannot handle 14 characters"],
]

INSTRUCTIONS_ROWS = [
    ["Step", "Instruction"],
    ["1", "Fill in every table below before submission."],
    ["2", "Email the completed document to the security team."],
]

GENERAL_INFO_ROWS = [
    ["Field", "Value"],
    ["Application name", "Payments Gateway"],
    ["Team", "Platform Engineering"],
]


def _write_real_docx(path):
    d = docx.Document()
    sections = [
        ("General Information", GENERAL_INFO_ROWS[0], GENERAL_INFO_ROWS[1:]),
        ("Instructions", INSTRUCTIONS_ROWS[0], INSTRUCTIONS_ROWS[1:]),
        ("JB.1.1 STIG HARDEING- SEVERITY HIGH", EX1_HEADERS, EX1_ROWS),
        ("IM-1.1 Settings related to Policy or Standards", EX2_HEADERS,
         EX2_ROWS),
    ]
    for heading, headers, rows in sections:
        d.add_paragraph(heading)
        t = d.add_table(rows=1, cols=len(headers))
        for i, h in enumerate(headers):
            t.rows[0].cells[i].text = h
        for row in rows:
            cells = t.add_row().cells
            for i, val in enumerate(row[: len(headers)]):
                cells[i].text = val
    d.save(str(path))
```

And inside `build_all`, before `return paths`:

```python
    paths["company_real_docx"] = out / "company_real.docx"
    _write_real_docx(paths["company_real_docx"])
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_fixtures.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/tests/fixtures/build_fixtures.py stig-compare/tests/test_fixtures.py
git commit -m "test(stig-compare): real-format company fixtures (ex1, ex2, irrelevant tables)"
```

---

### Task 3: `skeleton.py` — lossless company skeleton dump

**Files:**
- Create: `stig-compare/scripts/skeleton.py`
- Test: `stig-compare/tests/test_skeleton.py`

**Interfaces:**
- Consumes: `common.fold_ws`; fixtures from Task 2.
- Produces: `skeleton.extract_skeleton(path) -> {"tables": [...], "warnings": [...]}` where each table is `{"table_index": int (1-based), "sheet_or_section": "document-body" | "sheet=<name>", "preceding_narrative": str, "header_row": [str], "rows": [{"row_index": int (1-based data rows), "cells": [str], "merged": bool}]}`. Raises `ValueError` on unsupported suffix. Do NOT touch `extract.py` in this task — `extract.extract_company` keeps working until Task 17 removes it.

- [ ] **Step 1: Write the failing tests** (create `tests/test_skeleton.py`)

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skeleton'`

- [ ] **Step 3: Implement** (create `scripts/skeleton.py`)

```python
"""Lossless company-submission skeleton dump. Zero interpretation.

Every table, row, and cell is preserved verbatim, along with the narrative
text (headings/paragraphs) immediately preceding each table. All
interpretation (table triage, column mapping, canonicalization) happens in
Claude passes downstream — this module must never gate, map, or drop
content.
"""
from pathlib import Path

import docx
from docx.oxml.ns import qn
import openpyxl

import common


def _row_cells(docx_row):
    return [c.text for c in docx_row.cells]


def _has_merged_cells(docx_row):
    if not docx_row.cells:
        return False
    for cell in docx_row.cells:
        tcpr = cell._element.find(qn("w:tcPr"))
        if tcpr is not None:
            if tcpr.find(qn("w:gridSpan")) is not None or \
                    tcpr.find(qn("w:vMerge")) is not None:
                return True
    return False


def _docx_skeleton(path):
    d = docx.Document(str(path))
    doc_tables = list(d.tables)
    tables, warnings = [], []
    narrative = []
    ti = 0
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = common.fold_ws(
                "".join(node.text or "" for node in child.iter(qn("w:t"))))
            if text:
                narrative.append(text)
        elif child.tag == qn("w:tbl"):
            table = doc_tables[ti]
            ti += 1
            rows = list(table.rows)
            header = _row_cells(rows[0]) if rows else []
            data = [{"row_index": i, "cells": _row_cells(r),
                     "merged": _has_merged_cells(r)}
                    for i, r in enumerate(rows[1:], start=1)]
            tables.append({"table_index": ti,
                           "sheet_or_section": "document-body",
                           "preceding_narrative": "\n".join(narrative),
                           "header_row": header, "rows": data})
            narrative = []
    if not tables:
        warnings.append({"code": "no-tables-found", "detail": "0 tables"})
    return {"tables": tables, "warnings": warnings}


def _xlsx_skeleton(path):
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    tables, warnings = [], []
    for ti, ws in enumerate(wb.worksheets, start=1):
        rows = [["" if c.value is None else str(c.value) for c in row]
                for row in ws.iter_rows()]
        header = rows[0] if rows else []
        data = [{"row_index": i, "cells": r, "merged": False}
                for i, r in enumerate(rows[1:], start=1)]
        tables.append({"table_index": ti,
                       "sheet_or_section": f"sheet={ws.title}",
                       "preceding_narrative": ws.title,
                       "header_row": header, "rows": data})
    if not tables:
        warnings.append({"code": "no-tables-found", "detail": "0 sheets"})
    return {"tables": tables, "warnings": warnings}


def extract_skeleton(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx_skeleton(path)
    if suffix == ".xlsx":
        return _xlsx_skeleton(path)
    raise ValueError(f"unsupported company file type: {suffix}")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/skeleton.py stig-compare/tests/test_skeleton.py
git commit -m "feat(stig-compare): lossless company skeleton dump with narrative capture"
```

---

### Task 4: `canonical.py` — record model, claim normalization, chunking, reconciliation

**Files:**
- Create: `stig-compare/scripts/canonical.py`
- Test: `stig-compare/tests/test_canonical.py`

**Interfaces:**
- Consumes: `common.record_id` (Task 1), `common.row_id`, `common.fold_ws`, `normalize.norm_text`.
- Produces (used by Tasks 5, 6, 11, 13, 14):
  - `CANONICAL_DATA_FIELDS` — the 8 data fields, in order: `stig_description`, `stig_objective_or_requirement`, `stig_command_or_value`, `company_approved_setting_or_expected_value`, `observed_value_or_evidence`, `company_compliance_claim`, `company_severity`, `remarks_or_justification`.
  - `MAPPING_TARGETS = set(CANONICAL_DATA_FIELDS) | {"extra_field", "ignore"}`
  - `TABLE_CLASSIFICATIONS = {"stig_relevant", "irrelevant", "uncertain"}`
  - `IRRELEVANT_REASONS = {"instructions", "general-info", "toc", "signoff", "other"}`
  - `DISPOSITIONS = {"record", "separator", "continuation"}`
  - `normalize_claim(text) -> "comply" | "deviation" | "unknown"`
  - `original_text(cells) -> str` (`" | ".join`)
  - `chunk_rows(rows, size=40) -> list[list[row]]` — never starts a chunk on a `merged: true` row.
  - `build_record(table, row, sub_index, fields, field_provenance, extra_fields, interpretation_note, context_grouping) -> dict` — the full canonical record (shape in the plan header), `status: "ok"`.
  - `failed_record(table, row, note) -> dict` — same shape, empty fields, `status: "extraction-failed"`, `notes: note`.
  - `reconcile(table, dispositions: dict[int, str]) -> [missing row_index...]`.

- [ ] **Step 1: Write the failing tests** (create `tests/test_canonical.py`)

```python
import canonical


TABLE = {"table_index": 3, "sheet_or_section": "document-body",
         "preceding_narrative": "JB.1.1 STIG HARDEING- SEVERITY HIGH",
         "header_row": ["STIG REQUIREMENT", "DESCRIPTION",
                        "COMMAND TO VERIFY", "APPROVED SETTING"],
         "rows": [{"row_index": 1,
                   "cells": ["Password reuse must be restricted",
                             "Users should not reuse passwords",
                             "Run SHOW PARAMETER password_reuse_max",
                             "9 or more"],
                   "merged": False}]}


def test_normalize_claim():
    assert canonical.normalize_claim("COMPLY") == "comply"
    assert canonical.normalize_claim("Deviation") == "deviation"
    assert canonical.normalize_claim(
        "DEVIATION - cannot comply") == "deviation"
    assert canonical.normalize_claim("Adopt company standards") == "comply"
    assert canonical.normalize_claim("") == "unknown"
    assert canonical.normalize_claim("see remarks") == "unknown"


def test_chunk_rows_respects_size_and_merged_rows():
    rows = [{"row_index": i, "cells": [], "merged": i == 41}
            for i in range(1, 44)]
    chunks = canonical.chunk_rows(rows, size=40)
    assert [len(c) for c in chunks] == [41, 2]
    assert chunks[1][0]["row_index"] == 42


def test_build_record_shape_and_ids():
    rec = canonical.build_record(
        TABLE, TABLE["rows"][0], 0,
        {"stig_objective_or_requirement": "Password reuse must be restricted",
         "company_compliance_claim": ""},
        {"stig_objective_or_requirement": {"row_index": 1, "cell_index": 0}},
        {"REPORTING yes/no": "YES"}, "note text",
        "JB.1.1 STIG HARDEING- SEVERITY HIGH")
    assert rec["record_id"].startswith("CR-")
    assert rec["row_id"].startswith("R-")
    assert rec["status"] == "ok"
    assert rec["claim_normalized"] == "unknown"
    assert rec["stig_description"] == ""
    assert rec["extra_fields"] == {"REPORTING yes/no": "YES"}
    assert rec["source_reference"]["sub_index"] == 0
    assert "password_reuse_max" in rec["original_company_text"]


def test_failed_record():
    rec = canonical.failed_record(TABLE, TABLE["rows"][0], "canonicalize-rejected")
    assert rec["status"] == "extraction-failed"
    assert rec["notes"] == "canonicalize-rejected"


def test_reconcile_reports_missing():
    assert canonical.reconcile(TABLE, {}) == [1]
    assert canonical.reconcile(TABLE, {1: "record"}) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_canonical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'canonical'`

- [ ] **Step 3: Implement** (create `scripts/canonical.py`)

```python
"""Canonical company record model (spec section 3) and mechanical helpers.

All interpretation happens in Claude passes; this module only defines the
target shape plus deterministic claim normalization, chunking, and count
reconciliation. Claim synonyms are intentionally minimal — extensions come
through the rules registry's equivalent-terminology category, never by
editing this file per-submission.
"""
import common
import normalize

CANONICAL_DATA_FIELDS = [
    "stig_description", "stig_objective_or_requirement",
    "stig_command_or_value", "company_approved_setting_or_expected_value",
    "observed_value_or_evidence", "company_compliance_claim",
    "company_severity", "remarks_or_justification"]

MAPPING_TARGETS = set(CANONICAL_DATA_FIELDS) | {"extra_field", "ignore"}
TABLE_CLASSIFICATIONS = {"stig_relevant", "irrelevant", "uncertain"}
IRRELEVANT_REASONS = {"instructions", "general-info", "toc", "signoff",
                      "other"}
DISPOSITIONS = {"record", "separator", "continuation"}


def normalize_claim(text):
    norm = normalize.norm_text(text)
    if not norm:
        return "unknown"
    if "deviat" in norm:
        return "deviation"
    if "comply" in norm or "compliant" in norm or "adopt" in norm:
        return "comply"
    return "unknown"


def original_text(cells):
    return " | ".join(str(c) for c in cells)


def chunk_rows(rows, size=40):
    """Chunks of <= size rows; a merged row never starts a chunk (it may be
    a continuation of the previous row and must stay in the same request)."""
    chunks, current = [], []
    for row in rows:
        if len(current) >= size and not row.get("merged"):
            chunks.append(current)
            current = []
        current.append(row)
    if current:
        chunks.append(current)
    return chunks


def build_record(table, row, sub_index, fields, field_provenance,
                 extra_fields, interpretation_note, context_grouping):
    raw = original_text(row["cells"])
    rec = {f: "" for f in CANONICAL_DATA_FIELDS}
    for k, v in (fields or {}).items():
        rec[k] = common.fold_ws(v)
    rec["record_id"] = common.record_id(
        table["table_index"], row["row_index"], sub_index, raw)
    rec["row_id"] = common.row_id(table["table_index"], row["row_index"], raw)
    rec["context_grouping"] = context_grouping or ""
    rec["claim_normalized"] = normalize_claim(rec["company_compliance_claim"])
    rec["extra_fields"] = dict(extra_fields or {})
    rec["interpretation_note"] = interpretation_note or ""
    rec["field_provenance"] = dict(field_provenance or {})
    rec["source_reference"] = {
        "table_index": table["table_index"], "row_index": row["row_index"],
        "sub_index": sub_index,
        "sheet_or_section": table["sheet_or_section"],
        "table_title": context_grouping or ""}
    rec["original_company_text"] = raw
    rec["status"] = "ok"
    rec["notes"] = ""
    return rec


def failed_record(table, row, note):
    rec = build_record(table, row, 0, {}, {}, {}, "", "")
    rec["status"] = "extraction-failed"
    rec["notes"] = note
    return rec


def reconcile(table, dispositions):
    """dispositions: {row_index(int): disposition}. Returns row indexes
    present in the table but never accounted for by any response."""
    expected = {r["row_index"] for r in table["rows"]}
    return sorted(expected - set(dispositions))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_canonical.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/canonical.py stig-compare/tests/test_canonical.py
git commit -m "feat(stig-compare): canonical record model, claim normalization, chunking"
```

---

### Task 5: `validate.py` — table-mapping and canonicalize validators

**Files:**
- Modify: `stig-compare/scripts/validate.py`
- Test: `stig-compare/tests/test_validate.py`

**Interfaces:**
- Consumes: `canonical` constants (Task 4), existing `quote_exists`, `_require`, `common.fold_ws`.
- Produces (used by Task 11):
  - `validate.validate_table_mapping_output(resp, table) -> [error_code...]`
  - `validate.validate_canonicalize_output(resp, table, chunk_row_indexes) -> [error_code...]` — enforces per-chunk completeness (every chunk row accounted exactly once — this IS the spec's count-reconciliation guarantee), legal dispositions, sub_index sequence 0..n-1, and cell-verbatim fields against `field_provenance`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_validate.py`)

```python
import canonical
import validate

_TABLE = {"table_index": 1, "sheet_or_section": "document-body",
          "preceding_narrative": "JB.1.1 STIG HARDEING- SEVERITY HIGH",
          "header_row": ["STIG REQUIREMENT", "DESCRIPTION"],
          "rows": [
              {"row_index": 1, "cells": ["Password reuse restricted",
                                          "No password reuse"], "merged": False},
              {"row_index": 2, "cells": ["", ""], "merged": False}]}

_GOOD_MAPPING = {"table_index": 1, "classification": "stig_relevant",
                 "irrelevant_reason": "",
                 "column_mapping": {"0": "stig_objective_or_requirement",
                                    "1": "stig_description"},
                 "context_grouping": "JB.1.1 STIG HARDEING- SEVERITY HIGH"}


def test_table_mapping_valid():
    assert validate.validate_table_mapping_output(_GOOD_MAPPING, _TABLE) == []


def test_table_mapping_rejects_bad_enum_and_duplicate_fields():
    bad = dict(_GOOD_MAPPING, classification="maybe")
    assert "bad-classification" in validate.validate_table_mapping_output(bad, _TABLE)
    dup = dict(_GOOD_MAPPING, column_mapping={
        "0": "stig_description", "1": "stig_description"})
    assert "duplicate-field-mapping" in validate.validate_table_mapping_output(dup, _TABLE)


def test_table_mapping_irrelevant_needs_reason_and_no_columns_ok():
    irr = dict(_GOOD_MAPPING, classification="irrelevant",
               irrelevant_reason="instructions", column_mapping={})
    assert validate.validate_table_mapping_output(irr, _TABLE) == []
    irr_bad = dict(irr, irrelevant_reason="")
    assert "bad-irrelevant-reason" in validate.validate_table_mapping_output(irr_bad, _TABLE)


def test_table_mapping_relevant_requires_canonical_column():
    none_mapped = dict(_GOOD_MAPPING, column_mapping={"0": "ignore"})
    assert "no-canonical-columns" in validate.validate_table_mapping_output(
        none_mapped, _TABLE)


def test_table_mapping_context_grouping_must_be_verbatim():
    bad = dict(_GOOD_MAPPING, context_grouping="Improved Section Title")
    assert "context-grouping-not-verbatim" in \
        validate.validate_table_mapping_output(bad, _TABLE)


def _canon_resp(rows):
    return {"chunk_id": "T1-C0", "rows": rows}


def test_canonicalize_valid_and_complete():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0,
             "fields": {"stig_objective_or_requirement":
                        "Password reuse restricted"},
             "field_provenance": {"stig_objective_or_requirement":
                                  {"row_index": 1, "cell_index": 0}},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    assert validate.validate_canonicalize_output(resp, _TABLE, [1, 2]) == []


def test_canonicalize_rejects_missing_row():
    resp = _canon_resp([{"row_index": 1, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("missing-rows") for e in errs)


def test_canonicalize_rejects_paraphrase():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0,
             "fields": {"stig_objective_or_requirement":
                        "Passwords may not be reused"},
             "field_provenance": {"stig_objective_or_requirement":
                                  {"row_index": 1, "cell_index": 0}},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("not-cell-verbatim") for e in errs)


def test_canonicalize_rejects_bad_sub_index_sequence():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 1, "fields": {}, "field_provenance": {},
             "interpretation_note": ""}]},
        {"row_index": 2, "disposition": "separator"}])
    errs = validate.validate_canonicalize_output(resp, _TABLE, [1, 2])
    assert any(e.startswith("bad-sub-index") for e in errs)


def test_canonicalize_interpretation_note_is_free_text():
    resp = _canon_resp([
        {"row_index": 1, "disposition": "record", "records": [
            {"sub_index": 0, "fields": {}, "field_provenance": {},
             "interpretation_note": "This wording implies a deviation."}]},
        {"row_index": 2, "disposition": "separator"}])
    assert validate.validate_canonicalize_output(resp, _TABLE, [1, 2]) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_validate.py -v -k "table_mapping or canonicalize"`
Expected: FAIL with `AttributeError: module 'validate' has no attribute 'validate_table_mapping_output'`

- [ ] **Step 3: Implement** (append to `scripts/validate.py`; add `import canonical` at the top, after `import common`)

```python
def validate_table_mapping_output(resp, table):
    errs = _require(resp, ["table_index", "classification",
                           "irrelevant_reason", "column_mapping",
                           "context_grouping"])
    if errs:
        return errs
    if resp["table_index"] != table["table_index"]:
        return ["wrong-table-index"]
    cls = resp["classification"]
    if cls not in canonical.TABLE_CLASSIFICATIONS:
        return ["bad-classification"]
    if cls == "irrelevant" and \
            resp["irrelevant_reason"] not in canonical.IRRELEVANT_REASONS:
        errs.append("bad-irrelevant-reason")
    cm = resp["column_mapping"]
    if not isinstance(cm, dict):
        return errs + ["bad-column-mapping"]
    ncols = max(len(table["header_row"]),
                max((len(r["cells"]) for r in table["rows"]), default=0))
    seen_fields = set()
    for k, v in cm.items():
        if not (isinstance(k, str) and k.isdigit() and int(k) < ncols):
            errs.append("bad-column-index")
            break
        if v not in canonical.MAPPING_TARGETS:
            errs.append("bad-mapping-target")
            break
        if v in canonical.CANONICAL_DATA_FIELDS:
            if v in seen_fields:
                errs.append("duplicate-field-mapping")
                break
            seen_fields.add(v)
    if cls in ("stig_relevant", "uncertain") and not errs and not seen_fields:
        errs.append("no-canonical-columns")
    cg = resp["context_grouping"]
    if not isinstance(cg, str):
        errs.append("bad-context-grouping")
    elif common.fold_ws(cg):
        context_src = " ".join(
            [table.get("preceding_narrative", ""),
             table.get("sheet_or_section", "")] +
            [str(h) for h in table.get("header_row", [])])
        if not quote_exists(cg, context_src):
            errs.append("context-grouping-not-verbatim")
    return errs


def _validate_canon_record(rec, row_index, cells_by_index):
    if not isinstance(rec, dict):
        return [f"bad-record:{row_index}"]
    fields = rec.get("fields")
    prov = rec.get("field_provenance")
    note = rec.get("interpretation_note", "")
    if not isinstance(fields, dict) or not isinstance(prov, dict) or \
            not isinstance(note, str):
        return [f"bad-record:{row_index}"]
    for name, value in fields.items():
        if name not in canonical.CANONICAL_DATA_FIELDS:
            return [f"unknown-field:{name}"]
        if not isinstance(value, str):
            return [f"bad-field-type:{name}"]
        if not common.fold_ws(value):
            continue
        p = prov.get(name)
        if not (isinstance(p, dict) and isinstance(p.get("row_index"), int)
                and isinstance(p.get("cell_index"), int)):
            return [f"missing-provenance:{name}"]
        cells = cells_by_index.get(p["row_index"])
        if cells is None or not (0 <= p["cell_index"] < len(cells)):
            return [f"bad-provenance:{name}"]
        if not quote_exists(value, cells[p["cell_index"]]):
            return [f"not-cell-verbatim:{name}"]
    return []


def validate_canonicalize_output(resp, table, chunk_row_indexes):
    errs = _require(resp, ["chunk_id", "rows"])
    if errs:
        return errs
    rows = resp["rows"]
    if not isinstance(rows, list):
        return ["bad-rows"]
    cells_by_index = {r["row_index"]: r["cells"] for r in table["rows"]}
    chunk_set = set(chunk_row_indexes)
    seen = set()
    for entry in rows:
        if not isinstance(entry, dict):
            return ["bad-row-entry"]
        ri = entry.get("row_index")
        if ri not in chunk_set or ri in seen:
            return ["bad-row-index"]
        seen.add(ri)
        disp = entry.get("disposition")
        if disp not in canonical.DISPOSITIONS:
            return ["bad-disposition"]
        if disp == "separator":
            st = entry.get("separator_text", "")
            if not isinstance(st, str):
                return [f"bad-separator:{ri}"]
            if common.fold_ws(st) and not quote_exists(
                    st, canonical.original_text(cells_by_index[ri])):
                return [f"separator-not-verbatim:{ri}"]
        if disp == "record":
            recs = entry.get("records")
            if not isinstance(recs, list) or not recs:
                return [f"missing-records:{ri}"]
            for pos, rec in enumerate(recs):
                if not isinstance(rec, dict) or rec.get("sub_index") != pos:
                    return [f"bad-sub-index:{ri}"]
                rerrs = _validate_canon_record(rec, ri, cells_by_index)
                if rerrs:
                    return rerrs
    if seen != chunk_set:
        return [f"missing-rows:{len(chunk_set - seen)}"]
    return []
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_validate.py -v`
Expected: all PASS (existing tests untouched)

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/validate.py stig-compare/tests/test_validate.py
git commit -m "feat(stig-compare): validators for table mapping and cell-verbatim canonicalization"
```

---

### Task 6: `validate.py` — multi-select matching and sweep validators

**Files:**
- Modify: `stig-compare/scripts/validate.py`
- Test: `stig-compare/tests/test_validate.py`

**Interfaces:**
- Consumes: existing `quote_exists`, `_rule_text`, `_require`.
- Produces (used by Tasks 12, 13):
  - `validate.validate_match_output(output, shortlist_ids, record, rules_by_id) -> [errs]` — REWRITE. New `_MATCH_KEYS = ["record_id", "decision", "selections", "ambiguous_rule_ids", "basis"]`. `decision: "match"` requires a non-empty `selections` list of `{"rule_id", "row_quote", "rule_quote"}` — each rule_id ∈ shortlist, no duplicates, both quotes non-empty and verbatim (row quote against `record["original_company_text"]`, rule quote against the rule's title/check/fix text).
  - `validate.validate_sweep_output(output, batch_record_ids, index_rule_ids) -> [errs]`.
- Breakage note: `pipeline.py` still calls the old signature until Task 12; `tests/test_pipeline.py` / `test_end_to_end.py` will fail from this task until Tasks 10–14 land. That is expected — run only the named test files per task from here through Task 14.

- [ ] **Step 1: Replace the old matching-validator tests.** In `tests/test_validate.py`, delete any existing tests of `validate_match_output` (they use the single-select schema) and append:

```python
_REC = {"record_id": "CR-1", "original_company_text":
        "Password reuse must be restricted | Run SHOW PARAMETER password_reuse_max"}
_RULES = {"V-1001": {"rule_id": "V-1001",
                     "title": "Password reuse must be restricted",
                     "check_text": "Run SHOW PARAMETER password_reuse_max",
                     "fix_text": "Set password_reuse_max to 9 or more."},
          "V-1003": {"rule_id": "V-1003", "title": "Audit logging enabled",
                     "check_text": "Verify audit logging", "fix_text": ""}}
_SHORT = ["V-1001", "V-1003"]


def _match_resp(**kw):
    base = {"record_id": "CR-1", "decision": "match",
            "selections": [{"rule_id": "V-1001",
                            "row_quote": "Run SHOW PARAMETER password_reuse_max",
                            "rule_quote": "Run SHOW PARAMETER password_reuse_max"}],
            "ambiguous_rule_ids": [], "basis": "same parameter"}
    base.update(kw)
    return base


def test_match_multi_select_valid():
    assert validate.validate_match_output(_match_resp(), _SHORT, _REC, _RULES) == []


def test_match_two_selections_valid():
    two = _match_resp(selections=[
        {"rule_id": "V-1001",
         "row_quote": "Run SHOW PARAMETER password_reuse_max",
         "rule_quote": "Run SHOW PARAMETER password_reuse_max"},
        {"rule_id": "V-1003",
         "row_quote": "Password reuse must be restricted",
         "rule_quote": "Verify audit logging"}])
    assert validate.validate_match_output(two, _SHORT, _REC, _RULES) == []


def test_match_rejects_empty_selections_and_duplicates():
    assert "no-selections" in validate.validate_match_output(
        _match_resp(selections=[]), _SHORT, _REC, _RULES)
    dup = _match_resp()
    dup["selections"] = dup["selections"] * 2
    assert "duplicate-selection" in validate.validate_match_output(
        dup, _SHORT, _REC, _RULES)


def test_match_rejects_off_shortlist_and_bad_quotes():
    off = _match_resp()
    off["selections"][0]["rule_id"] = "V-9999"
    assert "rule-not-in-shortlist" in validate.validate_match_output(
        off, _SHORT, _REC, _RULES)
    bad = _match_resp()
    bad["selections"][0]["row_quote"] = "invented text"
    assert "row-quote-not-found" in validate.validate_match_output(
        bad, _SHORT, _REC, _RULES)


def test_match_none_and_ambiguous_still_work():
    none = _match_resp(decision="none", selections=[])
    assert validate.validate_match_output(none, _SHORT, _REC, _RULES) == []
    amb = _match_resp(decision="ambiguous", selections=[],
                      ambiguous_rule_ids=["V-1001", "V-1003"])
    assert validate.validate_match_output(amb, _SHORT, _REC, _RULES) == []
    amb1 = _match_resp(decision="ambiguous", selections=[],
                       ambiguous_rule_ids=["V-1001"])
    assert "ambiguous-needs-two" in validate.validate_match_output(
        amb1, _SHORT, _REC, _RULES)


def test_sweep_output():
    good = {"sweep_id": "S0",
            "proposals": [{"record_id": "CR-1", "rule_id": "V-1003"}]}
    assert validate.validate_sweep_output(good, {"CR-1"}, {"V-1003"}) == []
    empty = {"sweep_id": "S0", "proposals": []}
    assert validate.validate_sweep_output(empty, {"CR-1"}, {"V-1003"}) == []
    bad = {"sweep_id": "S0",
           "proposals": [{"record_id": "CR-2", "rule_id": "V-1003"}]}
    assert "bad-proposal" in validate.validate_sweep_output(
        bad, {"CR-1"}, {"V-1003"})
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_validate.py -v -k "match or sweep"`
Expected: FAIL (`missing-key:record_id` errors from the old implementation / missing `validate_sweep_output`)

- [ ] **Step 3: Implement.** In `scripts/validate.py`, replace `_MATCH_KEYS` and the whole `validate_match_output` with:

```python
_MATCH_KEYS = ["record_id", "decision", "selections", "ambiguous_rule_ids",
               "basis"]


def validate_match_output(output, shortlist_ids, record, rules_by_id):
    errs = _require(output, _MATCH_KEYS)
    if errs:
        return errs
    decision = output["decision"]
    if decision not in ("match", "none", "ambiguous"):
        return ["bad-decision"]
    if decision == "match":
        sels = output["selections"]
        if not isinstance(sels, list) or not sels:
            return ["no-selections"]
        seen = set()
        for sel in sels:
            if not isinstance(sel, dict):
                return ["bad-selection"]
            rid = sel.get("rule_id")
            if rid not in shortlist_ids:
                errs.append("rule-not-in-shortlist")
                continue
            if rid in seen:
                errs.append("duplicate-selection")
                continue
            seen.add(rid)
            rq = sel.get("row_quote")
            if not isinstance(rq, str) or not common.fold_ws(rq) or \
                    not quote_exists(rq, record["original_company_text"]):
                errs.append("row-quote-not-found")
            uq = sel.get("rule_quote")
            if not isinstance(uq, str) or not common.fold_ws(uq) or \
                    rid not in rules_by_id or \
                    not quote_exists(uq, _rule_text(rules_by_id[rid])):
                errs.append("rule-quote-not-found")
    elif decision == "ambiguous":
        ids = output["ambiguous_rule_ids"]
        if not isinstance(ids, list) or len(ids) < 2 or \
                not set(ids) <= set(shortlist_ids):
            errs.append("ambiguous-needs-two")
    return errs


def validate_sweep_output(output, batch_record_ids, index_rule_ids):
    errs = _require(output, ["sweep_id", "proposals"])
    if errs:
        return errs
    props = output["proposals"]
    if not isinstance(props, list):
        return ["bad-proposals"]
    for p in props:
        if not isinstance(p, dict) or \
                p.get("record_id") not in batch_record_ids or \
                p.get("rule_id") not in index_rule_ids:
            errs.append("bad-proposal")
            break
    return errs
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_validate.py tests/test_canonical.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/validate.py stig-compare/tests/test_validate.py
git commit -m "feat(stig-compare): multi-select match validation and sweep proposal validation"
```

---

### Task 7: `candidates.py` — record keying and multi-match shape

**Files:**
- Modify: `stig-compare/scripts/candidates.py`
- Test: `stig-compare/tests/test_candidates.py`

**Interfaces:**
- Consumes: canonical records with `record_id` + `status` (Task 4).
- Produces (used by Tasks 11–14): `candidates.generate(company_records, official_rules, k=5, floor=0.05, margin=0.15)` now returns per record: `{"record_id", "tier": None|"T0"|"T1", "matched_rule_ids": [...], "margin_flag", "candidates"}`. Only `status == "ok"` records are scored (the `needs-structuring` status no longer exists). Scoring features, weights, stopwords, T0/T1 logic are UNCHANGED.

- [ ] **Step 1: Update the tests.** In `tests/test_candidates.py`, update every constructed row dict: rename key `row_id` → `record_id` (keep values), keep `status: "ok"`; update every assertion reading `result["row_id"]` → `result["record_id"]` and `result["matched_rule_id"] == X` → `result["matched_rule_ids"] == [X]` (and `is None` → `== []`). Remove/replace any test that feeds a `needs-structuring` row expecting it to be scored — replace with:

```python
def test_non_ok_records_are_skipped(official_rules):
    row = {"record_id": "CR-x", "status": "extraction-failed",
           "original_company_text": "Run SHOW PARAMETER password_reuse_max",
           "context_grouping": ""}
    assert candidates.generate([row], official_rules) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_candidates.py -v`
Expected: FAIL with `KeyError: 'record_id'`

- [ ] **Step 3: Implement.** In `scripts/candidates.py` `generate()`:
  - Change the status gate to `if row.get("status") != "ok": continue`.
  - Change the result skeleton to `{"record_id": row["record_id"], "tier": None, "matched_rule_ids": [], "margin_flag": False, "candidates": shortlist}`.
  - T0 branch: `result["matched_rule_ids"] = [m.group(0).upper()]` (tier `"T0"` as before).
  - T1 branch: `result["matched_rule_ids"] = [hits[0]]` (tier `"T1"` as before).
  - Update the module docstring's first line to mention records.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_candidates.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/candidates.py stig-compare/tests/test_candidates.py
git commit -m "feat(stig-compare): candidates keyed by record_id with multi-match shape"
```

---

### Task 8: `coverage.py` rewrite — skeleton-row buckets

**Files:**
- Modify: `stig-compare/scripts/coverage.py` (full rewrite)
- Test: `stig-compare/tests/test_coverage.py` (full rewrite)

**Interfaces:**
- Consumes: skeleton tables (Task 3 shape), table_state records (plan header shape), canonical records (Task 4), match_state records (plan header shape).
- Produces (used by Task 14): `coverage.compute(skeleton_tables, table_state_by_index, company_records, match_results, ignored_row_ids) -> {"company", "official", "warnings", "ok"}`.
  - `company` buckets: `total` (all skeleton data rows), `matched`, `ambiguous`, `unmatched`, `ignored_irrelevant_table`, `ignored_by_rule`, `separator`, `extraction_failed`. Buckets must sum to `total` or `ok` is False.
  - Row bucketing: table `classification == "irrelevant"` → all its rows `ignored_irrelevant_table`; classification not in `{"stig_relevant", "uncertain", "irrelevant"}` (i.e. `None`, `"mapping-failed"`, `"mapping-pass-not-run"`) → all its rows `extraction_failed`; else per `row_dispositions`: `separator` → `separator`; `continuation` → same bucket as its `parent_of` row (fallback `extraction_failed` if the parent is unknown); `record` (or missing disposition) → aggregate over that row's canonical records: no records → `extraction_failed`; any record in `ignored_row_ids` (by record_id or row_id) → `ignored_by_rule`; all records `extraction-failed` → `extraction_failed`; any record with tier T0/T1/T2 and non-empty `matched_rule_ids` → `matched`; else any T3 → `ambiguous`; else `unmatched`.
  - `official`: `matched_rules` counted over the UNION of `matched_rule_ids` lists; `duplicate_coverage_rule_ids` = rule ids matched by more than one record.
  - Warnings: `coverage-sum-mismatch`, `extraction-failures`, and `low-coverage-red-banner` when `(extraction_failed + ignored_by_rule) / total > 0.10` — `ignored_irrelevant_table` is EXCLUDED from the red-banner ratio (spec §6) but still surfaced via the triage panel.
  - `RED_BANNER_THRESHOLD = 0.10` stays module-level.

- [ ] **Step 1: Write the failing tests** (replace `tests/test_coverage.py` content)

```python
import coverage


def _table(ti, n_rows, cls="stig_relevant", disps=None, parents=None):
    return ({"table_index": ti, "sheet_or_section": "document-body",
             "preceding_narrative": "", "header_row": ["A"],
             "rows": [{"row_index": i, "cells": ["x"], "merged": False}
                      for i in range(1, n_rows + 1)]},
            {"table_index": ti, "classification": cls,
             "irrelevant_reason": "", "column_mapping": {},
             "context_grouping": "", "mapping_failures": 0,
             "row_dispositions": disps or {}, "parent_of": parents or {},
             "chunks": {}})


def _rec(rid, ti, ri, status="ok", sub=0):
    return {"record_id": rid, "row_id": "R-" + rid, "status": status,
            "source_reference": {"table_index": ti, "row_index": ri,
                                 "sub_index": sub}}


def _match(rid, tier, matched=(), ):
    return {"record_id": rid, "tier": tier,
            "matched_rule_ids": list(matched), "candidates": []}


OFFICIAL = [{"rule_id": "V-1"}, {"rule_id": "V-2"}, {"rule_id": "V-3"}]


def test_buckets_sum_and_classify():
    t1, ts1 = _table(1, 2, cls="irrelevant")
    t2, ts2 = _table(2, 4, disps={"1": "record", "2": "separator",
                                   "3": "record", "4": "record"})
    skeleton = [t1, t2]
    tstate = {1: ts1, 2: ts2}
    records = [_rec("a", 2, 1), _rec("b", 2, 3),
               _rec("c", 2, 4, status="extraction-failed")]
    matches = [_match("a", "T2", ["V-1", "V-2"]), _match("b", "T3")]
    out = coverage.compute(skeleton, tstate, records, OFFICIAL, matches, set())
    assert out["ok"]
    c = out["company"]
    assert c["total"] == 6
    assert c["ignored_irrelevant_table"] == 2
    assert c["separator"] == 1
    assert c["matched"] == 1 and c["ambiguous"] == 1
    assert c["extraction_failed"] == 1
    assert out["official"]["addressed"] == 2
    assert out["official"]["unaddressed"] == 1


def test_continuation_takes_parent_bucket_and_split_rows_aggregate():
    t, ts = _table(1, 2, disps={"1": "record", "2": "continuation"},
                   parents={"2": 1})
    records = [_rec("a", 1, 1, sub=0), _rec("b", 1, 1, sub=1)]
    matches = [_match("a", "T4"), _match("b", "T2", ["V-1"])]
    out = coverage.compute([t], {1: ts}, records, OFFICIAL, matches, set())
    assert out["company"]["matched"] == 2  # row 1 aggregates to matched; row 2 follows parent
    assert out["ok"]


def test_unanswered_table_rows_are_extraction_failed():
    t, ts = _table(1, 3, cls=None)
    out = coverage.compute([t], {1: ts}, [], OFFICIAL, [], set())
    assert out["company"]["extraction_failed"] == 3
    assert out["ok"]


def test_red_banner_excludes_irrelevant_tables():
    t1, ts1 = _table(1, 50, cls="irrelevant")
    t2, ts2 = _table(2, 2, disps={"1": "record", "2": "record"})
    records = [_rec("a", 2, 1), _rec("b", 2, 2)]
    matches = [_match("a", "T2", ["V-1"]), _match("b", "T2", ["V-2"])]
    out = coverage.compute([t1, t2], {1: ts1, 2: ts2}, records, OFFICIAL,
                           matches, set())
    assert not any(w["code"] == "low-coverage-red-banner"
                   for w in out["warnings"])


def test_duplicate_coverage_flagged():
    t, ts = _table(1, 2, disps={"1": "record", "2": "record"})
    records = [_rec("a", 1, 1), _rec("b", 1, 2)]
    matches = [_match("a", "T2", ["V-1"]), _match("b", "T2", ["V-1"])]
    out = coverage.compute([t], {1: ts}, records, OFFICIAL, matches, set())
    assert out["official"]["duplicate_coverage_rule_ids"] == ["V-1"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_coverage.py -v`
Expected: FAIL (TypeError on the new signature / KeyError on new buckets)

- [ ] **Step 3: Implement** (replace `scripts/coverage.py` content)

```python
"""Coverage accounting over skeleton rows (spec section 6). Pure arithmetic."""
from collections import Counter

RED_BANNER_THRESHOLD = 0.10
_MATCHED_TIERS = ("T0", "T1", "T2")
_PROCESSABLE = ("stig_relevant", "uncertain")


def _bucket_for_records(records, match_by_record, ignored_row_ids):
    if not records:
        return "extraction_failed"
    if any(r["record_id"] in ignored_row_ids or
           r.get("row_id") in ignored_row_ids for r in records):
        return "ignored_by_rule"
    ok_records = [r for r in records if r.get("status") == "ok"]
    if not ok_records:
        return "extraction_failed"
    tiers = []
    for r in ok_records:
        m = match_by_record.get(r["record_id"])
        if m and m.get("tier") in _MATCHED_TIERS and m.get("matched_rule_ids"):
            return "matched"
        tiers.append(m.get("tier") if m else None)
    if any(t == "T3" for t in tiers):
        return "ambiguous"
    return "unmatched"


def compute(skeleton_tables, table_state_by_index, company_records,
            official_rules, match_results, ignored_row_ids):
    match_by_record = {m["record_id"]: m for m in match_results}
    recs_by_row = {}
    for rec in company_records:
        sr = rec["source_reference"]
        recs_by_row.setdefault(
            (sr["table_index"], sr["row_index"]), []).append(rec)

    c = Counter()
    row_buckets = {}
    continuations = []
    total = 0
    for table in skeleton_tables:
        ti = table["table_index"]
        ts = table_state_by_index.get(ti, {})
        cls = ts.get("classification")
        disps = {int(k): v
                 for k, v in (ts.get("row_dispositions") or {}).items()}
        parents = {int(k): v for k, v in (ts.get("parent_of") or {}).items()}
        for row in table["rows"]:
            total += 1
            ri = row["row_index"]
            if cls == "irrelevant":
                c["ignored_irrelevant_table"] += 1
                continue
            if cls not in _PROCESSABLE:
                c["extraction_failed"] += 1
                continue
            disp = disps.get(ri)
            if disp == "separator":
                c["separator"] += 1
                continue
            if disp == "continuation":
                continuations.append((ti, parents.get(ri)))
                continue
            bucket = _bucket_for_records(recs_by_row.get((ti, ri), []),
                                         match_by_record, ignored_row_ids)
            row_buckets[(ti, ri)] = bucket
            c[bucket] += 1
    for ti, parent in continuations:
        c[row_buckets.get((ti, parent), "extraction_failed")] += 1

    company = {"total": total, "matched": c["matched"],
               "ambiguous": c["ambiguous"], "unmatched": c["unmatched"],
               "ignored_irrelevant_table": c["ignored_irrelevant_table"],
               "ignored_by_rule": c["ignored_by_rule"],
               "separator": c["separator"],
               "extraction_failed": c["extraction_failed"]}

    matched_rules = Counter()
    for m in match_results:
        if m.get("tier") in _MATCHED_TIERS:
            for rid in m.get("matched_rule_ids", []):
                matched_rules[rid] += 1
    official_ids = {r["rule_id"] for r in official_rules}
    addressed = sum(1 for rid in official_ids if matched_rules.get(rid))
    official = {"total": len(official_ids), "addressed": addressed,
                "unaddressed": len(official_ids) - addressed,
                "duplicate_coverage_rule_ids":
                    sorted(rid for rid, n in matched_rules.items() if n > 1)}

    warnings = []
    bucket_sum = sum(v for k, v in company.items() if k != "total")
    ok = bucket_sum == total
    if not ok:
        warnings.append({"code": "coverage-sum-mismatch",
                         "detail": f"buckets={bucket_sum} total={total}"})
    if company["extraction_failed"] > 0:
        warnings.append({"code": "extraction-failures",
                         "detail": str(company["extraction_failed"])})
    bad = company["extraction_failed"] + company["ignored_by_rule"]
    if total and bad / total > RED_BANNER_THRESHOLD:
        warnings.append({"code": "low-coverage-red-banner",
                         "detail": f"{bad}/{total} rows not compared"})
    return {"company": company, "official": official,
            "warnings": warnings, "ok": ok}
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_coverage.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/coverage.py stig-compare/tests/test_coverage.py
git commit -m "feat(stig-compare): coverage over skeleton rows with triage-aware buckets"
```

---

### Task 9: Prompts — `table_mapping.md`, `canonicalize.md`, `sweep.md`, rewrite `matching.md`

**Files:**
- Create: `stig-compare/prompts/table_mapping.md`, `stig-compare/prompts/canonicalize.md`, `stig-compare/prompts/sweep.md`
- Modify: `stig-compare/prompts/matching.md`, `stig-compare/prompts/semantic_compare.md`
- Test: `stig-compare/tests/test_prompts_and_skill.py`

**Interfaces:**
- Consumes: request shapes emitted by Tasks 10–13; validator contracts from Tasks 5–6.
- Produces: prompt contracts Claude follows. Every prompt keeps the existing STRICT RULES preamble style (copy the 6-bullet block from `prompts/matching.md` lines 3–12 verbatim as the opener of each new prompt). `prompts/structuring.md` is NOT deleted yet (Task 17).

- [ ] **Step 1: Update the failing test.** In `tests/test_prompts_and_skill.py`: change `PROMPTS` to `["table_mapping.md", "canonicalize.md", "sweep.md", "matching.md", "semantic_compare.md", "validator.md"]`. In `test_prompts_state_their_schemas`, replace the matching-key list with `["record_id", "decision", "selections", "ambiguous_rule_ids", "rule_id", "row_quote", "rule_quote", "basis"]` and add:

```python
    table_mapping = (PKG / "prompts" / "table_mapping.md").read_text(encoding="utf-8")
    for key in ["table_index", "classification", "irrelevant_reason",
                "column_mapping", "context_grouping"]:
        assert f'"{key}"' in table_mapping
    canonicalize = (PKG / "prompts" / "canonicalize.md").read_text(encoding="utf-8")
    for key in ["chunk_id", "row_index", "disposition", "records",
                "sub_index", "fields", "field_provenance",
                "interpretation_note", "separator_text"]:
        assert f'"{key}"' in canonicalize
    sweep = (PKG / "prompts" / "sweep.md").read_text(encoding="utf-8")
    for key in ["sweep_id", "proposals"]:
        assert f'"{key}"' in sweep
    assert "candidates, not matches" in sweep
```

Also change `test_all_prompts_exist_with_strict_preamble` — no change needed beyond the new `PROMPTS` list.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_prompts_and_skill.py -v`
Expected: FAIL with `FileNotFoundError` on `table_mapping.md`

- [ ] **Step 3: Write the prompts.**

`prompts/table_mapping.md`:

````markdown
# Table Mapping Prompt (Phase 1: triage + column mapping)

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `table_mapping_requests.jsonl`:

- `table_index` (int) — echo back unchanged.
- `sheet_or_section` (string), `preceding_narrative` (string) — the heading
  and paragraph text that appeared immediately before this table in the
  document.
- `header_row` (array of strings) — the table's first row.
- `sample_rows` (array of arrays) — up to the first 5 data rows.
- `row_count` (int) — total data rows in the table.
- `header_hints` (object) — canonical field -> known header synonyms.
  Hints only; your semantic judgment of the actual headers wins.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "table_index": 1,
  "classification": "stig_relevant | irrelevant | uncertain",
  "irrelevant_reason": "instructions | general-info | toc | signoff | other",
  "column_mapping": {"0": "stig_objective_or_requirement", "1": "ignore"},
  "context_grouping": "..."
}
```

## Decision guide

- `classification`: `stig_relevant` when the table's rows each describe a
  security setting, requirement, parameter, or hardening control.
  `irrelevant` for instructions, general information, table-of-contents,
  sign-off/approval, or revision-history tables — set `irrelevant_reason`.
  `uncertain` when you genuinely cannot tell; uncertain tables ARE
  processed, then flagged for human review — prefer `uncertain` over a
  wrong `irrelevant`, because `irrelevant` removes every row from
  comparison.
- `column_mapping` keys are column indexes as strings ("0"-based). Values
  must be one of: `stig_description`, `stig_objective_or_requirement`,
  `stig_command_or_value`, `company_approved_setting_or_expected_value`,
  `observed_value_or_evidence`, `company_compliance_claim`,
  `company_severity`, `remarks_or_justification`, `extra_field`, `ignore`.
- Guidance for real-world headers: "Command to Verify" / "System
  Value/Parameter" -> `stig_command_or_value`; "Approved Setting" /
  "Company Agreed Setting/Command to Implement" ->
  `company_approved_setting_or_expected_value`; "Current Setting" /
  "Actual Value" -> `observed_value_or_evidence`; "Adopt Company Standards
  Deviation/Comply" -> `company_compliance_claim`; "Severity" ->
  `company_severity`; "Remarks/Justification" ->
  `remarks_or_justification`; yes/no process columns like "Reporting" or
  "Enforcing" -> `extra_field`; row-number columns -> `ignore`.
- Map each canonical field to AT MOST one column. Unmappable but
  informative columns -> `extra_field` (nothing is dropped). For
  `irrelevant` tables, `column_mapping` may be `{}`.
- `context_grouping`: the grouping title for this table, copied VERBATIM
  from `preceding_narrative`, `sheet_or_section`, or the header row —
  e.g. "JB.1.1 STIG HARDEING- SEVERITY HIGH". Use `""` if nothing fits.
  Never compose or paraphrase a title.
- Include every key in every response.
````

`prompts/canonicalize.md`:

````markdown
# Canonicalize Prompt (Phase 2: row canonicalization)

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `canonicalize_requests.jsonl`:

- `chunk_id` (string) — echo back unchanged.
- `table_index` (int), `context_grouping` (string), `header_row` (array).
- `column_mapping` (object) — the approved Phase-1 mapping: column index
  (string) -> canonical field | "extra_field" | "ignore".
- `rows` (array) — this chunk's rows: `{"row_index": int, "cells": [...],
  "merged": bool}`.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "chunk_id": "T3-C0",
  "rows": [
    {"row_index": 1, "disposition": "record",
     "records": [
       {"sub_index": 0,
        "fields": {"stig_objective_or_requirement": "..."},
        "field_provenance": {"stig_objective_or_requirement":
                              {"row_index": 1, "cell_index": 0}},
        "interpretation_note": ""}]},
    {"row_index": 2, "disposition": "separator", "separator_text": "..."}
  ]
}
```

## Decision guide

- Account for EVERY row in the request's `rows`, exactly once, using
  `disposition`:
  - `"record"` — a data row. Produce 1..n records (see splitting below).
  - `"separator"` — a sub-heading, section divider, or blank row inside
    the table. If it carries text, copy it verbatim into
    `separator_text`; it refines the grouping context for rows below it.
  - `"continuation"` — a merged/overflow row whose cells belong to the
    previous data row. Do NOT emit records for it; instead, the previous
    row's records may cite its cells in `field_provenance` (with that
    continuation row's `row_index`).
  A missing or duplicated `row_index` invalidates the whole response.
- Default behavior for a `record` row: for each column mapped to a
  canonical field, copy that cell's text VERBATIM into `fields` and record
  `{"row_index", "cell_index"}` in `field_provenance`. Skip empty cells.
  Do not copy `extra_field` or `ignore` columns into `fields` — the
  pipeline preserves extra-field cells itself.
- Deviate from the column mapping ONLY when the row itself demands it
  (e.g. a value sitting in the wrong column) — provenance must still point
  at the actual cell the text came from, and the text must remain
  verbatim. Never merge text from two cells into one field.
- Splitting: when one row genuinely covers several distinct settings,
  emit several records with `sub_index` 0, 1, ... — each field value still
  a verbatim substring of a single cell of this row (or its continuation
  rows).
- `interpretation_note` is the ONLY free-text field: use it to note what a
  human reviewer should know (e.g. "the DEVIATION entry appears to apply
  only to the second setting"). It is display-only and never used as
  matching evidence. Use `""` when there is nothing to note.
- Include every key shown in the schema for each entry you emit.
````

`prompts/sweep.md`:

````markdown
# Sweep Prompt (one-round recall pass)

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `sweep_requests.jsonl`:

- `sweep_id` (string) — echo back unchanged.
- `records` (array) — company records that matched nothing so far. Each
  has `record_id`, `context_grouping`, and the canonical data fields.
- `rules_index` (array) — official rules not yet addressed by any match.
  Each has `rule_id`, `title`, `expected_value`, `tech_tokens`.

## Output schema

```json
{
  "sweep_id": "S0",
  "proposals": [{"record_id": "CR-1a2b3c4d", "rule_id": "V-1004"}]
}
```

## Decision guide

- Propose a (record, rule) pair ONLY when the record's content plausibly
  addresses that rule's requirement. Your proposals are candidates, not
  matches — every proposal goes through the normal matching adjudication
  (with quotes and validation) afterwards, so a missed proposal here is
  unrecoverable but a weak proposal is filtered later. Prefer recall over
  precision, but never propose on severity or topic-word overlap alone.
- A record may appear in multiple proposals; a rule may appear in
  multiple proposals.
- An empty `proposals` array is an acceptable answer.
- Include both keys in every response.
````

Rewrite `prompts/matching.md`: keep the STRICT RULES block and overall structure; replace the Input bullets (`row_id`/`row` become `record_id`/`record`, note the record carries the canonical fields plus `context_grouping`, `original_company_text`, `source_reference`; candidates unchanged; note `sweep_round: true` may be present meaning candidates include sweep proposals with `_score` 0), the Output schema, and the decision-guide bullets that referenced single selection:

````markdown
## Output schema

```json
{
  "record_id": "...",
  "decision": "match | none | ambiguous",
  "selections": [
    {"rule_id": "...", "row_quote": "...", "rule_quote": "..."}
  ],
  "ambiguous_rule_ids": ["...", "..."],
  "basis": "..."
}
```

Include every key in every response, even when it does not apply to your
decision (e.g. `selections: []` for `"none"`). A missing key invalidates
the whole response.

## Decision guide

- Adjudicate ONLY among the listed `candidates`. Never propose a rule_id
  that is not one of them.
- `"match"`: one OR MORE candidates are genuinely the same requirement as
  this record. Emit one entry in `selections` per matched candidate — a
  record legitimately covering three rules yields three selections. Do
  not add a selection you are unsure of: selections are individually
  binding, not ranked alternatives.
- For every selection: `row_quote` must be copied verbatim from the
  record's text and must be the specific fragment that ties THIS record
  to THIS candidate; `rule_quote` must be copied verbatim from that
  candidate's `title`/`check_text`/`fix_text` and be the discriminating
  evidence, not filler. Both non-empty.
- `"ambiguous"`: two or more candidates plausibly fit and the record's
  text does not let you discriminate between them. List at least two
  `rule_id` values in `ambiguous_rule_ids`. Ambiguous means
  "indistinguishable alternatives for the SAME requirement" — a record
  that genuinely covers several DIFFERENT requirements is a multi-match,
  not ambiguous.
- `"none"`: no candidate fits. `"none"` and `"ambiguous"` are always
  acceptable and preferred over a forced, uncertain `"match"`.
- Similar `severity` alone is NEVER sufficient basis for a match.
- `basis` is a short phrase, in your own words, naming what discriminated
  this decision. It is not a quote.
````

In `prompts/semantic_compare.md`: rename the request-field references `row_id` → `record_id` and `row` → `record` (Input section and output-schema echo field). The output schema keeps `finding_type`, `verdict`, `row_quote`, `rule_quote`, `interpretation` but its echoed id keys become `record_id` + `rule_id`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_prompts_and_skill.py -v -k prompts`
Expected: prompt tests PASS (SKILL.md tests in that file may still reference old workflow — if any fail on SKILL.md content, leave them failing; Task 17 rewrites SKILL.md and fixes them. If the file mixes both, run with `-k "prompts"` only.)

- [ ] **Step 5: Commit**

```bash
git add stig-compare/prompts/ stig-compare/tests/test_prompts_and_skill.py
git commit -m "feat(stig-compare): phase-1/phase-2/sweep prompts; multi-select matching prompt"
```

---

### Task 10: `pipeline.py cmd_start` — skeleton + table-mapping requests

**Files:**
- Modify: `stig-compare/scripts/pipeline.py`, `stig-compare/scripts/extract.py`
- Test: `stig-compare/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `skeleton.extract_skeleton` (Task 3), `extract.extract_official` (unchanged).
- Produces: `start` writes `manifest.json`, `official_rules.jsonl`, `skeleton.json`, `extract_warnings.json`, `table_mapping_requests.jsonl` (one per table, shape below), `table_state.jsonl` (initial state per table), and EMPTY `company_records.jsonl` + `match_state.jsonl`. It no longer writes `company_rows.jsonl`, `structuring_requests.jsonl`, or `matching_requests.jsonl`, and no longer runs `candidates.generate`. Exit codes unchanged (2 on unreadable file).
- `extract.py` gains `COMPANY_HEADER_HINTS = COMPANY_HEADER_SYNONYMS` (alias; the old name and `extract_company` are removed in Task 17).

Table-mapping request shape (consumed by Task 11 and `prompts/table_mapping.md`):

```json
{"table_index": 1, "sheet_or_section": "document-body",
 "preceding_narrative": "...", "header_row": ["..."],
 "sample_rows": [["..."]], "row_count": 12,
 "header_hints": {"stig_description": ["description", "..."]},
 "instructions_file": "prompts/table_mapping.md"}
```

- [ ] **Step 1: Write the failing test.** In `tests/test_pipeline.py`, delete tests asserting `start` writes `company_rows.jsonl`/`structuring_requests.jsonl`/`matching_requests.jsonl`, and add:

```python
def test_start_writes_skeleton_and_mapping_requests(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start",
                        "--official", str(fixture_paths["official_csv"]),
                        "--company", str(fixture_paths["company_real_docx"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    assert len(skel["tables"]) == 4
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    assert len(reqs) == 4
    assert reqs[2]["header_row"][0] == "STIG REQUIREMENT"
    assert reqs[2]["instructions_file"] == "prompts/table_mapping.md"
    assert "header_hints" in reqs[2]
    tstate = common.read_jsonl(run_dir / "table_state.jsonl")
    assert all(t["classification"] is None for t in tstate)
    assert common.read_jsonl(run_dir / "match_state.jsonl") == []
    assert not (run_dir / "company_rows.jsonl").exists()
    assert not (run_dir / "structuring_requests.jsonl").exists()
```

(`fixture_paths` is the existing fixture in `test_pipeline.py` that calls `build_fixtures.build_all`; keep whatever its actual name is — check the top of the file and reuse it.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v -k skeleton_and_mapping`
Expected: FAIL (no `skeleton.json` written)

- [ ] **Step 3: Implement.**
  - In `scripts/extract.py`, add after the `COMPANY_HEADER_SYNONYMS` dict: `COMPANY_HEADER_HINTS = COMPANY_HEADER_SYNONYMS`.
  - In `scripts/pipeline.py`: add `import skeleton` and `import canonical` to the imports. Replace the body of `cmd_start` with:

```python
def cmd_start(args):
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        official = extract.extract_official(args.official)
        skel = skeleton.extract_skeleton(args.company)
    except Exception as e:                        # no document text in errors
        print(f"pipeline: cannot read file: {type(e).__name__}", file=sys.stderr)
        return 2
    normalize.add_normalized(official["records"], _OFFICIAL_NORM_FIELDS)

    registry = rules_mod.load_registry(PKG_ROOT / "rules" / "registry.json")
    doc_type = Path(args.company).suffix.lstrip(".").lower()
    _, conflicts = rules_mod.applicable_rules(
        registry, {"document_type": doc_type, "sheet_or_section": "",
                   "field": ""})

    manifest = {
        "official_file": Path(args.official).name,
        "company_file": Path(args.company).name,
        "official_sha256": common.file_sha256(args.official),
        "company_sha256": common.file_sha256(args.company),
        "started": datetime.now().isoformat(timespec="seconds"),
        "versions": common.load_versions(PKG_ROOT),
        "registry_version": registry["registry_version"],
        "rule_conflicts": conflicts,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    common.write_jsonl(run_dir / "official_rules.jsonl", official["records"])
    (run_dir / "skeleton.json").write_text(
        json.dumps(skel, indent=1), encoding="utf-8")
    (run_dir / "extract_warnings.json").write_text(json.dumps(
        official["warnings"] + skel["warnings"], indent=1), encoding="utf-8")

    mapping_requests = [
        {"table_index": t["table_index"],
         "sheet_or_section": t["sheet_or_section"],
         "preceding_narrative": t["preceding_narrative"],
         "header_row": t["header_row"],
         "sample_rows": [r["cells"] for r in t["rows"][:5]],
         "row_count": len(t["rows"]),
         "header_hints": extract.COMPANY_HEADER_HINTS,
         "instructions_file": "prompts/table_mapping.md"}
        for t in skel["tables"]]
    common.write_jsonl(run_dir / "table_mapping_requests.jsonl",
                       mapping_requests)
    common.write_jsonl(run_dir / "table_state.jsonl", [
        {"table_index": t["table_index"], "classification": None,
         "irrelevant_reason": "", "column_mapping": {},
         "context_grouping": "", "mapping_failures": 0,
         "row_dispositions": {}, "parent_of": {}, "chunks": {}}
        for t in skel["tables"]])
    common.write_jsonl(run_dir / "company_records.jsonl", [])
    common.write_jsonl(run_dir / "match_state.jsonl", [])

    print(f"start: tables={len(skel['tables'])} "
          f"mapping_pending={len(mapping_requests)}")
    return 0
```

  - In `_load_consumed`, change the defaults line to: `for k in ("table_mapping", "canonicalize", "matching", "sweep", "semantic", "skeptic"):`.
  - Delete the now-unused `_STRUCT_FIELDS` constant and `_COMPANY_NORM_FIELDS` stays (used by Task 11).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py -v -k skeleton_and_mapping`
Expected: PASS. Other `test_pipeline.py` tests that exercise resolve/finalize will fail until Tasks 11–14 — do not chase them yet.

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/scripts/extract.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): start emits skeleton and table-mapping requests"
```

---

### Task 11: `pipeline.py cmd_resolve` — table-mapping and canonicalize passes

**Files:**
- Modify: `stig-compare/scripts/pipeline.py`
- Test: `stig-compare/tests/test_pipeline.py`

**Interfaces:**
- Consumes: validators (Task 5), `canonical` (Task 4), `candidates.generate` (Task 7), request/state files from Task 10.
- Produces: `resolve` gains two passes that run BEFORE the matching pass:
  1. **Table-mapping pass** — consumes `table_mapping_responses.jsonl` (consumed-key `table_mapping`). Valid answer → table_state updated; `stig_relevant`/`uncertain` tables get chunked `canonicalize_requests.jsonl` records appended (chunk ids `T<ti>-C<n>`, `canonical.chunk_rows` size 40). Invalid → two-strike retry (re-append request with `retry: true`/`previous_errors`), second strike → `classification = "mapping-failed"`.
  2. **Canonicalize pass** — consumes `canonicalize_responses.jsonl` (consumed-key `canonicalize`). Valid chunk → entries stored in `table_state.chunks[chunk_id]["entries"]`; when ALL chunks of a table are done, `_build_table_records` walks entries in row order (separator context refinement, continuation parenting, sub-record splitting), appends canonical records to `company_records.jsonl`, normalizes them, runs `candidates.generate` over the new `status=="ok"` records, appends to `match_state.jsonl`, and appends matching requests (shape below) for tier-None records with candidates. Invalid chunk → two-strike; second strike → every row of that chunk becomes a `canonical.failed_record(..., "canonicalize-rejected")` with disposition `"record"`.
- Matching request shape (consumed by Task 12 + `prompts/matching.md`): `{"record_id", "record": <canonical record>, "candidates": [official rule | {"_score": s}], "instructions_file": "prompts/matching.md"}`.
- Helper functions added to `pipeline.py` (module level): `_build_table_records(table, ts)`, `_extra_fields_for(table, column_mapping, row)`, `_matching_request(record, m, rules_by_id)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`; use the real-format fixture end to end through extraction)

```python
def _mapping_answer(req, classification="stig_relevant", mapping=None,
                    reason=""):
    return {"table_index": req["table_index"],
            "classification": classification,
            "irrelevant_reason": reason,
            "column_mapping": mapping or {},
            "context_grouping": ""}


def _canon_answer(req):
    """Mechanical fake-Claude: apply the column mapping verbatim."""
    entries = []
    for row in req["rows"]:
        fields, prov = {}, {}
        empty = True
        for k, target in req["column_mapping"].items():
            i = int(k)
            if target in ("extra_field", "ignore"):
                continue
            val = row["cells"][i] if i < len(row["cells"]) else ""
            if val.strip():
                empty = False
                fields[target] = val
                prov[target] = {"row_index": row["row_index"],
                                "cell_index": i}
        if empty:
            entries.append({"row_index": row["row_index"],
                            "disposition": "separator",
                            "separator_text": ""})
        else:
            entries.append({"row_index": row["row_index"],
                            "disposition": "record",
                            "records": [{"sub_index": 0, "fields": fields,
                                         "field_provenance": prov,
                                         "interpretation_note": ""}]})
    return {"chunk_id": req["chunk_id"], "rows": entries}


EX1_MAPPING = {"0": "stig_objective_or_requirement", "1": "stig_description",
               "2": "stig_command_or_value",
               "3": "company_approved_setting_or_expected_value"}
EX2_MAPPING = {"0": "ignore", "1": "stig_command_or_value",
               "2": "stig_description", "3": "extra_field",
               "4": "extra_field", "5": "company_compliance_claim",
               "6": "company_approved_setting_or_expected_value",
               "7": "company_severity", "8": "observed_value_or_evidence",
               "9": "remarks_or_justification"}


def _answer_extraction(run_dir):
    """Answer table-mapping for the real fixture, resolve, then answer
    canonicalize chunks, resolve again. Tables 1-2 irrelevant."""
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    answers = []
    for r in reqs:
        if r["table_index"] == 1:
            answers.append(_mapping_answer(r, "irrelevant",
                                           reason="general-info"))
        elif r["table_index"] == 2:
            answers.append(_mapping_answer(r, "irrelevant",
                                           reason="instructions"))
        elif r["table_index"] == 3:
            answers.append(_mapping_answer(r, mapping=EX1_MAPPING))
        else:
            answers.append(_mapping_answer(r, mapping=EX2_MAPPING))
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    canon_reqs = common.read_jsonl(run_dir / "canonicalize_requests.jsonl")
    common.write_jsonl(run_dir / "canonicalize_responses.jsonl",
                       [_canon_answer(r) for r in canon_reqs])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_resolve_builds_canonical_records(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    records = common.read_jsonl(run_dir / "company_records.jsonl")
    assert len(records) == 4          # 2 EX1 rows + 2 EX2 rows
    ex2 = [r for r in records
           if r["source_reference"]["table_index"] == 4]
    dev = next(r for r in ex2 if r["claim_normalized"] == "deviation")
    assert dev["company_severity"] == "HIGH"
    assert dev["observed_value_or_evidence"] == "10"
    assert dev["extra_fields"]["REPORTING yes/no"] == "YES"

    tstate = {t["table_index"]: t
              for t in common.read_jsonl(run_dir / "table_state.jsonl")}
    assert tstate[1]["classification"] == "irrelevant"
    assert tstate[3]["row_dispositions"] == {"1": "record", "2": "record"}

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    assert len(match_state) == 4
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert all("record" in r and "candidates" in r for r in m_reqs)


def test_mapping_two_strikes_marks_table_failed(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    bad = {"table_index": 1, "classification": "nonsense",
           "irrelevant_reason": "", "column_mapping": {},
           "context_grouping": ""}
    common.write_jsonl(run_dir / "table_mapping_responses.jsonl", [bad])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    reqs = common.read_jsonl(run_dir / "table_mapping_requests.jsonl")
    assert any(r.get("retry") for r in reqs if r["table_index"] == 1)
    with open(run_dir / "table_mapping_responses.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps(dict(bad, classification="still-bad")) + "\n")
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    tstate = {t["table_index"]: t
              for t in common.read_jsonl(run_dir / "table_state.jsonl")}
    assert tstate[1]["classification"] == "mapping-failed"


def test_build_table_records_separator_continuation_split():
    table = {"table_index": 1, "sheet_or_section": "document-body",
             "preceding_narrative": "", "header_row": ["A", "B"],
             "rows": [
                 {"row_index": 1, "cells": ["SECTION X", ""], "merged": True},
                 {"row_index": 2, "cells": ["timeout 15", "length 14"],
                  "merged": False},
                 {"row_index": 3, "cells": ["continued detail", ""],
                  "merged": True}]}
    ts = {"table_index": 1, "classification": "stig_relevant",
          "irrelevant_reason": "", "column_mapping": {"0": "stig_description"},
          "context_grouping": "Base", "mapping_failures": 0,
          "row_dispositions": {}, "parent_of": {},
          "chunks": {"T1-C0": {"row_indexes": [1, 2, 3], "done": True,
                               "failures": 0, "entries": [
              {"row_index": 1, "disposition": "separator",
               "separator_text": "SECTION X"},
              {"row_index": 2, "disposition": "record", "records": [
                  {"sub_index": 0,
                   "fields": {"stig_description": "timeout 15"},
                   "field_provenance": {"stig_description":
                                        {"row_index": 2, "cell_index": 0}},
                   "interpretation_note": ""},
                  {"sub_index": 1,
                   "fields": {"stig_description": "length 14"},
                   "field_provenance": {"stig_description":
                                        {"row_index": 2, "cell_index": 1}},
                   "interpretation_note": ""}]},
              {"row_index": 3, "disposition": "continuation"}]}}}
    records = pipeline._build_table_records(table, ts)
    assert len(records) == 2
    assert [r["source_reference"]["sub_index"] for r in records] == [0, 1]
    assert all(r["context_grouping"] == "Base | SECTION X" for r in records)
    assert records[0]["record_id"] != records[1]["record_id"]
    assert records[0]["row_id"] == records[1]["row_id"]
    assert ts["parent_of"] == {"3": 2}
    assert ts["row_dispositions"] == {"1": "separator", "2": "record",
                                      "3": "continuation"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v -k "canonical_records or two_strikes or separator_continuation"`
Expected: FAIL (resolve still runs the old structuring pass and crashes on missing `company_rows.jsonl`)

- [ ] **Step 3: Implement.** In `scripts/pipeline.py`:

**3a.** Add module-level helpers (near `_rule_text`):

```python
def _extra_fields_for(table, column_mapping, row):
    header = table["header_row"]
    out = {}
    for k, target in column_mapping.items():
        if target != "extra_field":
            continue
        i = int(k)
        val = row["cells"][i] if i < len(row["cells"]) else ""
        if common.fold_ws(val):
            name = header[i] if i < len(header) and \
                common.fold_ws(str(header[i])) else f"col{i}"
            out[str(name)] = common.fold_ws(val)
    return out


def _build_table_records(table, ts):
    """Walk a fully-canonicalized table's stored chunk entries in row order
    and build canonical records. Mutates ts (row_dispositions, parent_of).
    Returns the new records. Belt-and-braces: rows the validator somehow
    never saw become extraction-failed records via canonical.reconcile."""
    rows_by_index = {r["row_index"]: r for r in table["rows"]}
    entries = []
    for chunk in ts["chunks"].values():
        entries.extend(chunk.get("entries", []))
    entries.sort(key=lambda e: e["row_index"])

    records = []
    current_context = ts["context_grouping"]
    last_record_row = None
    for entry in entries:
        ri = entry["row_index"]
        disp = entry["disposition"]
        ts["row_dispositions"][str(ri)] = disp
        if disp == "separator":
            st = common.fold_ws(entry.get("separator_text", ""))
            current_context = ts["context_grouping"] + \
                (" | " + st if st else "")
            continue
        if disp == "continuation":
            if last_record_row is None:
                ts["row_dispositions"][str(ri)] = "record"
                records.append(canonical.failed_record(
                    table, rows_by_index[ri], "orphan-continuation"))
            else:
                ts["parent_of"][str(ri)] = last_record_row
            continue
        last_record_row = ri
        for rec_resp in entry["records"]:
            records.append(canonical.build_record(
                table, rows_by_index[ri], rec_resp["sub_index"],
                rec_resp["fields"], rec_resp["field_provenance"],
                _extra_fields_for(table, ts["column_mapping"],
                                  rows_by_index[ri]),
                rec_resp.get("interpretation_note", ""), current_context))
    for ri in canonical.reconcile(
            table, {int(k): v for k, v in ts["row_dispositions"].items()}):
        ts["row_dispositions"][str(ri)] = "record"
        records.append(canonical.failed_record(
            table, rows_by_index[ri], "reconcile-missing"))
    return records


def _matching_request(record, m, rules_by_id, extra=None):
    req = {"record_id": record["record_id"], "record": record,
           "candidates": [rules_by_id[c["rule_id"]] | {"_score": c["score"]}
                          for c in m["candidates"]
                          if c["rule_id"] in rules_by_id],
           "instructions_file": "prompts/matching.md"}
    if extra:
        req.update(extra)
    return req
```

**3b.** Update `_ensure_match_fields` to the multi-match shape:

```python
def _ensure_match_fields(m):
    m.setdefault("matched_rule_ids", [])
    m.setdefault("match_failures", 0)
    m.setdefault("semantic_failures", {})
    m.setdefault("retried", False)
    m.setdefault("warnings", [])
    m.setdefault("row_quotes", {})
    m.setdefault("rule_quotes", {})
    m.setdefault("ambiguous_rule_ids", [])
    m.setdefault("verdict_done_rules", [])
    m.setdefault("sweep_origin_rule_ids", [])
    return m
```

**3c.** In `cmd_resolve`, replace the loading block and the whole structuring pass. New loading block reads `skeleton.json`, `table_state.jsonl`, `company_records.jsonl` instead of `company_rows.jsonl`:

```python
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    tables_by_index = {t["table_index"]: t for t in skel["tables"]}
    table_state = _read_jsonl_opt(run_dir / "table_state.jsonl")
    tstate_by_index = {t["table_index"]: t for t in table_state}
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
```

(keep `official_rules`/`rules_by_id`, `match_state` loading; `rows_by_id` is gone — every later reference in resolve becomes `records_by_id`.)

Then insert the two passes before the matching pass:

```python
    # ---- table-mapping pass ---------------------------------------------
    consumed_mapping = set(consumed["table_mapping"])
    consumed_canon = set(consumed["canonicalize"])
    mapping_requests_all = _read_jsonl_opt(
        run_dir / "table_mapping_requests.jsonl")
    mapping_req_by_index = {r["table_index"]: r for r in mapping_requests_all}
    new_mapping_requests = []
    new_canon_requests = []
    mapping_ok = mapping_failed_final = 0

    for raw_line in _read_response_lines(
            run_dir / "table_mapping_responses.jsonl"):
        fp = _fingerprint(raw_line)
        if fp in consumed_mapping:
            continue
        consumed_mapping.add(fp)
        resp, parse_err = _parse_response_line(raw_line)
        if parse_err:
            validation_failures_new.append(
                _mk_failure(None, "table_mapping", [parse_err], raw_line))
            continue
        tix = resp.get("table_index")
        ts = tstate_by_index.get(tix) if isinstance(tix, int) else None
        if ts is None or ts["classification"] is not None:
            validation_failures_new.append(
                _mk_failure(None, "table_mapping", ["no-such-request"], resp))
            continue
        errs = validate.validate_table_mapping_output(
            resp, tables_by_index[tix])
        if errs:
            ts["mapping_failures"] += 1
            validation_failures_new.append(
                _mk_failure(None, "table_mapping", errs, resp))
            if ts["mapping_failures"] >= 2:
                ts["classification"] = "mapping-failed"
                mapping_failed_final += 1
            else:
                new_mapping_requests.append(dict(
                    mapping_req_by_index[tix], retry=True,
                    previous_errors=errs))
            continue
        mapping_ok += 1
        ts["classification"] = resp["classification"]
        ts["irrelevant_reason"] = resp["irrelevant_reason"]
        ts["column_mapping"] = resp["column_mapping"]
        ts["context_grouping"] = common.fold_ws(resp["context_grouping"])
        if ts["classification"] in ("stig_relevant", "uncertain"):
            table = tables_by_index[tix]
            for ci, chunk in enumerate(canonical.chunk_rows(table["rows"])):
                chunk_id = f"T{tix}-C{ci}"
                ts["chunks"][chunk_id] = {
                    "row_indexes": [r["row_index"] for r in chunk],
                    "done": False, "failures": 0, "entries": []}
                new_canon_requests.append({
                    "chunk_id": chunk_id, "table_index": tix,
                    "context_grouping": ts["context_grouping"],
                    "column_mapping": ts["column_mapping"],
                    "header_row": table["header_row"], "rows": chunk,
                    "instructions_file": "prompts/canonicalize.md"})

    # ---- canonicalize pass ------------------------------------------------
    canon_req_by_id = {r["chunk_id"]: r for r in
                       _read_jsonl_opt(run_dir / "canonicalize_requests.jsonl")}
    canon_ok = canon_failed_final = 0
    new_records = []

    def _chunk_state(chunk_id):
        for ts in table_state:
            if chunk_id in ts.get("chunks", {}):
                return ts, ts["chunks"][chunk_id]
        return None, None

    for raw_line in _read_response_lines(
            run_dir / "canonicalize_responses.jsonl"):
        fp = _fingerprint(raw_line)
        if fp in consumed_canon:
            continue
        consumed_canon.add(fp)
        resp, parse_err = _parse_response_line(raw_line)
        if parse_err:
            validation_failures_new.append(
                _mk_failure(None, "canonicalize", [parse_err], raw_line))
            continue
        cid = resp.get("chunk_id") if isinstance(resp.get("chunk_id"), str) \
            else None
        ts, chunk = _chunk_state(cid) if cid else (None, None)
        if chunk is None or chunk["done"]:
            validation_failures_new.append(
                _mk_failure(None, "canonicalize", ["no-such-request"], resp))
            continue
        table = tables_by_index[ts["table_index"]]
        errs = validate.validate_canonicalize_output(
            resp, table, chunk["row_indexes"])
        if errs:
            chunk["failures"] += 1
            validation_failures_new.append(
                _mk_failure(None, "canonicalize", errs, resp))
            if chunk["failures"] >= 2:
                chunk["done"] = True
                canon_failed_final += 1
                rows_by_index = {r["row_index"]: r for r in table["rows"]}
                chunk["entries"] = []
                for ri in chunk["row_indexes"]:
                    ts["row_dispositions"][str(ri)] = "record"
                    new_records.append(canonical.failed_record(
                        table, rows_by_index[ri], "canonicalize-rejected"))
            else:
                new_canon_requests.append(dict(
                    canon_req_by_id[cid], retry=True, previous_errors=errs))
            continue
        canon_ok += 1
        chunk["done"] = True
        chunk["entries"] = resp["rows"]

    # tables whose chunks all just completed -> build records + shortlists
    new_matching_requests_from_canon = []
    for ts in table_state:
        chunks = ts.get("chunks", {})
        if not chunks or ts.get("records_built"):
            continue
        if all(c["done"] for c in chunks.values()):
            table = tables_by_index[ts["table_index"]]
            built = _build_table_records(table, ts)
            ts["records_built"] = True
            normalize.add_normalized(
                [r for r in built if r["status"] == "ok"],
                _COMPANY_NORM_FIELDS)
            new_records.extend(built)
    if new_records:
        company_records.extend(new_records)
        records_by_id.update({r["record_id"]: r for r in new_records})
        fresh = [r for r in new_records if r["status"] == "ok"]
        for m in candidates_mod.generate(fresh, official_rules):
            m = _ensure_match_fields(m)
            state_by_id[m["record_id"]] = m
            if m["tier"] is None and m["candidates"]:
                new_matching_requests_from_canon.append(_matching_request(
                    records_by_id[m["record_id"]], m, rules_by_id))
    match_state = list(state_by_id.values())
```

**3d.** Persist the new artifacts at the end of `cmd_resolve` (alongside the existing writes; `company_rows.jsonl` write is removed):

```python
    common.write_jsonl(run_dir / "table_state.jsonl", table_state)
    common.write_jsonl(run_dir / "company_records.jsonl", company_records)
    _append_jsonl(run_dir / "table_mapping_requests.jsonl",
                  new_mapping_requests)
    _append_jsonl(run_dir / "canonicalize_requests.jsonl", new_canon_requests)
    consumed["table_mapping"] = sorted(consumed_mapping)
    consumed["canonicalize"] = sorted(consumed_canon)
```

and extend the summary print with `mapping_ok=... mapping_failed=... canon_ok=... canon_failed=... canon_pending=<count of not-done chunks>`. `state_by_id` keys are now record_ids; the matching pass and `_run_deterministic_verdicts` still reference the OLD single-select fields — they are rewritten in Task 12; for this task's tests only extraction-stage behavior is asserted (the fake answers produce matching requests but no matching responses are resolved).

Note on ordering: the matching pass's `requested_ids` must now be computed from `matching_requests.jsonl` AFTER `new_matching_requests_from_canon` is known — simplest is to keep the existing read of `matching_requests_all` where it is, and `_append_jsonl` the canon-derived requests BEFORE the matching pass reads responses is not needed (responses to them can only exist on the NEXT resolve call). Just append `new_matching_requests_from_canon` together with the matching pass's own `new_matching_requests` in the persist block.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py -v -k "canonical_records or two_strikes or skeleton_and_mapping"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): resolve processes table-mapping and canonicalize passes"
```

---

### Task 12: `pipeline.py` — multi-select matching pass and per-pair deterministic verdicts

**Files:**
- Modify: `stig-compare/scripts/pipeline.py`
- Test: `stig-compare/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `validate.validate_match_output` (Task 6), match_state multi-match shape (Task 11's `_ensure_match_fields`).
- Produces:
  - Matching pass keyed by `record_id`; a valid `"match"` sets `tier="T2"`, `matched_rule_ids=[...]`, `row_quotes`/`rule_quotes` dicts. `"none"` → `T4`; `"ambiguous"` → `T3` + `ambiguous_rule_ids`. Two-strike retry unchanged (`match_failures`, `llm-output-rejected`). Margin-flag downgrade applies ONLY when exactly one selection was made and the runner-up quote-overlap check passes (same logic as before, using the single selection's `rule_quote`).
  - `_run_deterministic_verdicts` iterates every `(record, rule_id)` pair in `matched_rule_ids` not yet in `verdict_done_rules`; each pair yields a finding or a semantic request `{"record_id", "rule_id", "record", "rule", "instructions_file": "prompts/semantic_compare.md"}`.
  - `_build_finding(record_id, row_id, rule_id, ...)` — findings carry BOTH `record_id` and `row_id`; `finding_id = common.finding_id(record_id, rule_id, finding_type or "deterministic")`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`)

```python
def _match_answer(req, rule_ids):
    if not rule_ids:
        return {"record_id": req["record_id"], "decision": "none",
                "selections": [], "ambiguous_rule_ids": [], "basis": "none"}
    sels = []
    for rid in rule_ids:
        rule = next(c for c in req["candidates"] if c["rule_id"] == rid)
        sels.append({"rule_id": rid,
                     "row_quote": req["record"]["original_company_text"]
                     .split(" | ")[0],
                     "rule_quote": rule["title"]})
    return {"record_id": req["record_id"], "decision": "match",
            "selections": sels, "ambiguous_rule_ids": [], "basis": "content"}


def test_multi_select_match_produces_pair_findings(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)

    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = []
    for req in m_reqs:
        cand_ids = [c["rule_id"] for c in req["candidates"]]
        picks = cand_ids[:2] if len(cand_ids) >= 2 and \
            "password_reuse_max" in req["record"]["original_company_text"] \
            else cand_ids[:1]
        answers.append(_match_answer(req, picks))
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    match_state = common.read_jsonl(run_dir / "match_state.jsonl")
    multi = [m for m in match_state if len(m["matched_rule_ids"]) == 2]
    assert multi, "expected at least one two-rule match"
    findings = common.read_jsonl(run_dir / "findings.jsonl")
    sem_reqs = (common.read_jsonl(run_dir / "semantic_requests.jsonl")
                if (run_dir / "semantic_requests.jsonl").exists() else [])
    m0 = multi[0]
    covered = {f["rule_id"] for f in findings
               if f["record_id"] == m0["record_id"]} | \
              {r["rule_id"] for r in sem_reqs
               if r["record_id"] == m0["record_id"]}
    assert covered == set(m0["matched_rule_ids"])
    for f in findings:
        assert "record_id" in f and "row_id" in f
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v -k multi_select`
Expected: FAIL (old matching pass KeyErrors on `row_id`/single-select fields)

- [ ] **Step 3: Implement.** In `scripts/pipeline.py`:

**3a.** Rewrite the matching pass loop body (inside `cmd_resolve`). Keep fingerprinting/parse/no-such-request structure, with these changes: `rid = resp.get("record_id")`; `_pending_ids()` uses `requested_ids & {record_ids with tier None}` where `requested_ids = {r["record_id"] for r in matching_requests_all}`; `record = records_by_id.get(rid)`; type-guard call becomes `_type_guard(resp, ["decision", "basis"], ["selections", "ambiguous_rule_ids"])`; validation call `validate.validate_match_output(resp, shortlist_ids, record, rules_by_id)`; retry re-request uses `_matching_request(record, m, rules_by_id, extra={"retry": True, "previous_errors": errs})`. Decision handling:

```python
        decision = resp["decision"]
        matching_ok += 1
        if decision == "none":
            m["tier"] = "T4"
        elif decision == "ambiguous":
            m["tier"] = "T3"
            m["ambiguous_rule_ids"] = resp["ambiguous_rule_ids"]
        else:  # match
            sels = resp["selections"]
            downgraded = False
            if m.get("margin_flag") and len(sels) == 1 and \
                    len(m["candidates"]) >= 2:
                chosen_id = sels[0]["rule_id"]
                runner_up = next((c for c in m["candidates"]
                                  if c["rule_id"] != chosen_id), None)
                if runner_up is not None:
                    runner_rule = rules_by_id.get(runner_up["rule_id"])
                    if runner_rule and validate.quote_exists(
                            sels[0]["rule_quote"], _rule_text(runner_rule)):
                        downgraded = True
                        m["tier"] = "T3"
                        m["ambiguous_rule_ids"] = [chosen_id,
                                                   runner_up["rule_id"]]
            if not downgraded:
                m["tier"] = "T2"
                m["matched_rule_ids"] = [s["rule_id"] for s in sels]
                m["row_quotes"] = {s["rule_id"]: s["row_quote"]
                                   for s in sels}
                m["rule_quotes"] = {s["rule_id"]: s["rule_quote"]
                                    for s in sels}
```

**3b.** Rewrite `_run_deterministic_verdicts` to iterate pairs (replace the whole function; signature becomes `(registry, doc_type, match_state, records_by_id, rules_by_id)`):

```python
def _run_deterministic_verdicts(registry, doc_type, match_state,
                                records_by_id, rules_by_id):
    new_findings = []
    new_semantic_requests = []
    for m in match_state:
        if m["tier"] not in _MATCHED_TIERS or not m.get("matched_rule_ids"):
            continue
        record = records_by_id.get(m["record_id"])
        for rule_id in m["matched_rule_ids"]:
            if rule_id in m["verdict_done_rules"]:
                continue
            rule = rules_by_id.get(rule_id)
            if record is None or rule is None:
                m["verdict_done_rules"].append(rule_id)
                m["warnings"].append("unknown-matched-rule")
                continue
            context = _context_for_row(record, doc_type,
                                       field="expected_value")
            applied, _ = rules_mod.applicable_rules(registry, context)
            observed_raw = record.get("observed_value_or_evidence", "")
            expected_raw = rule.get("expected_value", "")
            eq_rule_id = None
            if common.fold_ws(observed_raw):
                eq_rule_id = rules_mod.equivalent_by_rule(
                    applied, observed_raw, expected_raw)
            applied_rules_list = []
            if eq_rule_id:
                result = {"verdict": "Compliant",
                          "basis": "rule-equivalence",
                          "deterministic": True, "approved_alignment": None,
                          "observation": {"observed": observed_raw,
                                          "expected": expected_raw}}
                applied_rules_list = [eq_rule_id]
            else:
                result = compare_values.deterministic_verdict(record, rule)
            m["verdict_done_rules"].append(rule_id)
            if result is not None:
                new_findings.append(_build_finding(
                    m["record_id"], record["row_id"], rule_id,
                    result["verdict"], result["basis"],
                    result["deterministic"], None, result["observation"],
                    None, applied_rules_list, m, record, rule,
                    approved_alignment=result.get("approved_alignment")))
            else:
                new_semantic_requests.append(
                    {"record_id": m["record_id"], "rule_id": rule_id,
                     "record": record, "rule": rule,
                     "instructions_file": "prompts/semantic_compare.md"})
    return new_findings, new_semantic_requests
```

**3c.** Update `_build_finding`: signature `(record_id, row_id, rule_id, verdict, basis, deterministic, finding_type, observation, interpretation, applied_rules_list, match_row, company_record, official_rule, approved_alignment=None)`; body sets `"finding_id": common.finding_id(record_id, rule_id, finding_type or "deterministic")`, `"record_id": record_id, "row_id": row_id`, and the `company_row` block reads from `company_record` (same two keys). Update `_finding_id` helper accordingly or inline it.

**3d.** Update both call sites of `_run_deterministic_verdicts` (resolve + finalize) to pass `records_by_id`. In finalize, the loading block changes the same way as resolve's (skeleton/table_state/company_records instead of company_rows) — do the minimal load change now (`company_records = common.read_jsonl(run_dir / "company_records.jsonl")`, `records_by_id = ...`); the rest of finalize is Task 14. Update `resolve`'s `retries_pending` computation to use `m["record_id"]`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py -v -k "multi_select or canonical_records or two_strikes or skeleton_and_mapping"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): multi-select matching and per-pair deterministic verdicts"
```

---

### Task 13: `pipeline.py sweep` command and sweep-response processing

**Files:**
- Modify: `stig-compare/scripts/pipeline.py`
- Test: `stig-compare/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `validate.validate_sweep_output` (Task 6), `candidates_mod.technical_tokens`, match_state (Task 12 shape).
- Produces:
  - CLI: `python scripts/pipeline.py sweep --run-dir <dir>`. Idempotent single round: if `sweep_state.json` exists → print `sweep: already-done`, exit 0, write nothing. If there are no unmatched ok-records or no unaddressed rules → write `sweep_state.json` `{"done": true, "batches": 0}`, print `sweep: nothing-to-sweep`, exit 0. Otherwise write `sweep_requests.jsonl` (batches of ≤20 records, ids `S0, S1, ...`) and `sweep_state.json` `{"done": true, "batches": N}`.
  - Sweep request shape: `{"sweep_id", "records": [{record_id, context_grouping, <8 canonical data fields>}], "rules_index": [{rule_id, title, expected_value, tech_tokens}], "instructions_file": "prompts/sweep.md"}`.
  - `resolve` gains a sweep-response pass (consumed-key `sweep`, runs BEFORE the matching pass): valid proposals for still-unmatched records (tier `None`/`T4`) inject `{"rule_id", "score": 0.0, "features": {"sweep": 1.0}}` into that record's `candidates` (skip if already present), append the rule to `sweep_origin_rule_ids`, reset `tier` to `None` and `match_failures` to 0, and emit ONE new matching request per touched record (all its proposals folded into the shortlist) with `extra={"sweep_round": True}`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`)

```python
def _finish_matching_as_none(run_dir):
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = [_match_answer(r, []) for r in m_reqs]
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0


def test_sweep_generates_requests_then_injects(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    _finish_matching_as_none(run_dir)

    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    s_reqs = common.read_jsonl(run_dir / "sweep_requests.jsonl")
    assert s_reqs and s_reqs[0]["sweep_id"] == "S0"
    assert all(len(b["records"]) <= 20 for b in s_reqs)
    assert {"rule_id", "title", "expected_value", "tech_tokens"} <= \
        set(s_reqs[0]["rules_index"][0])

    # second invocation is a no-op
    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    assert common.read_jsonl(run_dir / "sweep_requests.jsonl") == s_reqs

    batch = s_reqs[0]
    rec_id = batch["records"][0]["record_id"]
    rule_id = batch["rules_index"][0]["rule_id"]
    common.write_jsonl(run_dir / "sweep_responses.jsonl",
                       [{"sweep_id": batch["sweep_id"],
                         "proposals": [{"record_id": rec_id,
                                        "rule_id": rule_id}]}])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0

    state = {m["record_id"]: m
             for m in common.read_jsonl(run_dir / "match_state.jsonl")}
    m = state[rec_id]
    assert m["tier"] is None
    assert rule_id in m["sweep_origin_rule_ids"]
    assert any(c["rule_id"] == rule_id for c in m["candidates"])
    reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    assert any(r.get("sweep_round") and r["record_id"] == rec_id
               for r in reqs)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v -k sweep_generates`
Expected: FAIL (`unknown command: sweep` argparse error)

- [ ] **Step 3: Implement.** In `scripts/pipeline.py`:

**3a.** Add `cmd_sweep` after `cmd_resolve`:

```python
def cmd_sweep(args):
    run_dir = Path(args.run_dir)
    state_path = run_dir / "sweep_state.json"
    if state_path.exists():
        print("sweep: already-done")
        return 0
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
    official_rules = common.read_jsonl(run_dir / "official_rules.jsonl")
    match_state = [_ensure_match_fields(m) for m in
                   _read_jsonl_opt(run_dir / "match_state.jsonl")]

    matched_ids = set()
    for m in match_state:
        if m["tier"] in _MATCHED_TIERS:
            matched_ids.update(m["matched_rule_ids"])
    unmatched = [records_by_id[m["record_id"]] for m in match_state
                 if m["tier"] in (None, "T4")
                 and records_by_id.get(m["record_id"], {}).get("status") == "ok"]
    unaddressed = [r for r in official_rules
                   if r["rule_id"] not in matched_ids]
    if not unmatched or not unaddressed:
        state_path.write_text(json.dumps({"done": True, "batches": 0},
                                         indent=1), encoding="utf-8")
        print("sweep: nothing-to-sweep")
        return 0

    index = [{"rule_id": r["rule_id"], "title": r.get("title", ""),
              "expected_value": r.get("expected_value", ""),
              "tech_tokens": sorted(candidates_mod.technical_tokens(
                  _rule_text(r)))[:8]}
             for r in unaddressed]
    requests = []
    for bi, start in enumerate(range(0, len(unmatched), 20)):
        batch = unmatched[start:start + 20]
        requests.append({
            "sweep_id": f"S{bi}",
            "records": [{"record_id": r["record_id"],
                         "context_grouping": r["context_grouping"],
                         **{f: r[f] for f in canonical.CANONICAL_DATA_FIELDS}}
                        for r in batch],
            "rules_index": index,
            "instructions_file": "prompts/sweep.md"})
    common.write_jsonl(run_dir / "sweep_requests.jsonl", requests)
    state_path.write_text(json.dumps({"done": True,
                                      "batches": len(requests)}, indent=1),
                          encoding="utf-8")
    print(f"sweep: batches={len(requests)} unmatched={len(unmatched)} "
          f"unaddressed={len(unaddressed)}")
    return 0
```

**3b.** In `cmd_resolve`, insert the sweep-response pass immediately BEFORE the matching pass:

```python
    # ---- sweep-response pass ----------------------------------------------
    consumed_sweep = set(consumed["sweep"])
    sweep_reqs = _read_jsonl_opt(run_dir / "sweep_requests.jsonl")
    sweep_req_by_id = {r["sweep_id"]: r for r in sweep_reqs}
    sweep_injected = {}
    for raw_line in _read_response_lines(run_dir / "sweep_responses.jsonl"):
        fp = _fingerprint(raw_line)
        if fp in consumed_sweep:
            continue
        consumed_sweep.add(fp)
        resp, parse_err = _parse_response_line(raw_line)
        if parse_err:
            validation_failures_new.append(
                _mk_failure(None, "sweep", [parse_err], raw_line))
            continue
        sid = resp.get("sweep_id")
        req = sweep_req_by_id.get(sid) if isinstance(sid, str) else None
        if req is None:
            validation_failures_new.append(
                _mk_failure(None, "sweep", ["no-such-request"], resp))
            continue
        batch_ids = {r["record_id"] for r in req["records"]}
        index_ids = {r["rule_id"] for r in req["rules_index"]}
        errs = validate.validate_sweep_output(resp, batch_ids, index_ids)
        if errs:
            validation_failures_new.append(
                _mk_failure(None, "sweep", errs, resp))
            continue
        for p in resp["proposals"]:
            m = state_by_id.get(p["record_id"])
            if m is None or m["tier"] not in (None, "T4"):
                continue
            if not any(c["rule_id"] == p["rule_id"]
                       for c in m["candidates"]):
                m["candidates"].append({"rule_id": p["rule_id"],
                                        "score": 0.0,
                                        "features": {"sweep": 1.0}})
            if p["rule_id"] not in m["sweep_origin_rule_ids"]:
                m["sweep_origin_rule_ids"].append(p["rule_id"])
            m["tier"] = None
            m["match_failures"] = 0
            sweep_injected[p["record_id"]] = m
    for rid, m in sweep_injected.items():
        new_matching_requests.append(_matching_request(
            records_by_id[rid], m, rules_by_id,
            extra={"sweep_round": True}))
    consumed["sweep"] = sorted(consumed_sweep)
```

(`new_matching_requests` must be initialized before this pass; it already exists — move its initialization above if needed. Sweep-injected candidate rule_ids missing from `rules_by_id` are impossible because the index was built from `official_rules.jsonl`.)

**3c.** Register the subcommand in `main()`:

```python
    p_sweep = sub.add_parser("sweep")
    p_sweep.add_argument("--run-dir", required=True)
```
and dispatch `if args.cmd == "sweep": return cmd_sweep(args)`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py -v -k sweep`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): one-round sweep command with adjudicated candidate injection"
```

---

### Task 14: `pipeline.py cmd_finalize` — per-pair semantic, claim flags, confidence, coverage, triage

**Files:**
- Modify: `stig-compare/scripts/pipeline.py`, `stig-compare/scripts/validate.py`
- Test: `stig-compare/tests/test_pipeline.py`, `stig-compare/tests/test_validate.py`

**Interfaces:**
- Consumes: everything above; `coverage.compute` (Task 8 signature).
- Produces:
  - Semantic pass keyed `(record_id, rule_id)`; per-pair two-strike via `m["semantic_failures"][rule_id]`. Semantic responses echo `record_id` + `rule_id`; source text for row quotes is the record's `original_company_text` (existing `validate.validate_semantic_output(resp, record, rule)` works unchanged — it reads `output`/`row`/`rule`; pass the record as `row`).
  - Refusal gate (exit 4) now counts, in addition to pending matching/semantic: tables with `classification is None` and chunks with `done == False` — printed as `pending mapping=… pending canonicalize=… pending matching=… pending semantic=…`. `--allow-pending` marks: unanswered tables → `classification = "mapping-pass-not-run"`; unanswered chunks → `done=True` + failed records with note `"canonicalize-pass-not-run"` for each of their unaccounted rows (disposition `"record"`); unanswered matching records → `T4` + `matching-pass-not-run` warning; unanswered semantic pairs → `Cannot Assess` `semantic-pass-not-run` findings (as today).
  - `assign_confidence(match_record, finding, skeptic_outcome)` REWRITE: margin/retried → Low; sweep-originated (`finding.rule_id ∈ match_record.sweep_origin_rule_ids`) → Medium when (deterministic OR skeptic upheld) else Low — never High; else T0/T1/T2+deterministic → High; T2+semantic+upheld → Medium; else Low.
  - Claim + review loop additions per finding: `company_compliance_claim`, `claim_normalized`, `interpretation_note`, `claim_flags` (`company-declared-deviation` when claim_normalized==deviation; `claim-contradicted` when claim comply + verdict Non-Compliant), `sweep_originated` bool. `human_review_needed` additionally true when: claim_flags non-empty, `sweep_originated`, or the record's table classification is `"uncertain"`.
  - Coverage call: `coverage_mod.compute(skel["tables"], tstate_by_index, company_records, official_rules, match_state_for_coverage, ignored_ids)` where `match_state_for_coverage = match_state` (no needs-structuring filter anymore) and `_ignored_row_ids` now iterates `company_records` (context from `source_reference.sheet_or_section`) returning record_ids.
  - `final.json` gains `"table_triage"`: one entry per skeleton table `{table_index, sheet_or_section, classification, irrelevant_reason, context_grouping, row_count, column_mapping}`; warnings gain `{"code": "uncertain-table", "detail": "table=N"}` and `{"code": "mapping-failed", "detail": "table=N"}` entries; `unmatched_rows`/`ambiguous` entries keyed `record_id` (keep `original_company_text` + `source_reference`); `unresolved_rows` = records with `status == "extraction-failed"`.
  - `unaddressed_rules` computed against the UNION of all `matched_rule_ids`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`)

```python
def _full_run(tmp_path, fixture_paths, match_picks=1):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    m_reqs = common.read_jsonl(run_dir / "matching_requests.jsonl")
    answers = [_match_answer(r, [c["rule_id"]
                                 for c in r["candidates"]][:match_picks])
               for r in m_reqs]
    common.write_jsonl(run_dir / "matching_responses.jsonl", answers)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    return run_dir


def test_finalize_claim_flags_and_triage(tmp_path, fixture_paths):
    run_dir = _full_run(tmp_path, fixture_paths)
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))

    triage = {t["table_index"]: t for t in final["table_triage"]}
    assert triage[1]["classification"] == "irrelevant"
    assert triage[4]["classification"] == "stig_relevant"

    cov = final["coverage"]["company"]
    assert cov["ignored_irrelevant_table"] == 4   # 2 general-info + 2 instructions rows
    assert cov["total"] == 8

    dev_findings = [f for f in final["findings"]
                    if f["claim_normalized"] == "deviation"]
    assert dev_findings
    for f in dev_findings:
        assert "company-declared-deviation" in f["claim_flags"]
        assert f["human_review_needed"] is True

    comply_bad = [f for f in final["findings"]
                  if f["claim_normalized"] == "comply"
                  and f["verdict"] == "Non-Compliant"]
    for f in comply_bad:
        assert "claim-contradicted" in f["claim_flags"]


def test_finalize_refuses_on_pending_extraction(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report"])
    assert rc == 4


def test_sweep_originated_findings_capped_medium(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_extraction(run_dir)
    _finish_matching_as_none(run_dir)
    assert pipeline.main(["sweep", "--run-dir", str(run_dir)]) == 0
    s_reqs = common.read_jsonl(run_dir / "sweep_requests.jsonl")
    batch = s_reqs[0]
    rec = batch["records"][0]
    rule_id = batch["rules_index"][0]["rule_id"]
    common.write_jsonl(run_dir / "sweep_responses.jsonl",
                       [{"sweep_id": batch["sweep_id"],
                         "proposals": [{"record_id": rec["record_id"],
                                        "rule_id": rule_id}]}])
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    m_reqs = [r for r in
              common.read_jsonl(run_dir / "matching_requests.jsonl")
              if r.get("sweep_round")]
    answers = [_match_answer(r, [rule_id]) for r in m_reqs
               if r["record_id"] == rec["record_id"]]
    with open(run_dir / "matching_responses.jsonl", "a",
              encoding="utf-8") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    rc = pipeline.main(["finalize", "--run-dir", str(run_dir),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    swept = [f for f in final["findings"] if f["sweep_originated"]]
    assert swept
    for f in swept:
        assert f["confidence"] in ("Medium", "Low")
        assert f["human_review_needed"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py -v -k "finalize_claim or refuses_on_pending or capped_medium"`
Expected: FAIL (finalize still reads `company_rows.jsonl` / old semantic keys)

- [ ] **Step 3: Implement.** In `scripts/pipeline.py` `cmd_finalize` (region by region):

**3a. Loading block:** replace `company_rows`/`rows_by_id` with:

```python
    skel = json.loads((run_dir / "skeleton.json").read_text(encoding="utf-8"))
    table_state = _read_jsonl_opt(run_dir / "table_state.jsonl")
    tstate_by_index = {t["table_index"]: t for t in table_state}
    tables_by_index = {t["table_index"]: t for t in skel["tables"]}
    company_records = _read_jsonl_opt(run_dir / "company_records.jsonl")
    records_by_id = {r["record_id"]: r for r in company_records}
```

**3b. Semantic pass:** pair keys become `(resp["record_id"], resp["rule_id"])`; `semantic_pairs = {(r["record_id"], r["rule_id"]) for r in semantic_requests_all}`; the row/rule lookups use `records_by_id` / `rules_by_id`; failures use the per-rule dict:

```python
        n = m["semantic_failures"].get(ruleid, 0) + 1
        m["semantic_failures"][ruleid] = n
        m["retried"] = True
        ...
        if n >= 2:
            resolved_pairs.add(pair)
            semantic_findings.append(_build_finding(
                rid, record["row_id"], ruleid, "Cannot Assess",
                "llm-output-rejected", False, None, None, None, [], m,
                record, rule))
        else:
            new_semantic_requests.append(
                {"record_id": rid, "rule_id": ruleid, "record": record,
                 "rule": rule,
                 "instructions_file": "prompts/semantic_compare.md",
                 "retry": True, "previous_errors": errs})
```
The success branch calls `_build_finding(rid, record["row_id"], ruleid, resp["verdict"], "semantic-comparison", False, resp["finding_type"], {...quotes...}, resp.get("interpretation"), [], m, record, rule)`. `validate.validate_semantic_output(resp, record, rule)` — record passed as the `row` argument.

**3c. Refusal gate:** compute and print all four pending sets:

```python
    pending_tables = [t["table_index"] for t in table_state
                      if t["classification"] is None]
    pending_chunks = [(t["table_index"], cid)
                      for t in table_state
                      for cid, c in t.get("chunks", {}).items()
                      if not c["done"]]
    ...
    if (pending_tables or pending_chunks or pending_matching_ids or
            pending_semantic_pairs) and not args.allow_pending:
        print(f"finalize: refused - pending mapping={len(pending_tables)} "
              f"pending canonicalize={len(pending_chunks)} "
              f"pending matching={len(pending_matching_ids)} "
              f"pending semantic={len(pending_semantic_pairs)} "
              f"(use --allow-pending to force)")
        return 4
```

`--allow-pending` handling before findings assembly:

```python
    if args.allow_pending:
        for tix in pending_tables:
            tstate_by_index[tix]["classification"] = "mapping-pass-not-run"
        for tix, cid in pending_chunks:
            ts = tstate_by_index[tix]
            chunk = ts["chunks"][cid]
            chunk["done"] = True
            table = tables_by_index[tix]
            rows_by_index = {r["row_index"]: r for r in table["rows"]}
            for ri in chunk["row_indexes"]:
                if str(ri) not in ts["row_dispositions"]:
                    ts["row_dispositions"][str(ri)] = "record"
                    rec = canonical.failed_record(
                        table, rows_by_index[ri], "canonicalize-pass-not-run")
                    company_records.append(rec)
                    records_by_id[rec["record_id"]] = rec
```
(matching/semantic allow-pending branches stay, keyed by record_id.)

**3d. Claim/confidence/review loop** (inside `for f in kept:`): after computing `f["confidence"] = assign_confidence(m, f, skeptic_outcome)` add:

```python
        record = records_by_id.get(f["record_id"], {})
        f["company_compliance_claim"] = record.get(
            "company_compliance_claim", "")
        f["claim_normalized"] = record.get("claim_normalized", "unknown")
        f["interpretation_note"] = record.get("interpretation_note", "")
        flags = []
        if f["claim_normalized"] == "deviation":
            flags.append("company-declared-deviation")
        if f["claim_normalized"] == "comply" and \
                f.get("verdict") == "Non-Compliant":
            flags.append("claim-contradicted")
        f["claim_flags"] = flags
        f["sweep_originated"] = f["rule_id"] in \
            m.get("sweep_origin_rule_ids", [])
```
and extend the review triggers: `if flags: review = True`; `if f["sweep_originated"]: review = True`; `if tstate_by_index.get(record.get("source_reference", {}).get("table_index"), {}).get("classification") == "uncertain": review = True`. The Cannot-Assess-with-evidence trigger reads the record: `record.get("observed_value_or_evidence", "")`.

**3e. `assign_confidence` rewrite** (module level):

```python
def assign_confidence(match_record, finding, skeptic_outcome):
    if match_record.get("margin_flag") or match_record.get("retried"):
        return "Low"
    deterministic = bool(finding.get("deterministic"))
    tier = match_record.get("tier")
    if finding.get("rule_id") in match_record.get("sweep_origin_rule_ids", []):
        if deterministic or skeptic_outcome == "upheld":
            return "Medium"
        return "Low"
    if tier in ("T0", "T1", "T2") and deterministic:
        return "High"
    if tier == "T2" and not deterministic and skeptic_outcome == "upheld":
        return "Medium"
    return "Low"
```

**3f. Coverage + leftovers + final:**

```python
    ignored_ids = _ignored_row_ids(registry, company_records, doc_type)
    coverage = coverage_mod.compute(skel["tables"], tstate_by_index,
                                    company_records, official_rules,
                                    match_state, ignored_ids)
```
`_ignored_row_ids` body: iterate `company_records`, return `{row["record_id"] ...}` (context helper unchanged — `_context_for_row` reads `source_reference.sheet_or_section` which records carry). Leftover blocks: `unmatched_rows`/`ambiguous` iterate match_state with `records_by_id[m["record_id"]]`, keeping keys `record_id`, `original_company_text`, `source_reference` (+ `warnings`/`ambiguous_rule_ids`/`candidates` as before); `matched_rule_ids_union = set().union(*[m["matched_rule_ids"] for m in match_state if m["tier"] in _MATCHED_TIERS] or [set()])` feeds `unaddressed_rules`; `unresolved_rows = [ ... for r in company_records if r["status"] == "extraction-failed"]`. Triage + warnings:

```python
    table_triage = []
    triage_warnings = []
    for t in skel["tables"]:
        ts = tstate_by_index.get(t["table_index"], {})
        table_triage.append({
            "table_index": t["table_index"],
            "sheet_or_section": t["sheet_or_section"],
            "classification": ts.get("classification"),
            "irrelevant_reason": ts.get("irrelevant_reason", ""),
            "context_grouping": ts.get("context_grouping", ""),
            "row_count": len(t["rows"]),
            "column_mapping": ts.get("column_mapping", {})})
        if ts.get("classification") == "uncertain":
            triage_warnings.append({"code": "uncertain-table",
                                    "detail": f"table={t['table_index']}"})
        elif ts.get("classification") in ("mapping-failed",
                                          "mapping-pass-not-run"):
            triage_warnings.append({"code": "mapping-failed",
                                    "detail": f"table={t['table_index']}"})
```
Add `triage_warnings` into the `warnings` concatenation and `"table_triage": table_triage` into `final`. Persist `table_state.jsonl` and `company_records.jsonl` in the pre-refusal persist block (they may have gained allow-pending mutations — write them right after the gate instead, alongside the existing `match_state` write at the end; the pre-gate persist block keeps its existing writes plus `table_state`/`company_records` so retry bookkeeping survives a refusal).

**3g. Dedup/contradictions key on record_id.** In `scripts/validate.py`, `dedup_findings` keys on `(f["record_id"], f["rule_id"], f["finding_type"])` and `find_contradictions` groups by `(f["record_id"], f["rule_id"])` — two sub-records of the same Word row share a `row_id`, and their findings against the same rule must NOT dedup or read as contradictory. Add to `tests/test_validate.py`:

```python
def test_dedup_and_contradictions_key_on_record_id():
    f1 = {"finding_id": "F-1", "record_id": "CR-a", "row_id": "R-x",
          "rule_id": "V-1", "finding_type": None, "verdict": "Compliant"}
    f2 = {"finding_id": "F-2", "record_id": "CR-b", "row_id": "R-x",
          "rule_id": "V-1", "finding_type": None, "verdict": "Non-Compliant"}
    kept, dropped = validate.dedup_findings([f1, f2])
    assert len(kept) == 2 and dropped == []
    assert validate.find_contradictions(kept) == []
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py tests/test_coverage.py tests/test_validate.py -v`
Expected: PASS (all pipeline-stage tests green now)

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): finalize with claim flags, sweep caps, triage, skeleton coverage"
```

---

### Task 15: `report.py` — triage panel, claim badges, interpretation styling, sweep labels

**Files:**
- Modify: `stig-compare/scripts/report.py`
- Test: `stig-compare/tests/test_report.py`

**Interfaces:**
- Consumes: `final.json` shape from Task 14 (`table_triage`, findings with `claim_flags`/`claim_normalized`/`interpretation_note`/`sweep_originated`/`record_id`).
- Produces: `report.render(run_dir)` unchanged signature. New: `_triage_html(final)` section rendered between the dashboard and the filters; per-finding claim badges and labels.

- [ ] **Step 1: Write the failing test** (append to `tests/test_report.py`; reuse that file's existing helper for building a minimal `final.json` — extend the helper's finding dict with `"record_id": "CR-1"`, `"claim_flags": ["company-declared-deviation"]`, `"claim_normalized": "deviation"`, `"company_compliance_claim": "DEVIATION"`, `"interpretation_note": "note text"`, `"sweep_originated": True`, and add a top-level `"table_triage"` list)

```python
def test_report_renders_triage_and_claim_badges(tmp_path, minimal_final):
    minimal_final["table_triage"] = [
        {"table_index": 1, "sheet_or_section": "document-body",
         "classification": "irrelevant", "irrelevant_reason": "instructions",
         "context_grouping": "", "row_count": 3, "column_mapping": {}},
        {"table_index": 2, "sheet_or_section": "document-body",
         "classification": "stig_relevant", "irrelevant_reason": "",
         "context_grouping": "JB.1.1", "row_count": 5,
         "column_mapping": {"0": "stig_description"}}]
    f = minimal_final["findings"][0]
    f["claim_flags"] = ["company-declared-deviation", "claim-contradicted"]
    f["claim_normalized"] = "deviation"
    f["company_compliance_claim"] = "DEVIATION"
    f["interpretation_note"] = "reviewer note"
    f["sweep_originated"] = True
    run_dir = tmp_path
    (run_dir / "final.json").write_text(json.dumps(minimal_final),
                                        encoding="utf-8")
    report.render(run_dir)
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Table triage" in html
    assert "irrelevant" in html and "instructions" in html
    assert "company-declared-deviation" in html
    assert "claim-contradicted" in html
    assert "Interpretation (not evidence)" in html
    assert "sweep-originated" in html
```

(If `test_report.py` has no `minimal_final`-style fixture, build the dict inline by copying the smallest `final` dict already used in that file's existing tests and extending it as above.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_report.py -v -k triage`
Expected: FAIL (`"Table triage" not in html`)

- [ ] **Step 3: Implement.** In `scripts/report.py`:
  - Add CSS to `_CSS`: `.badge-claim{background:#7a1f1f;color:#fff;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}` `.badge-sweep{background:#5b4a12;color:#fff;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}` `.interp{border-left:3px solid #888;padding:4px 8px;margin:6px 0;font-style:italic;opacity:.85}` `.triage-table td,.triage-table th{padding:4px 8px;border-bottom:1px solid #333}`.
  - Add:

```python
def _triage_html(final):
    rows = []
    for t in final.get("table_triage", []):
        cls = esc(str(t.get("classification")))
        rows.append(
            f"<tr><td>{t['table_index']}</td>"
            f"<td>{esc(t.get('sheet_or_section', ''))}</td>"
            f"<td>{cls}</td>"
            f"<td>{esc(t.get('irrelevant_reason', ''))}</td>"
            f"<td>{esc(t.get('context_grouping', ''))}</td>"
            f"<td>{t.get('row_count', 0)}</td></tr>")
    if not rows:
        return ""
    return ("<section><h2>Table triage</h2>"
            "<table class='triage-table'><tr><th>#</th><th>Location</th>"
            "<th>Classification</th><th>Reason</th><th>Grouping</th>"
            "<th>Rows</th></tr>" + "".join(rows) + "</table></section>")
```

  - In `_finding_html(f)`: after the verdict/confidence chips add
    `"".join(f'<span class="badge-claim">{esc(fl)}</span>' for fl in f.get("claim_flags", []))`
    and `'<span class="badge-sweep">sweep-originated</span>' if f.get("sweep_originated") else ''`;
    show the claim itself in the evidence key-values (`_kv_rows`) as `("Company claim", f.get("company_compliance_claim", ""))`; and when `f.get("interpretation_note")` render
    `f'<div class="interp"><b>Interpretation (not evidence):</b> {esc(f["interpretation_note"])}</div>'`.
  - In `render(...)`'s HTML assembly, insert `_triage_html(final)` right after `_dashboard_html(final)`.
  - Update anything in `report.py` that reads `f["row_id"]` for display to prefer `f.get("record_id", f.get("row_id"))` (feedback export JS included — the export payload should carry `finding_id` as today, unchanged).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/report.py stig-compare/tests/test_report.py
git commit -m "feat(stig-compare): report triage panel, claim badges, interpretation styling"
```

---

### Task 16: `feedback.py` + `regression.py` compatibility

**Files:**
- Modify: `stig-compare/scripts/feedback.py`, `stig-compare/scripts/regression.py`
- Test: `stig-compare/tests/test_feedback.py`, `stig-compare/tests/test_regression.py`

**Interfaces:**
- Consumes: `final.json`/run-dir shape from Task 14; canonical records.
- Produces:
  - `feedback._load_replay_lookups(run_dir)` reads `company_records.jsonl` (was `company_rows.jsonl`) and keys company lookups by `record_id`; `_build_snapshot` resolves the finding's record via `finding["record_id"]`, storing the snapshot's company excerpt under the existing `company_row` key (schema stability for old cases).
  - `regression.run_case` gains record-era compatibility: before replay, `row = dict(snapshot["company_row"]); row.setdefault("record_id", row.get("row_id", "regression-row")); row.setdefault("status", "ok")`. Tier/match reading becomes `matched = match.get("matched_rule_ids") or []; matched_rule_id = matched[0] if matched else None`. `_ROW_FIELDS` extends with `"company_compliance_claim", "company_severity", "remarks_or_justification"`.
  - Old regression case files (`RC-*.json`) keep replaying without edits — that is the point of the setdefaults.

- [ ] **Step 1: Write the failing tests.** In `tests/test_regression.py` append:

```python
def test_run_case_accepts_legacy_row_id_snapshot():
    case = {"case_id": "RC-legacy", "snapshot": {
        "company_row": {
            "row_id": "R-old", "status": "ok",
            "original_company_text":
                "Run SHOW PARAMETER password_reuse_max | 9 or more | 9",
            "context_grouping": "High",
            "stig_command_or_value": "Run SHOW PARAMETER password_reuse_max",
            "observed_value_or_evidence": "9"},
        "official_rules": [{
            "rule_id": "V-1001",
            "title": "Password reuse must be restricted",
            "severity": "high",
            "check_text": "Run SHOW PARAMETER password_reuse_max",
            "fix_text": "Set password_reuse_max to 9 or more.",
            "expected_value": "9 or more"}]},
        "expected": {"matched_rule_id": "V-1001", "verdict": "Compliant"}}
    registry = {"registry_version": 1, "rules": []}
    result = regression.run_case(case, registry)
    assert result["passed"], result["detail"]
```

In `tests/test_feedback.py`, update the run-dir builders that write `company_rows.jsonl` to write `company_records.jsonl` with records carrying `record_id` (reuse each test's existing row dicts, add `"record_id": "CR-" + <old row_id suffix>`), and update finding dicts to carry `record_id`. Assertions on stored snapshots stay on the `company_row` key.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_regression.py tests/test_feedback.py -v`
Expected: FAIL (`KeyError: 'record_id'` in candidates via run_case; feedback lookups miss `company_records.jsonl`)

- [ ] **Step 3: Implement** the changes listed under Interfaces (three small edits in `regression.py`: the setdefault lines at the top of `run_case`'s replay, the matched-rule reading, `_ROW_FIELDS`; in `feedback.py`: `_load_replay_lookups` file name + key change to `record_id` with `row_id` fallback `rows_by_id = {r.get("record_id", r.get("row_id")): r ...}`, `_build_snapshot` resolves via `finding.get("record_id", finding.get("row_id"))`).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_regression.py tests/test_feedback.py tests/test_rules.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/feedback.py stig-compare/scripts/regression.py stig-compare/tests/test_feedback.py stig-compare/tests/test_regression.py
git commit -m "feat(stig-compare): feedback and regression compatibility with canonical records"
```

---

### Task 17: SKILL.md rewrite, retire old extraction, end-to-end test, versions

**Files:**
- Modify: `stig-compare/SKILL.md`, `stig-compare/VERSIONS.json`, `stig-compare/scripts/extract.py`, `stig-compare/scripts/pipeline.py` (dead-code removal only), `stig-compare/tests/test_prompts_and_skill.py`, `stig-compare/tests/test_end_to_end.py`
- Delete: `stig-compare/prompts/structuring.md`, `stig-compare/tests/test_extract_company.py`
- Test: full suite

**Interfaces:**
- Consumes: everything above.
- Produces: the shipping skill. `extract.py` keeps ONLY official-side extraction plus `COMPANY_HEADER_HINTS` (rename the dict itself; delete `extract_company`, `_company_tables`, `_has_merged_cells`, `_COMPANY_FIELDS`, and the company branch in `main()`). `pipeline.py` loses any remaining structuring references. `VERSIONS.json`: `extraction_version` and `pipeline_version` and `report_schema_version` → `"0.2.0"` (skill_version → `"0.2.0"` too).

- [ ] **Step 1: Rewrite the end-to-end test.** Replace `tests/test_end_to_end.py` with a scripted full run against `company_real_docx` reusing the helpers already added to `test_pipeline.py` (import them: `from test_pipeline import _answer_extraction, _match_answer, EX1_MAPPING, EX2_MAPPING`):

```python
def test_end_to_end_real_format(tmp_path, fixture_paths):
    run_dir = tmp_path / "run"
    assert pipeline.main(["start",
                          "--official", str(fixture_paths["official_csv"]),
                          "--company",
                          str(fixture_paths["company_real_docx"]),
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_end_to_end.py -v`
Expected: FAIL until old test content replaced / passes once replaced — if it passes immediately after replacement, continue.

- [ ] **Step 3: Retire old code and rewrite SKILL.md.**
  - Delete `prompts/structuring.md` and `tests/test_extract_company.py` (git rm).
  - `extract.py`: rename `COMPANY_HEADER_SYNONYMS` → `COMPANY_HEADER_HINTS` (drop the Task-10 alias), delete `extract_company`, `_company_tables`, `_has_merged_cells`, `_COMPANY_FIELDS`, and reduce `main()` to the `official` subcommand.
  - `pipeline.py`: remove any remaining `structuring` references (grep for `structuring`), remove `_STRUCT_FIELDS` if still present.
  - `VERSIONS.json`: bump the four version strings to `"0.2.0"` (keep `rule_registry_version` untouched).
  - SKILL.md: keep frontmatter, hard-rules section (drop the structuring-specific wording; the untrusted-input paragraph stays, now naming table-mapping/canonicalize/matching/sweep/semantic responses), Feedback mode, Review mode. Replace Compare mode steps 3–5 with:

```markdown
3. **Start the run** (`pipeline.py start ...` — unchanged invocation).
   Non-zero exit: surface and stop, as before.

4. **Answer table-mapping requests, then resolve — repeat while there is
   new work, capped at 2 rounds.** After `start` (and after every
   `resolve`), `table_mapping_requests.jsonl` may contain unanswered
   records: for each, read `prompts/table_mapping.md`, follow it exactly,
   and append one JSON object per line to `table_mapping_responses.jsonl`.
   Run `python scripts/pipeline.py resolve --run-dir runs/<ts>`. Retried
   requests carry `retry: true` and `previous_errors`.

5. **Answer canonicalize requests — same loop shape, capped at 2 rounds.**
   For each unanswered record in `canonicalize_requests.jsonl`, read
   `prompts/canonicalize.md`, follow it, append to
   `canonicalize_responses.jsonl`, then `resolve`. Every row of every
   chunk must be accounted for — a chunk response that loses rows is
   rejected mechanically and retried once.

6. **Answer matching requests — 2-round loop as before** (multi-select:
   one selection per genuinely-matching candidate; `none`/`ambiguous`
   always acceptable), then:

7. **Run the sweep once:** `python scripts/pipeline.py sweep --run-dir
   runs/<ts>`. If it writes `sweep_requests.jsonl`, answer each batch per
   `prompts/sweep.md` (proposals are candidates, not matches), `resolve`,
   then answer the resulting `sweep_round` matching requests and
   `resolve` again — the sweep never repeats.

8. **Answer semantic requests / finalize / skeptic / final finalize** —
   unchanged from the previous workflow (2-round semantic loop with
   `finalize --no-report`, exit 4 as the designed continue signal;
   skeptic subagents on semantic findings; one final
   `finalize --allow-pending` that renders the report).

9. **Present results:** warnings first (now including `uncertain-table`,
   `mapping-failed`, `company-declared-deviation`, `claim-contradicted`),
   then coverage (note the `ignored_irrelevant_table` bucket and the
   table-triage panel), then the report path and feedback offer.
```

  - Update `tests/test_prompts_and_skill.py` SKILL.md assertions to the new step names (assert the strings `table_mapping_responses.jsonl`, `canonicalize_responses.jsonl`, `sweep`, `--allow-pending` appear in SKILL.md).

- [ ] **Step 4: Run the FULL suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS. If anything fails, fix before committing — do not skip tests.

- [ ] **Step 5: Commit**

```bash
git add -A stig-compare/
git commit -m "feat(stig-compare): SKILL.md Claude-first workflow; retire structuring pipeline"
```

---

## Execution notes

- Tasks 1–9 are independent of the pipeline and keep the full suite green except where a task explicitly says otherwise (Tasks 6, 10–14 leave `test_pipeline.py`/`test_end_to_end.py` partially red until Task 14/17 — run only the test files named in each task's steps during that window).
- Task order is dependency order; do not reorder Tasks 10–14.
- After Task 17, `git log` should show 17 commits for this plan; the suite must be fully green before the branch is offered for review (superpowers:finishing-a-development-branch).






