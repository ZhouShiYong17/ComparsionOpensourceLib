# STIG Comparison Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `stig-compare` Claude Code Skill that compares a company STIG submission (DOCX/XLSX) against an official STIG file (CSV/JSON/XLSX) through a deterministic-core pipeline with narrow, evidence-verified Claude passes, and renders a self-contained verification-first HTML report.

**Architecture:** Deterministic Python scripts own parsing, provenance, normalization, candidate generation, value comparison, validation, coverage, and reporting; artifacts flow as JSON/JSONL through `runs/<run-id>/`. Claude passes (structuring, match adjudication, semantic comparison, skeptical validation) are orchestrated by SKILL.md between deterministic stages, and their outputs are treated as untrusted input — schema- and evidence-checked by `validate.py` before entering any report.

**Tech Stack:** Python 3.10+, openpyxl, python-docx, pytest. Nothing else — no network, no other third-party packages (validation is hand-rolled, not `jsonschema`).

**Spec:** `docs/superpowers/specs/2026-08-10-stig-comparison-skill-design.md` — the authority on behavior. Read it before starting any task.

## Global Constraints

- Dependencies: Python stdlib + `openpyxl` + `python-docx` (+ `pytest` for tests). No other imports. No network calls anywhere.
- All run state lives under `stig-compare/runs/<run-id>/` as JSON/JSONL; `runs/` is gitignored.
- Raw values are never mutated. Normalization is additive (`normalized` sub-dict), never destructive.
- Every quote check compares after whitespace folding only (`fold_ws`).
- Company row IDs: `"R-" + short_hash(table_index, row_index, raw_row_text)`. Finding IDs: `"F-" + short_hash(row_id, rule_id, finding_type)`.
- Matching tiers: T0 exact ID, T1 unique technical signature, T2 shortlist adjudication, T3 ambiguous, T4 unmatched. Severity agreement is a tie-breaker feature only — never sufficient for a match.
- Defaults: shortlist K=5, score floor 0.05, ambiguity margin = top-2 lexical scores within 15% relative.
- Hard rule: empty/missing `observed_value_or_evidence` → verdict `Cannot Assess`, deterministically; no Claude output can override.
- Confidence classes: High / Medium / Low with the spec §6 criteria; `human_review_needed` is an orthogonal boolean.
- Coverage buckets must sum exactly to extraction totals or the run fails loudly. Any extraction failure warns; >10% of rows failed or ignored → top-level red banner.
- Report: one self-contained HTML file, inline CSS/JS, zero external assets, works from `file://`.
- Logs and exceptions must never include document text — IDs, counts, statuses only.
- Commit after every task (steps include the commands).

## File Structure

Everything lives in `stig-compare/` at the repo root:

```
stig-compare/
  SKILL.md                     # Task 16 — orchestration for the three modes
  VERSIONS.json                # Task 1 — component versions; prompt hashes computed at runtime
  scripts/
    common.py                  # Task 1 — hashing, IDs, JSONL IO, fold_ws, versions
    extract.py                 # Tasks 3-4 — official + company extraction CLIs
    normalize.py               # Task 5
    compare_values.py          # Task 6
    candidates.py              # Task 7
    validate.py                # Task 8
    rules.py                   # Task 9
    coverage.py                # Task 10
    pipeline.py                # Task 11 — stage orchestration CLI
    report.py                  # Task 12
    feedback.py                # Task 13
    regression.py              # Task 14
  prompts/
    structuring.md             # Task 15
    matching.md                # Task 15
    semantic_compare.md        # Task 15
    validator.md               # Task 15
  rules/
    registry.json              # Task 9 — seed registry (empty rule list, version 1)
    candidates/                # Task 13 output dir (.gitkeep)
  feedback/                    # Task 13 output dir (.gitkeep)
  tests/
    fixtures/build_fixtures.py # Task 2 — builds synthetic files into tests/fixtures/generated/
    regression/                # Task 13/14 — feedback-derived cases
    test_common.py             # Task 1
    test_fixtures.py           # Task 2
    test_extract_official.py   # Task 3
    test_extract_company.py    # Task 4
    test_normalize.py          # Task 5
    test_compare_values.py     # Task 6
    test_candidates.py         # Task 7
    test_validate.py           # Task 8
    test_rules.py              # Task 9
    test_coverage.py           # Task 10
    test_pipeline.py           # Task 11
    test_report.py             # Task 12
    test_feedback.py           # Task 13
    test_regression.py         # Task 14
    test_prompts_and_skill.py  # Task 15
    test_end_to_end.py         # Task 16
  runs/                        # gitignored
```

Run all tests from the repo root with: `python -m pytest stig-compare/tests -v`
(a `stig-compare/tests/conftest.py` created in Task 1 puts `scripts/` on `sys.path`, so tests import modules as `import common`, `import extract`, etc.)

---

### Task 1: Scaffolding and `common.py`

**Files:**
- Create: `stig-compare/scripts/common.py`
- Create: `stig-compare/tests/conftest.py`
- Create: `stig-compare/VERSIONS.json`
- Create: `.gitignore` (repo root)
- Test: `stig-compare/tests/test_common.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (used by every later task):
  - `short_hash(*parts: str) -> str` — 8-char lowercase hex of SHA-256 over parts joined with `"\x1f"`.
  - `row_id(table_index: int, row_index: int, raw_text: str) -> str` — `"R-" + short_hash(...)` with ints stringified.
  - `finding_id(row_id: str, rule_id: str, finding_type: str) -> str` — `"F-" + short_hash(...)`.
  - `fold_ws(text: str) -> str` — collapse all whitespace runs to single spaces, strip ends.
  - `read_jsonl(path) -> list[dict]` / `write_jsonl(path, records: list[dict]) -> None` (UTF-8, one JSON object per line).
  - `file_sha256(path) -> str` — full hex digest.
  - `load_versions(package_root) -> dict` — parses `VERSIONS.json` and adds `"prompt_hashes"`: `{filename: sha256hex}` for every `.md` in `prompts/` (empty dict if the folder is missing).

- [ ] **Step 1: Create directories, `.gitignore`, `VERSIONS.json`, `conftest.py`**

`.gitignore` (repo root):

```
stig-compare/runs/
__pycache__/
*.pyc
```

`stig-compare/VERSIONS.json`:

```json
{
  "skill_version": "0.1.0",
  "extraction_version": "0.1.0",
  "pipeline_version": "0.1.0",
  "report_schema_version": "0.1.0",
  "rule_registry_version": 1
}
```

`stig-compare/tests/conftest.py`:

```python
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 2: Write the failing tests**

`stig-compare/tests/test_common.py`:

```python
import json
from pathlib import Path

import common


def test_short_hash_stable_and_short():
    a = common.short_hash("x", "y")
    assert a == common.short_hash("x", "y")
    assert len(a) == 8
    assert a != common.short_hash("xy")          # separator prevents collisions
    assert a != common.short_hash("x", "z")


def test_row_id_and_finding_id_prefixes():
    rid = common.row_id(1, 2, "raw text")
    assert rid.startswith("R-") and len(rid) == 10
    assert rid == common.row_id(1, 2, "raw text")   # stable across calls
    fid = common.finding_id(rid, "V-1001", "match")
    assert fid.startswith("F-") and len(fid) == 10


def test_fold_ws():
    assert common.fold_ws("  a\t b\n\nc  ") == "a b c"


def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "x.jsonl"
    records = [{"a": 1}, {"b": "café"}]
    common.write_jsonl(p, records)
    assert common.read_jsonl(p) == records


def test_file_sha256(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert common.file_sha256(p) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_load_versions_includes_prompt_hashes(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "matching.md").write_text("PROMPT", encoding="utf-8")
    (tmp_path / "VERSIONS.json").write_text(
        json.dumps({"skill_version": "0.1.0"}), encoding="utf-8"
    )
    v = common.load_versions(tmp_path)
    assert v["skill_version"] == "0.1.0"
    assert "matching.md" in v["prompt_hashes"]
    assert len(v["prompt_hashes"]["matching.md"]) == 64
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 4: Implement `stig-compare/scripts/common.py`**

```python
"""Shared primitives: hashing, IDs, JSONL IO, whitespace folding, versions."""
import hashlib
import json
import re
from pathlib import Path

_SEP = "\x1f"
_WS = re.compile(r"\s+")


def short_hash(*parts):
    joined = _SEP.join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]


def row_id(table_index, row_index, raw_text):
    return "R-" + short_hash(table_index, row_index, raw_text)


def finding_id(rid, rule_id, finding_type):
    return "F-" + short_hash(rid, rule_id, finding_type)


def fold_ws(text):
    return _WS.sub(" ", text or "").strip()


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path, records):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_versions(package_root):
    root = Path(package_root)
    versions = json.loads((root / "VERSIONS.json").read_text(encoding="utf-8"))
    hashes = {}
    prompts = root / "prompts"
    if prompts.is_dir():
        for p in sorted(prompts.glob("*.md")):
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    versions["prompt_hashes"] = hashes
    return versions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_common.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add .gitignore stig-compare
git commit -m "feat(stig-compare): scaffolding, VERSIONS.json, common primitives"
```

---

### Task 2: Synthetic fixture builder

**Files:**
- Create: `stig-compare/tests/fixtures/build_fixtures.py`
- Test: `stig-compare/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `openpyxl`, `python-docx` (verifies both are importable in this environment).
- Produces: `build_all(out_dir: Path) -> dict[str, Path]` returning name→path for every fixture. Later tasks call `build_all(tmp_path)` in a session-scoped pytest fixture. Fixture names (keys) later tasks rely on:
  - `"official_csv"` — 5-rule official STIG CSV with columns `Rule ID,Title,Severity,Check Text,Fix Text,Expected Value` (rules `V-1001`..`V-1005`; `V-1001` is password-reuse with check text containing `password_reuse_max` and expected value `9 or more`; `V-1002` is max password age 60 days; `V-1003` audit logging enabled; `V-1004` session timeout `15 minutes`; `V-1005` min password length `14`).
  - `"official_json"` — same 5 rules as a JSON array with keys `rule_id,title,severity,check_text,fix_text,expected_value`.
  - `"official_xlsx"` — same 5 rules on sheet `Rules`, header row 1.
  - `"official_dup_ids_csv"` — 2 rows sharing `V-2001` (duplicate-ID warning case).
  - `"company_docx"` — one Word table, headers `Group|STIG Requirement|Description|Command to Verify|Approved Setting|Observed Value`, 4 rows: row 1 matches V-1001 (approved `9 or more`, observed `9`); row 2 matches V-1002 with paraphrased wording ("passwords must be rotated at least every 60 days", observed `60`); row 3 is vague ("logging checked", no observed value); row 4 has an unknown requirement matching nothing ("screensaver must show corporate logo").
  - `"company_docx_messy"` — same 4 data rows but headers `Area|What we did|How we checked|Value` (unmappable → needs structuring), plus one empty row (extraction-failed case).
  - `"company_xlsx"` — same 4 rows as `company_docx` on sheet `Submission`.

- [ ] **Step 1: Write the failing test**

`stig-compare/tests/test_fixtures.py`:

```python
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
```

Note for the implementer: tests importing `fixtures.build_fixtures` work because
`conftest.py` put `scripts/` on the path but `fixtures` is a package relative to
`tests/` — add an empty `stig-compare/tests/fixtures/__init__.py` and
`stig-compare/tests/__init__.py` in this task so the import resolves.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest stig-compare/tests/test_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fixtures'`

- [ ] **Step 3: Implement `build_fixtures.py`**

```python
"""Builds every synthetic test file. Deterministic content, no randomness."""
import csv
import json
from pathlib import Path

import docx
import openpyxl

OFFICIAL_RULES = [
    {"rule_id": "V-1001", "title": "Password reuse must be restricted",
     "severity": "high",
     "check_text": "Run SHOW PARAMETER password_reuse_max and verify the value.",
     "fix_text": "Set password_reuse_max to 9 or more.",
     "expected_value": "9 or more"},
    {"rule_id": "V-1002", "title": "Maximum password age must be limited",
     "severity": "medium",
     "check_text": "Verify maximum password age is no greater than 60 days.",
     "fix_text": "Set maximum password age to 60 days.",
     "expected_value": "60 days or less"},
    {"rule_id": "V-1003", "title": "Audit logging must be enabled",
     "severity": "high",
     "check_text": "Verify audit logging is enabled for all databases.",
     "fix_text": "Enable audit logging.",
     "expected_value": "enabled"},
    {"rule_id": "V-1004", "title": "Session timeout must be enforced",
     "severity": "medium",
     "check_text": "Verify idle session timeout is 15 minutes or less.",
     "fix_text": "Set session timeout to 15 minutes.",
     "expected_value": "15 minutes or less"},
    {"rule_id": "V-1005", "title": "Minimum password length must be enforced",
     "severity": "high",
     "check_text": "Verify minimum password length is at least 14 characters.",
     "fix_text": "Set minimum password length to 14.",
     "expected_value": "14 or more"},
]

COMPANY_ROWS = [
    ["High", "Password reuse must be restricted",
     "Database users should not reuse recent passwords",
     "Run SHOW PARAMETER password_reuse_max", "9 or more", "9"],
    ["Medium", "Passwords must be rotated at least every 60 days",
     "Password aging is configured on all accounts",
     "Check profile PASSWORD_LIFE_TIME", "60", "60"],
    ["High", "Logging checked", "Logging was reviewed", "", "", ""],
    ["Low", "Screensaver must show corporate logo",
     "Branding requirement from marketing", "Visual inspection", "logo.png", ""],
]

_HEADERS = ["Group", "STIG Requirement", "Description",
            "Command to Verify", "Approved Setting", "Observed Value"]
_MESSY_HEADERS = ["Area", "What we did", "How we checked", "Value"]
_CSV_COLS = ["Rule ID", "Title", "Severity", "Check Text", "Fix Text",
             "Expected Value"]


def _write_official_csv(path, rules):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(_CSV_COLS)
        for r in rules:
            w.writerow([r["rule_id"], r["title"], r["severity"],
                        r["check_text"], r["fix_text"], r["expected_value"]])


def _write_docx(path, headers, rows):
    d = docx.Document()
    t = d.add_table(rows=1, cols=len(headers))
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row[: len(headers)]):
            cells[i].text = val
    d.save(str(path))


def build_all(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    paths["official_csv"] = out / "official.csv"
    _write_official_csv(paths["official_csv"], OFFICIAL_RULES)

    paths["official_json"] = out / "official.json"
    paths["official_json"].write_text(
        json.dumps(OFFICIAL_RULES, indent=1), encoding="utf-8")

    paths["official_xlsx"] = out / "official.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rules"
    ws.append(_CSV_COLS)
    for r in OFFICIAL_RULES:
        ws.append([r["rule_id"], r["title"], r["severity"],
                   r["check_text"], r["fix_text"], r["expected_value"]])
    wb.save(str(paths["official_xlsx"]))

    dup = [dict(OFFICIAL_RULES[0], rule_id="V-2001"),
           dict(OFFICIAL_RULES[1], rule_id="V-2001")]
    paths["official_dup_ids_csv"] = out / "official_dup.csv"
    _write_official_csv(paths["official_dup_ids_csv"], dup)

    paths["company_docx"] = out / "company.docx"
    _write_docx(paths["company_docx"], _HEADERS, COMPANY_ROWS)

    messy = [[r[0], r[1] + ". " + r[2], r[3], r[4]] for r in COMPANY_ROWS]
    messy.append(["", "", "", ""])                     # empty row
    paths["company_docx_messy"] = out / "company_messy.docx"
    _write_docx(paths["company_docx_messy"], _MESSY_HEADERS, messy)

    paths["company_xlsx"] = out / "company.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Submission"
    ws.append(_HEADERS)
    for row in COMPANY_ROWS:
        ws.append(row)
    wb.save(str(paths["company_xlsx"]))

    return paths
```

Also create empty `stig-compare/tests/__init__.py` and
`stig-compare/tests/fixtures/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_fixtures.py -v`
Expected: 3 passed (also proves openpyxl + python-docx are importable here)

- [ ] **Step 5: Commit**

```bash
git add stig-compare/tests
git commit -m "test(stig-compare): synthetic fixture builder for docx/xlsx/csv"
```

---

### Task 3: Official file extraction

**Files:**
- Create: `stig-compare/scripts/extract.py` (official half; Task 4 adds the company half)
- Test: `stig-compare/tests/test_extract_official.py`

**Interfaces:**
- Consumes: `common.write_jsonl`, `common.fold_ws`, fixtures from Task 2.
- Produces:
  - `extract_official(path: str|Path) -> dict` returning `{"records": list[dict], "warnings": list[dict]}`. Each record: `{"rule_id", "title", "severity", "check_text", "fix_text", "expected_value", "provenance": {"source_file", "locator"}, "raw_record"}`. Severity lowercased; missing columns become `""`. Warnings are `{"code": str, "detail": str}` — codes used later: `"duplicate-rule-id"`, `"empty-official-file"`.
  - Header mapping table `OFFICIAL_HEADER_SYNONYMS: dict[str, list[str]]` mapping canonical keys (`rule_id`, `title`, `severity`, `check_text`, `fix_text`, `expected_value`) to lowercase header variants.
  - `_map_headers(headers, synonyms) -> dict[int, str|None]` — column index → canonical key (reused by Task 4).
  - CLI: `python stig-compare/scripts/extract.py official <file> --out <path.jsonl>` writes records to JSONL and a sibling `<path>.warnings.json` with the warnings list. Exit 0 normally, exit 2 if the file is unreadable.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_extract_official.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_extract_official.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'extract'`

- [ ] **Step 3: Implement the official half of `extract.py`**

```python
"""Extraction: official STIG (CSV/JSON/XLSX) and company submission (DOCX/XLSX).

All records carry provenance. Unreadable content becomes warnings or
extraction-failed items — never silent drops. No document text in error output.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import openpyxl

import common

OFFICIAL_HEADER_SYNONYMS = {
    "rule_id": ["rule id", "ruleid", "stig id", "stigid", "vuln id", "vulnid",
                "v-id", "id", "group id"],
    "title": ["title", "rule title", "name"],
    "severity": ["severity", "cat", "category", "risk"],
    "check_text": ["check text", "check", "checkcontent", "check content"],
    "fix_text": ["fix text", "fix", "fixtext", "fix content"],
    "expected_value": ["expected value", "expected", "required value",
                       "baseline value"],
}


def _map_headers(headers, synonyms):
    """Column index -> canonical key (or None if unmapped)."""
    mapping = {}
    for idx, h in enumerate(headers):
        key = None
        h_low = common.fold_ws(str(h or "")).lower()
        for canon, variants in synonyms.items():
            if h_low == canon.replace("_", " ") or h_low == canon or h_low in variants:
                key = canon
                break
        mapping[idx] = key
    return mapping


def _rows_from_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _rows_from_xlsx_sheet(ws):
    return [["" if c.value is None else str(c.value) for c in row]
            for row in ws.iter_rows()]


def _official_from_table(rows, source_file, locator_prefix):
    records, warnings = [], []
    if len(rows) < 2:
        warnings.append({"code": "empty-official-file",
                         "detail": f"{locator_prefix}: no data rows"})
        return records, warnings
    mapping = _map_headers(rows[0], OFFICIAL_HEADER_SYNONYMS)
    for n, row in enumerate(rows[1:], start=2):
        if not any(common.fold_ws(str(c)) for c in row):
            continue
        rec = {k: "" for k in OFFICIAL_HEADER_SYNONYMS}
        raw = {}
        for idx, val in enumerate(row):
            header = str(rows[0][idx]) if idx < len(rows[0]) else f"col{idx}"
            raw[header] = str(val)
            canon = mapping.get(idx)
            if canon:
                rec[canon] = common.fold_ws(str(val))
        rec["severity"] = rec["severity"].lower()
        rec["provenance"] = {"source_file": Path(source_file).name,
                             "locator": f"{locator_prefix},row={n}"}
        rec["raw_record"] = raw
        records.append(rec)
    return records, warnings


def extract_official(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records, warnings = _official_from_table(_rows_from_csv(path), path, "csv")
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        records, warnings = [], []
        for n, item in enumerate(data):
            rec = {k: common.fold_ws(str(item.get(k, "")))
                   for k in OFFICIAL_HEADER_SYNONYMS}
            rec["severity"] = rec["severity"].lower()
            rec["provenance"] = {"source_file": path.name,
                                 "locator": f"json,index={n}"}
            rec["raw_record"] = {k: str(v) for k, v in item.items()}
            records.append(rec)
        if not records:
            warnings.append({"code": "empty-official-file", "detail": "json: empty"})
    elif suffix == ".xlsx":
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        records, warnings = [], []
        for ws in wb.worksheets:
            r, w = _official_from_table(_rows_from_xlsx_sheet(ws), path,
                                        f"sheet={ws.title}")
            records.extend(r)
        if not records:
            warnings.append({"code": "empty-official-file",
                             "detail": "xlsx: no data rows in any sheet"})
    else:
        raise ValueError(f"unsupported official file type: {suffix}")

    counts = Counter(r["rule_id"] for r in records if r["rule_id"])
    for rid, n in sorted(counts.items()):
        if n > 1:
            warnings.append({"code": "duplicate-rule-id",
                             "detail": f"{rid} appears {n} times"})
    return {"records": records, "warnings": warnings}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    for kind in ("official", "company"):
        p = sub.add_parser(kind)
        p.add_argument("file")
        p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    fn = extract_official if args.kind == "official" else extract_company
    try:
        result = fn(args.file)
    except Exception as e:                        # no document text in errors
        print(f"extract: cannot read file: {type(e).__name__}", file=sys.stderr)
        return 2
    common.write_jsonl(args.out, result["records"])
    Path(str(args.out) + ".warnings.json").write_text(
        json.dumps(result["warnings"], indent=1), encoding="utf-8")
    print(f"{args.kind}: {len(result['records'])} records, "
          f"{len(result['warnings'])} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`extract_company` does not exist yet — add a stub `def extract_company(path): raise NotImplementedError` so the module imports; Task 4 replaces it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_extract_official.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/extract.py stig-compare/tests/test_extract_official.py
git commit -m "feat(stig-compare): official STIG extraction (csv/json/xlsx) with provenance and warnings"
```

---

### Task 4: Company file extraction

**Files:**
- Modify: `stig-compare/scripts/extract.py` (replace the `extract_company` stub)
- Test: `stig-compare/tests/test_extract_company.py`

**Interfaces:**
- Consumes: `common.row_id`, `common.fold_ws`, Task 3's `_map_headers` and `_rows_from_xlsx_sheet`, fixtures.
- Produces:
  - `extract_company(path) -> {"records": list[dict], "warnings": list[dict]}`. Each record:
    `{"row_id", "context_grouping", "stig_description", "stig_objective_or_requirement", "stig_command_or_value", "company_approved_setting_or_expected_value", "observed_value_or_evidence", "source_reference": {"table_index", "row_index", "sheet_or_section"}, "original_company_text", "status", "notes"}`.
    `status` ∈ `{"ok", "needs-structuring", "extraction-failed"}`.
    `original_company_text` = raw cell texts joined with `" | "`.
    `row_id` = `common.row_id(table_index, row_index, original_company_text)`.
  - `COMPANY_HEADER_SYNONYMS: dict[str, list[str]]` for the six canonical company fields.
  - Mapping decision rule: if ≥3 canonical fields map from a table's header row → deterministic assignment, `status="ok"`. Otherwise all non-empty rows get `status="needs-structuring"` (only `context_grouping` from the first cell, provenance, and raw text filled) and the table gets warning `{"code": "unmapped-headers", "detail": "table=<i>"}`. Fully empty rows → `status="extraction-failed"`, `notes="empty-row"`.
  - CLI subcommand `company` (already wired in Task 3's `main`).

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_extract_company.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_extract_company.py -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Implement `extract_company` in `extract.py`**

Add `import docx` to the imports, then replace the stub:

```python
COMPANY_HEADER_SYNONYMS = {
    "context_grouping": ["group", "grouping", "category", "severity group"],
    "stig_description": ["description", "details", "notes"],
    "stig_objective_or_requirement": ["stig requirement", "requirement",
                                      "objective", "control", "policy"],
    "stig_command_or_value": ["command to verify", "how to check",
                              "check command", "command", "verification",
                              "validation method"],
    "company_approved_setting_or_expected_value": ["approved setting",
                                                   "expected value", "baseline",
                                                   "approved value", "setting"],
    "observed_value_or_evidence": ["observed value", "evidence", "actual value",
                                   "result", "observed"],
}

_COMPANY_FIELDS = list(COMPANY_HEADER_SYNONYMS)


def _company_tables(path):
    """Yield (table_index, sheet_or_section, header_row, data_rows)."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        d = docx.Document(str(path))
        for ti, table in enumerate(d.tables, start=1):
            rows = [[c.text for c in row.cells] for row in table.rows]
            if rows:
                yield ti, "document-body", rows[0], rows[1:]
    elif path.suffix.lower() == ".xlsx":
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        for ti, ws in enumerate(wb.worksheets, start=1):
            rows = _rows_from_xlsx_sheet(ws)
            if rows:
                yield ti, f"sheet={ws.title}", rows[0], rows[1:]
    else:
        raise ValueError(f"unsupported company file type: {path.suffix}")


def extract_company(path):
    records, warnings = [], []
    any_table = False
    for ti, section, headers, data_rows in _company_tables(path):
        any_table = True
        mapping = _map_headers(headers, COMPANY_HEADER_SYNONYMS)
        mapped_fields = {v for v in mapping.values() if v}
        mappable = len(mapped_fields) >= 3
        if not mappable:
            warnings.append({"code": "unmapped-headers", "detail": f"table={ti}"})
        for ri, row in enumerate(data_rows, start=1):
            original = " | ".join(str(c) for c in row)
            rec = {f: "" for f in _COMPANY_FIELDS}
            rec["row_id"] = common.row_id(ti, ri, original)
            rec["source_reference"] = {"table_index": ti, "row_index": ri,
                                       "sheet_or_section": section}
            rec["original_company_text"] = original
            rec["notes"] = ""
            if not any(common.fold_ws(str(c)) for c in row):
                rec["status"] = "extraction-failed"
                rec["notes"] = "empty-row"
            elif mappable:
                rec["status"] = "ok"
                for idx, val in enumerate(row):
                    canon = mapping.get(idx)
                    if canon:
                        rec[canon] = common.fold_ws(str(val))
            else:
                rec["status"] = "needs-structuring"
                rec["context_grouping"] = common.fold_ws(str(row[0])) if row else ""
            records.append(rec)
    if not any_table:
        warnings.append({"code": "no-tables-found", "detail": "0 tables"})
    return {"records": records, "warnings": warnings}
```

- [ ] **Step 4: Run all extraction tests**

Run: `python -m pytest stig-compare/tests/test_extract_company.py stig-compare/tests/test_extract_official.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/extract.py stig-compare/tests/test_extract_company.py
git commit -m "feat(stig-compare): company submission extraction (docx/xlsx) with stable row IDs"
```

---

### Task 5: Additive normalization

**Files:**
- Create: `stig-compare/scripts/normalize.py`
- Test: `stig-compare/tests/test_normalize.py`

**Interfaces:**
- Consumes: `common.fold_ws`.
- Produces:
  - `norm_text(s: str) -> str` — Unicode NFC, fold whitespace, lowercase. For comparison keys only, never display.
  - `norm_value(s: str) -> str` — `norm_text` plus: strip surrounding backticks/quotes, canonicalize numbers (`"09"`→`"9"`, `"9.0"`→`"9"`), keep everything else verbatim.
  - `add_normalized(records: list[dict], fields: list[str]) -> list[dict]` — returns the same records with a `"normalized"` sub-dict added: `{field: norm_value(record[field])}` for each requested field. **Never mutates the original fields** (spec §4.4: normalization is additive).
  - Field lists used by callers (Task 11): company records normalize the five structure fields + `observed_value_or_evidence`; official records normalize `title`, `check_text`, `fix_text`, `expected_value`.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_normalize.py`:

```python
import normalize


def test_norm_text_folds_case_space_unicode():
    assert normalize.norm_text("  Ена́бled  VALUE ") == \
           normalize.norm_text("Ена́bled value")


def test_norm_value_numbers_and_quotes():
    assert normalize.norm_value("`09`") == "9"
    assert normalize.norm_value('"9.0"') == "9"
    assert normalize.norm_value("9 or more") == "9 or more"


def test_add_normalized_is_additive_not_destructive():
    rec = {"a": "  RAW Value ", "b": "keep"}
    out = normalize.add_normalized([rec], ["a"])
    assert out[0]["a"] == "  RAW Value "          # raw untouched
    assert out[0]["normalized"]["a"] == "raw value"
    assert "b" not in out[0]["normalized"]


def test_meaning_preserved_distinct_values_stay_distinct():
    # normalization must never merge meaningfully different values (spec §4.4)
    pairs = [("9 or more", "9"), ("enabled", "disabled"),
             ("60 days", "90 days"), ("15 minutes", "15 hours")]
    for a, b in pairs:
        assert normalize.norm_value(a) != normalize.norm_value(b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'normalize'`

- [ ] **Step 3: Implement `normalize.py`**

```python
"""Additive normalization. Raw values are never mutated (spec section 4.4)."""
import re
import unicodedata

import common

_NUM = re.compile(r"^\d+(\.\d+)?$")
_WRAP = "`'\""


def norm_text(s):
    s = unicodedata.normalize("NFC", s or "")
    return common.fold_ws(s).lower()


def norm_value(s):
    s = norm_text(s).strip(_WRAP).strip()
    if _NUM.match(s):
        f = float(s)
        s = str(int(f)) if f == int(f) else str(f)
    return s


def add_normalized(records, fields):
    for rec in records:
        rec["normalized"] = {f: norm_value(rec.get(f, "")) for f in fields}
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_normalize.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/normalize.py stig-compare/tests/test_normalize.py
git commit -m "feat(stig-compare): additive meaning-preserving normalization"
```

---

### Task 6: Deterministic value comparison and verdicts

**Files:**
- Create: `stig-compare/scripts/compare_values.py`
- Test: `stig-compare/tests/test_compare_values.py`

**Interfaces:**
- Consumes: `normalize.norm_value`.
- Produces:
  - `parse_value(text: str) -> dict|None`. Kinds:
    - `{"kind": "number", "value": float}` — `"9"`, `"9.0"`
    - `{"kind": "range", "op": ">="|"<="|"=", "value": float, "unit": str|None}` — `"9 or more"`→`>=9`, `"60 days or less"`→`<=60,unit=days`, `"at least 14"`→`>=14`, `"no greater than 60 days"`→`<=60,days`, `"15 minutes"`→`=15,minutes`, `"≥ 9"`→`>=9`
    - `{"kind": "boolean", "value": True|False}` — `"enabled"/"true"/"yes"/"on"` → True; `"disabled"/"false"/"no"/"off"` → False
    - `None` when unparseable (free text) — callers then go to the semantic path.
  - `satisfies(observed: dict, expected: dict) -> bool|None` — whether observed value satisfies expected constraint; `None` when kinds are incompatible or units differ.
  - `classify_difference(raw_a, raw_b) -> str` — `"identical"` (exact string equal), `"formatting-only"` (equal after `fold_ws` only), `"normalized-equivalent"` (equal after `norm_value`), `"different"`.
  - `deterministic_verdict(company_row: dict, official_rule: dict) -> dict|None`:
    - **Hard rule first (spec §4.7):** if `fold_ws(company_row["observed_value_or_evidence"]) == ""` → return `{"verdict": "Cannot Assess", "basis": "missing-evidence", "deterministic": True, "observation": {...}}`. Always returned, never `None`, regardless of anything else.
    - Else parse observed vs `official_rule["expected_value"]`: both parse and comparable → `{"verdict": "Compliant"|"Non-Compliant", "basis": "value-comparison", "deterministic": True, "observation": {"observed": raw, "expected": raw, "relation": str}}`.
    - Else → `None` (semantic path decides; Task 11 wires this).
    - Every returned dict also includes `"approved_alignment"`: `"aligned"|"misaligned"|"not-comparable"` comparing `company_approved_setting_or_expected_value` against the official expected value with the same machinery (an *observation*, not a verdict).

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_compare_values.py`:

```python
import compare_values as cv


def test_parse_number_and_range():
    assert cv.parse_value("9") == {"kind": "number", "value": 9.0}
    assert cv.parse_value("9 or more") == {"kind": "range", "op": ">=",
                                           "value": 9.0, "unit": None}
    assert cv.parse_value("60 days or less") == {"kind": "range", "op": "<=",
                                                 "value": 60.0, "unit": "days"}
    assert cv.parse_value("at least 14") == {"kind": "range", "op": ">=",
                                             "value": 14.0, "unit": None}
    assert cv.parse_value("15 minutes") == {"kind": "range", "op": "=",
                                            "value": 15.0, "unit": "minutes"}
    assert cv.parse_value("≥ 9")["op"] == ">="


def test_parse_boolean_and_unparseable():
    assert cv.parse_value("Enabled") == {"kind": "boolean", "value": True}
    assert cv.parse_value("off") == {"kind": "boolean", "value": False}
    assert cv.parse_value("logo.png") is None
    assert cv.parse_value("") is None


def test_satisfies():
    nine = cv.parse_value("9")
    assert cv.satisfies(nine, cv.parse_value("9 or more")) is True
    assert cv.satisfies(cv.parse_value("8"), cv.parse_value("9 or more")) is False
    assert cv.satisfies(cv.parse_value("59"), cv.parse_value("60 days or less")) is True
    assert cv.satisfies(cv.parse_value("enabled"), cv.parse_value("enabled")) is True
    # incompatible kinds / units -> None, not a guess
    assert cv.satisfies(cv.parse_value("enabled"), cv.parse_value("9 or more")) is None
    assert cv.satisfies(cv.parse_value("15 minutes"),
                        cv.parse_value("60 days or less")) is None


def test_classify_difference():
    assert cv.classify_difference("abc", "abc") == "identical"
    assert cv.classify_difference("a  b", "a b") == "formatting-only"
    assert cv.classify_difference("`09`", "9") == "normalized-equivalent"
    assert cv.classify_difference("9", "12") == "different"


def _row(observed, approved="9 or more"):
    return {"observed_value_or_evidence": observed,
            "company_approved_setting_or_expected_value": approved}


_RULE = {"expected_value": "9 or more"}


def test_missing_evidence_is_always_cannot_assess():
    v = cv.deterministic_verdict(_row(""), _RULE)
    assert v["verdict"] == "Cannot Assess"
    assert v["basis"] == "missing-evidence"
    assert v["deterministic"] is True


def test_compliant_and_noncompliant():
    assert cv.deterministic_verdict(_row("9"), _RULE)["verdict"] == "Compliant"
    v = cv.deterministic_verdict(_row("8"), _RULE)
    assert v["verdict"] == "Non-Compliant"
    assert v["approved_alignment"] == "aligned"     # approved '9 or more' == expected


def test_unparseable_returns_none_for_semantic_path():
    row = _row("evidence attached as screenshot")
    assert cv.deterministic_verdict(row, _RULE) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_compare_values.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'compare_values'`

- [ ] **Step 3: Implement `compare_values.py`**

```python
"""Deterministic value parsing, comparison, and verdicts (spec sections 4.7, 4.4)."""
import re

import common
import normalize

_TRUE = {"enabled", "true", "yes", "on"}
_FALSE = {"disabled", "false", "no", "off"}
_UNITS = r"(?P<unit>days?|hours?|minutes?|seconds?|characters?)?"
_NUM = r"(?P<num>\d+(?:\.\d+)?)"

_RANGE_PATTERNS = [
    (">=", re.compile(rf"^(?:>=|≥|at least)\s*{_NUM}\s*{_UNITS}$")),
    (">=", re.compile(rf"^{_NUM}\s*{_UNITS}\s*or (?:more|greater|higher)$")),
    ("<=", re.compile(rf"^(?:<=|≤|at most|no (?:greater|more) than)\s*{_NUM}\s*{_UNITS}$")),
    ("<=", re.compile(rf"^{_NUM}\s*{_UNITS}\s*or (?:less|fewer|lower)$")),
    ("=",  re.compile(rf"^{_NUM}\s*{_UNITS}$")),
]


def parse_value(text):
    s = normalize.norm_value(text)
    if not s:
        return None
    if s in _TRUE:
        return {"kind": "boolean", "value": True}
    if s in _FALSE:
        return {"kind": "boolean", "value": False}
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return {"kind": "number", "value": float(s)}
    for op, pat in _RANGE_PATTERNS:
        m = pat.match(s)
        if m:
            unit = m.group("unit")
            if unit:
                unit = unit.rstrip("s") + ("s" if unit.rstrip("s") != unit else "")
                unit = m.group("unit")          # keep as written, singularized:
                unit = unit[:-1] if unit.endswith("s") else unit
                unit += "s"
            return {"kind": "range", "op": op, "value": float(m.group("num")),
                    "unit": unit}
    return None


def _obs_number(parsed):
    if parsed["kind"] == "number":
        return parsed["value"], None
    if parsed["kind"] == "range" and parsed["op"] == "=":
        return parsed["value"], parsed["unit"]
    return None, None


def satisfies(observed, expected):
    if observed is None or expected is None:
        return None
    if observed["kind"] == "boolean" and expected["kind"] == "boolean":
        return observed["value"] == expected["value"]
    if expected["kind"] in ("number", "range"):
        val, unit = _obs_number(observed)
        if val is None:
            return None
        e_unit = expected.get("unit")
        if unit and e_unit and unit != e_unit:
            return None                      # unit mismatch -> undecidable
        if expected["kind"] == "number":
            return val == expected["value"]
        op = expected["op"]
        return {"<=": val <= expected["value"],
                ">=": val >= expected["value"],
                "=": val == expected["value"]}[op]
    return None


def classify_difference(raw_a, raw_b):
    if raw_a == raw_b:
        return "identical"
    if common.fold_ws(raw_a) == common.fold_ws(raw_b):
        return "formatting-only"
    if normalize.norm_value(raw_a) == normalize.norm_value(raw_b):
        return "normalized-equivalent"
    return "different"


def _alignment(approved_text, expected_text):
    a, e = parse_value(approved_text), parse_value(expected_text)
    if normalize.norm_value(approved_text) == normalize.norm_value(expected_text):
        return "aligned"
    if a is None or e is None:
        return "not-comparable"
    sat = satisfies(a, e)
    if sat is None:
        return "not-comparable"
    return "aligned" if sat else "misaligned"


def deterministic_verdict(company_row, official_rule):
    observed_raw = company_row.get("observed_value_or_evidence", "")
    expected_raw = official_rule.get("expected_value", "")
    approved_raw = company_row.get("company_approved_setting_or_expected_value", "")
    alignment = _alignment(approved_raw, expected_raw)

    if not common.fold_ws(observed_raw):
        return {"verdict": "Cannot Assess", "basis": "missing-evidence",
                "deterministic": True, "approved_alignment": alignment,
                "observation": {"observed": observed_raw,
                                "expected": expected_raw}}

    sat = satisfies(parse_value(observed_raw), parse_value(expected_raw))
    if sat is None:
        return None                          # semantic path decides
    return {"verdict": "Compliant" if sat else "Non-Compliant",
            "basis": "value-comparison", "deterministic": True,
            "approved_alignment": alignment,
            "observation": {"observed": observed_raw, "expected": expected_raw,
                            "relation": "satisfies" if sat else "violates"}}
```

Note for the implementer: the unit-handling lines inside `parse_value` shown above
are deliberately simplified in this plan — implement it as: singularize the captured
unit then append `"s"` (so `day`/`days` both → `"days"`). Delete the duplicate
assignment lines; keep one clear implementation and make the unit test in Step 1
pass exactly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_compare_values.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/compare_values.py stig-compare/tests/test_compare_values.py
git commit -m "feat(stig-compare): deterministic value parsing, verdicts, Cannot-Assess hard rule"
```

---

### Task 7: Candidate generation and deterministic match tiers

**Files:**
- Create: `stig-compare/scripts/candidates.py`
- Test: `stig-compare/tests/test_candidates.py`

**Interfaces:**
- Consumes: `normalize.norm_text`, company/official record shapes from Tasks 3–4.
- Produces:
  - `technical_tokens(text: str) -> set[str]` — lowercase tokens that look technical: snake_case (`password_reuse_max`), dotted names (`audit.log.enabled`), registry/file paths, ALL_CAPS parameters (`PASSWORD_LIFE_TIME`). Plain words never qualify.
  - `score_row(company_row, official_rule, idf: dict[str, float]) -> dict` — `{"score": float, "features": {"token_overlap": float, "technical": float, "value_overlap": float, "severity_tiebreak": float}}`. Weights: technical 3.0, token_overlap 1.0, value_overlap 0.3, severity_tiebreak 0.05. Severity contributes at most 0.05 — it can break ties but never create a candidate (Global Constraints).
  - `build_idf(official_rules) -> dict[str, float]` — `log(N / df)` over `norm_text` word tokens of title+check+fix.
  - `generate(company_rows, official_rules, k=5, floor=0.05, margin=0.15) -> list[dict]` — one result per company row with `status in ("ok", "needs-structuring")`:
    `{"row_id", "tier": "T0"|"T1"|None, "matched_rule_id": str|None, "margin_flag": bool, "candidates": [{"rule_id", "score", "features"}]}` (candidates sorted desc, ≤k, all ≥ floor).
    - **T0:** regex `\b(?:SV|V)-\d+\b` in `original_company_text` equals an official `rule_id` (case-insensitive) → `tier="T0"`, `matched_rule_id` set, candidates still included for the report.
    - **T1:** some technical token from the row appears in **exactly one** rule's check+fix text → that rule; `tier="T1"`.
    - Else `tier=None` (Claude adjudicates in T2; Task 11 wires it). `margin_flag=True` when ≥2 candidates and `(c0.score - c1.score) / c0.score < margin`.
    - Empty candidate list + no T0/T1 → row is T4 unmatched downstream.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_candidates.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_candidates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'candidates'`

- [ ] **Step 3: Implement `candidates.py`**

```python
"""Lexical candidate generation and deterministic match tiers T0/T1.

Explainable features only; severity can only break ties (spec section 4.5-4.6).
"""
import math
import re

import normalize

_ID = re.compile(r"\b(SV|V)-\d+\b", re.IGNORECASE)
_TECH = re.compile(
    r"[A-Za-z0-9_.\\/-]*(?:_[A-Za-z0-9]+|\.[A-Za-z]+\.[A-Za-z.]+|\\[A-Za-z])"
    r"[A-Za-z0-9_.\\/-]*")
_WORD = re.compile(r"[a-z0-9_]+")

_WEIGHTS = {"technical": 3.0, "token_overlap": 1.0,
            "value_overlap": 0.3, "severity_tiebreak": 0.05}

_ROW_TEXT_FIELDS = ["stig_description", "stig_objective_or_requirement",
                    "stig_command_or_value"]


def technical_tokens(text):
    out = set()
    for m in _TECH.finditer(text or ""):
        tok = m.group(0).strip(".-/\\").lower()
        if len(tok) >= 4 and ("_" in tok or "." in tok or "\\" in tok or "/" in tok):
            out.add(tok)
    for m in re.finditer(r"\b[A-Z][A-Z0-9_]{3,}\b", text or ""):
        out.add(m.group(0).lower())
    return out


def _words(text):
    return set(_WORD.findall(normalize.norm_text(text)))


def build_idf(official_rules):
    docs = [_words(" ".join([r["title"], r["check_text"], r["fix_text"]]))
            for r in official_rules]
    n = max(len(docs), 1)
    idf = {}
    for d in docs:
        for w in d:
            idf[w] = idf.get(w, 0) + 1
    return {w: math.log(n / df) for w, df in idf.items()}


def _rule_text(rule):
    return " ".join([rule["title"], rule["check_text"], rule["fix_text"]])


def score_row(company_row, official_rule, idf):
    row_text = " ".join(company_row.get(f, "") for f in _ROW_TEXT_FIELDS) or \
               company_row["original_company_text"]
    rule_text = _rule_text(official_rule)

    row_words, rule_words = _words(row_text), _words(rule_text)
    shared = row_words & rule_words
    denom = sum(idf.get(w, 0.0) for w in row_words) or 1.0
    token_overlap = sum(idf.get(w, 0.0) for w in shared) / denom

    row_tech = technical_tokens(company_row["original_company_text"])
    rule_tech = technical_tokens(rule_text)
    technical = 1.0 if row_tech & rule_tech else 0.0

    approved = normalize.norm_value(
        company_row.get("company_approved_setting_or_expected_value", ""))
    expected = normalize.norm_value(official_rule.get("expected_value", ""))
    value_overlap = 1.0 if approved and expected and \
        (approved == expected or approved in expected or expected in approved) \
        else 0.0

    sev = normalize.norm_text(company_row.get("context_grouping", ""))
    severity_tiebreak = 1.0 if sev and sev == official_rule.get("severity") else 0.0

    features = {"token_overlap": round(token_overlap, 4),
                "technical": technical, "value_overlap": value_overlap,
                "severity_tiebreak": severity_tiebreak}
    score = sum(_WEIGHTS[k] * v for k, v in features.items())
    return {"score": round(score, 4), "features": features}


def generate(company_rows, official_rules, k=5, floor=0.05, margin=0.15):
    idf = build_idf(official_rules)
    by_id = {r["rule_id"]: r for r in official_rules}
    rule_tech = {r["rule_id"]: technical_tokens(_rule_text(r))
                 for r in official_rules}
    results = []
    for row in company_rows:
        if row.get("status") not in ("ok", "needs-structuring"):
            continue
        scored = sorted(
            ({"rule_id": r["rule_id"], **score_row(row, r, idf)}
             for r in official_rules),
            key=lambda c: c["score"], reverse=True)
        # severity alone must never clear the floor: drop candidates whose
        # score comes only from the severity feature
        shortlist = [c for c in scored
                     if c["score"] >= floor and
                     c["score"] > _WEIGHTS["severity_tiebreak"] *
                     c["features"]["severity_tiebreak"] + 1e-9][:k]

        result = {"row_id": row["row_id"], "tier": None,
                  "matched_rule_id": None, "margin_flag": False,
                  "candidates": shortlist}

        m = _ID.search(row["original_company_text"] or "")
        if m and m.group(0).upper() in by_id:
            result["tier"] = "T0"
            result["matched_rule_id"] = m.group(0).upper()
        else:
            row_tech = technical_tokens(row["original_company_text"])
            if row_tech:
                hits = [rid for rid, toks in rule_tech.items() if row_tech & toks]
                if len(hits) == 1:
                    result["tier"] = "T1"
                    result["matched_rule_id"] = hits[0]

        if result["tier"] is None and len(shortlist) >= 2 and shortlist[0]["score"] > 0:
            rel = (shortlist[0]["score"] - shortlist[1]["score"]) / shortlist[0]["score"]
            result["margin_flag"] = rel < margin
        results.append(result)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_candidates.py -v`
Expected: 6 passed. If `test_shortlist_recall_for_paraphrased_row` fails, tune
`floor` down or check `_words`/IDF math — recall failures here become false
"unmatched" results downstream, the exact risk spec §17 names.

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/candidates.py stig-compare/tests/test_candidates.py
git commit -m "feat(stig-compare): explainable candidate generation with T0/T1 deterministic tiers"
```

---

### Task 8: Validation of Claude outputs and findings

**Files:**
- Create: `stig-compare/scripts/validate.py`
- Test: `stig-compare/tests/test_validate.py`

**Interfaces:**
- Consumes: `common.fold_ws`, `common.finding_id`.
- Produces (all return `list[str]` of error codes — empty list = valid):
  - `quote_exists(quote: str, source_text: str) -> bool` — substring check after `fold_ws` on both sides.
  - `validate_match_output(output: dict, shortlist_ids: list[str], row: dict, rules_by_id: dict) -> list[str]` — checks Claude's T2 adjudication JSON:
    - required keys: `decision` (`"match"|"none"|"ambiguous"`), `rule_id` (str|None), `ambiguous_rule_ids` (list), `row_quote` (str), `rule_quote` (str), `basis` (str)
    - `decision=="match"` → `rule_id` must be in `shortlist_ids` (**never** outside it), `row_quote` must exist in `row["original_company_text"]`, `rule_quote` must exist in the matched rule's `title+check_text+fix_text`
    - `decision=="ambiguous"` → `ambiguous_rule_ids` ⊆ shortlist, length ≥ 2
    - error codes: `"missing-key:<k>"`, `"bad-decision"`, `"rule-not-in-shortlist"`, `"row-quote-not-found"`, `"rule-quote-not-found"`, `"ambiguous-needs-two"`
  - `validate_semantic_output(output: dict, row: dict, rule: dict) -> list[str]` — checks semantic-comparison JSON: required keys `finding_type` (one of `equivalent|stronger|weaker|changed-scope|contradictory|cannot-determine`), `verdict` (`Compliant|Non-Compliant|Cannot Assess`), `row_quote`, `rule_quote`, `interpretation` (str); quotes verified against row raw text / rule text; codes `"bad-finding-type"`, `"bad-verdict"`, plus the quote/missing-key codes above.
  - `dedup_findings(findings: list[dict]) -> tuple[list[dict], list[str]]` — collapse duplicates by `(row_id, rule_id, finding_type)`, second return = dropped finding IDs.
  - `find_contradictions(findings: list[dict]) -> list[dict]` — pairs with same `(row_id, rule_id)` but conflicting `verdict`s; each `{"finding_ids": [a, b], "code": "contradictory-verdicts"}`.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_validate.py`:

```python
import validate

_ROW = {"row_id": "R-aaaa0001",
        "original_company_text": "High | Password reuse must be restricted | 9"}
_RULE = {"rule_id": "V-1001", "title": "Password reuse must be restricted",
         "check_text": "Run SHOW PARAMETER password_reuse_max",
         "fix_text": "Set password_reuse_max to 9 or more."}
_RULES = {"V-1001": _RULE}


def _good_match():
    return {"decision": "match", "rule_id": "V-1001", "ambiguous_rule_ids": [],
            "row_quote": "Password reuse must be restricted",
            "rule_quote": "password_reuse_max", "basis": "same requirement"}


def test_quote_exists_whitespace_folded():
    assert validate.quote_exists("reuse  must   be", "reuse must be restricted")
    assert not validate.quote_exists("not present", "reuse must be restricted")


def test_valid_match_passes():
    assert validate.validate_match_output(_good_match(), ["V-1001"], _ROW, _RULES) == []


def test_rule_outside_shortlist_rejected():
    out = _good_match()
    out["rule_id"] = "V-9999"
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "rule-not-in-shortlist" in errs


def test_invented_quote_rejected():
    out = _good_match()
    out["row_quote"] = "text that was never in the row"
    errs = validate.validate_match_output(out, ["V-1001"], _ROW, _RULES)
    assert "row-quote-not-found" in errs


def test_ambiguous_needs_two():
    out = {"decision": "ambiguous", "rule_id": None,
           "ambiguous_rule_ids": ["V-1001"], "row_quote": "9",
           "rule_quote": "password_reuse_max", "basis": "unclear"}
    errs = validate.validate_match_output(out, ["V-1001", "V-1002"], _ROW, _RULES)
    assert "ambiguous-needs-two" in errs


def test_semantic_bad_type_and_missing_key():
    out = {"finding_type": "banana", "verdict": "Compliant",
           "row_quote": "9", "rule_quote": "password_reuse_max"}
    errs = validate.validate_semantic_output(out, _ROW, _RULE)
    assert "bad-finding-type" in errs
    assert "missing-key:interpretation" in errs


def test_dedup_and_contradictions():
    f1 = {"finding_id": "F-1", "row_id": "R-1", "rule_id": "V-1",
          "finding_type": "equivalent", "verdict": "Compliant"}
    f2 = dict(f1, finding_id="F-2")                       # duplicate
    f3 = dict(f1, finding_id="F-3", finding_type="stronger",
              verdict="Non-Compliant")                     # contradicts f1
    kept, dropped = validate.dedup_findings([f1, f2, f3])
    assert [f["finding_id"] for f in kept] == ["F-1", "F-3"]
    assert dropped == ["F-2"]
    contras = validate.find_contradictions(kept)
    assert contras == [{"finding_ids": ["F-1", "F-3"],
                        "code": "contradictory-verdicts"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'validate'`

- [ ] **Step 3: Implement `validate.py`**

```python
"""Deterministic validation. Claude output is untrusted input (spec section 5)."""
import common

FINDING_TYPES = {"equivalent", "stronger", "weaker", "changed-scope",
                 "contradictory", "cannot-determine"}
VERDICTS = {"Compliant", "Non-Compliant", "Cannot Assess"}
_MATCH_KEYS = ["decision", "rule_id", "ambiguous_rule_ids",
               "row_quote", "rule_quote", "basis"]
_SEM_KEYS = ["finding_type", "verdict", "row_quote", "rule_quote",
             "interpretation"]


def quote_exists(quote, source_text):
    return common.fold_ws(quote) in common.fold_ws(source_text)


def _rule_text(rule):
    return " ".join([rule.get("title", ""), rule.get("check_text", ""),
                     rule.get("fix_text", "")])


def _require(output, keys):
    return [f"missing-key:{k}" for k in keys if k not in output]


def validate_match_output(output, shortlist_ids, row, rules_by_id):
    errs = _require(output, _MATCH_KEYS)
    if errs:
        return errs
    decision = output["decision"]
    if decision not in ("match", "none", "ambiguous"):
        return ["bad-decision"]
    if decision == "match":
        rid = output["rule_id"]
        if rid not in shortlist_ids:
            errs.append("rule-not-in-shortlist")
        if not quote_exists(output["row_quote"], row["original_company_text"]):
            errs.append("row-quote-not-found")
        if rid in rules_by_id and not quote_exists(
                output["rule_quote"], _rule_text(rules_by_id[rid])):
            errs.append("rule-quote-not-found")
    elif decision == "ambiguous":
        ids = output["ambiguous_rule_ids"]
        if len(ids) < 2 or not set(ids) <= set(shortlist_ids):
            errs.append("ambiguous-needs-two")
    return errs


def validate_semantic_output(output, row, rule):
    errs = _require(output, _SEM_KEYS)
    if output.get("finding_type") not in FINDING_TYPES:
        errs.append("bad-finding-type")
    if output.get("verdict") not in VERDICTS:
        errs.append("bad-verdict")
    if "row_quote" in output and not quote_exists(
            output["row_quote"], row["original_company_text"]):
        errs.append("row-quote-not-found")
    if "rule_quote" in output and not quote_exists(
            output["rule_quote"], _rule_text(rule)):
        errs.append("rule-quote-not-found")
    return errs


def dedup_findings(findings):
    seen, kept, dropped = set(), [], []
    for f in findings:
        key = (f["row_id"], f["rule_id"], f["finding_type"])
        if key in seen:
            dropped.append(f["finding_id"])
        else:
            seen.add(key)
            kept.append(f)
    return kept, dropped


def find_contradictions(findings):
    by_pair = {}
    for f in findings:
        by_pair.setdefault((f["row_id"], f["rule_id"]), []).append(f)
    out = []
    for pair, fs in by_pair.items():
        verdicts = {f.get("verdict") for f in fs}
        if len(fs) > 1 and len(verdicts) > 1:
            out.append({"finding_ids": [f["finding_id"] for f in fs],
                        "code": "contradictory-verdicts"})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_validate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/validate.py stig-compare/tests/test_validate.py
git commit -m "feat(stig-compare): deterministic validation of Claude outputs, dedup, contradictions"
```

---

### Task 9: Rule registry — scoping, precedence, conflicts

**Files:**
- Create: `stig-compare/scripts/rules.py`
- Create: `stig-compare/rules/registry.json`
- Create: `stig-compare/rules/candidates/.gitkeep`
- Test: `stig-compare/tests/test_rules.py`

**Interfaces:**
- Consumes: nothing beyond stdlib.
- Produces:
  - Seed `stig-compare/rules/registry.json`:
    ```json
    {"registry_version": 1, "rules": []}
    ```
  - Rule record shape (used by Tasks 11, 13, 14):
    `{"rule_id": "RL-<8hex>", "version": 1, "category": str, "scope": {"level": "global"|"document-type"|"sheet-or-section"|"field", "value": str|None}, "status": "candidate"|"active"|"rejected", "payload": dict, "provenance": {"feedback_ids": [...], "approved_by": str|None, "created": str, "approved": str|None}}`
    Categories: `equivalent-terminology` (payload `{"a": str, "b": str}`), `normalization-exception`, `matching-key`, `ignore-field` (payload `{"field": str}`), `exact-compare-field`, `severity-override`, `semantic-equivalence`.
  - `load_registry(path) -> dict` — parses, raises `ValueError` on duplicate rule IDs or unknown category/scope level (message contains IDs only, no payloads).
  - `applicable_rules(registry: dict, context: dict) -> tuple[list[dict], list[dict]]` — `context` = `{"document_type": str, "sheet_or_section": str, "field": str}`. Returns `(applied, conflicts)`:
    - Only `status=="active"` rules whose scope matches the context (global always matches; `field` scope matches when `scope.value == context["field"]`, etc.).
    - Precedence: narrowest scope wins (`field` > `sheet-or-section` > `document-type` > `global`). Two matching rules of the **same category and same scope level** with different payloads = conflict: **both** excluded from `applied`, one entry in `conflicts`: `{"code": "rule-conflict", "rule_ids": [a, b], "scope_level": str}` (spec §10: no silent resolution).
  - `equivalent_by_rule(applied: list[dict], a: str, b: str) -> str|None` — returns the rule_id of an `equivalent-terminology` rule whose payload pair matches `{a,b}` case-insensitively in either order, else `None`. (Task 11 uses this so findings can record which rule affected them.)

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_rules.py`:

```python
import pytest

import rules


def _rule(rid, level, value, category="equivalent-terminology",
          payload=None, status="active"):
    return {"rule_id": rid, "version": 1, "category": category,
            "scope": {"level": level, "value": value}, "status": status,
            "payload": payload or {"a": "enabled", "b": "turned on"},
            "provenance": {"feedback_ids": [], "approved_by": "t",
                           "created": "2026-08-10", "approved": "2026-08-10"}}


_CTX = {"document_type": "docx", "sheet_or_section": "document-body",
        "field": "observed_value_or_evidence"}


def test_load_registry_rejects_duplicate_ids(tmp_path):
    import json
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"registry_version": 1, "rules": [
        _rule("RL-00000001", "global", None),
        _rule("RL-00000001", "global", None)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        rules.load_registry(p)


def test_scope_matching_and_candidate_excluded():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-1", "global", None),
        _rule("RL-2", "field", "some_other_field"),
        _rule("RL-3", "global", None, status="candidate")]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    assert [r["rule_id"] for r in applied] == ["RL-1"]
    assert conflicts == []


def test_narrower_scope_wins():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-g", "global", None, payload={"a": "enabled", "b": "on"}),
        _rule("RL-f", "field", "observed_value_or_evidence",
              payload={"a": "enabled", "b": "active"})]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    # both apply (different payloads at different levels is not a conflict);
    # narrower first so callers can prefer it
    assert [r["rule_id"] for r in applied] == ["RL-f", "RL-g"]
    assert conflicts == []


def test_same_level_conflict_suspends_both():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-a", "global", None, payload={"a": "enabled", "b": "on"}),
        _rule("RL-b", "global", None, payload={"a": "enabled", "b": "off"})]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    assert applied == []
    assert conflicts[0]["code"] == "rule-conflict"
    assert set(conflicts[0]["rule_ids"]) == {"RL-a", "RL-b"}


def test_equivalent_by_rule():
    applied = [_rule("RL-1", "global", None)]
    assert rules.equivalent_by_rule(applied, "Turned On", "ENABLED") == "RL-1"
    assert rules.equivalent_by_rule(applied, "enabled", "disabled") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rules'`

- [ ] **Step 3: Implement `rules.py` and seed files**

```python
"""Rule registry: load, scope matching, precedence, conflicts (spec section 10)."""
import json
from pathlib import Path

CATEGORIES = {"equivalent-terminology", "normalization-exception",
              "matching-key", "ignore-field", "exact-compare-field",
              "severity-override", "semantic-equivalence"}
_LEVELS = ["field", "sheet-or-section", "document-type", "global"]  # narrow->wide


def load_registry(path):
    reg = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for r in reg.get("rules", []):
        rid = r.get("rule_id")
        if rid in seen:
            raise ValueError(f"duplicate rule id: {rid}")
        seen.add(rid)
        if r.get("category") not in CATEGORIES:
            raise ValueError(f"unknown category on rule: {rid}")
        if r.get("scope", {}).get("level") not in _LEVELS:
            raise ValueError(f"unknown scope level on rule: {rid}")
    return reg


def _matches(rule, context):
    level = rule["scope"]["level"]
    if level == "global":
        return True
    value = rule["scope"]["value"]
    key = {"field": "field", "sheet-or-section": "sheet_or_section",
           "document-type": "document_type"}[level]
    return value == context.get(key)


def applicable_rules(registry, context):
    matching = [r for r in registry.get("rules", [])
                if r.get("status") == "active" and _matches(r, context)]
    matching.sort(key=lambda r: _LEVELS.index(r["scope"]["level"]))

    conflicts, suspended = [], set()
    by_bucket = {}
    for r in matching:
        by_bucket.setdefault((r["category"], r["scope"]["level"]), []).append(r)
    for (cat, level), rs in by_bucket.items():
        payloads = [json.dumps(r["payload"], sort_keys=True) for r in rs]
        if len(rs) > 1 and len(set(payloads)) > 1:
            ids = [r["rule_id"] for r in rs]
            conflicts.append({"code": "rule-conflict", "rule_ids": ids,
                              "scope_level": level})
            suspended.update(ids)
    applied = [r for r in matching if r["rule_id"] not in suspended]
    return applied, conflicts


def equivalent_by_rule(applied, a, b):
    pair = {a.strip().lower(), b.strip().lower()}
    for r in applied:
        if r["category"] == "equivalent-terminology":
            p = r["payload"]
            if {p["a"].strip().lower(), p["b"].strip().lower()} == pair:
                return r["rule_id"]
    return None
```

`stig-compare/rules/registry.json`:

```json
{"registry_version": 1, "rules": []}
```

Create empty `stig-compare/rules/candidates/.gitkeep`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_rules.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/rules.py stig-compare/rules stig-compare/tests/test_rules.py
git commit -m "feat(stig-compare): rule registry with scope precedence and conflict suspension"
```

---

### Task 10: Coverage arithmetic

**Files:**
- Create: `stig-compare/scripts/coverage.py`
- Test: `stig-compare/tests/test_coverage.py`

**Interfaces:**
- Consumes: record shapes from Tasks 4, 7.
- Produces:
  - `compute(company_rows, official_rules, match_results, ignored_row_ids: set[str]) -> dict`:
    - `match_results` is the final per-row match state (Task 11 shape): `{"row_id", "tier": "T0"|"T1"|"T2"|"T3"|"T4", "matched_rule_id": str|None, "ambiguous_rule_ids": list}`.
    - Returns:
      ```
      {"company": {"total", "matched", "ambiguous", "unmatched",
                   "ignored_by_rule", "extraction_failed", "needs_structuring_unresolved"},
       "official": {"total", "addressed", "unaddressed",
                    "duplicate_coverage_rule_ids": [...]},
       "warnings": [{"code", "detail"}],
       "ok": bool}
      ```
    - Bucket rules: every company row lands in exactly one bucket — `extraction-failed` status → `extraction_failed`; `row_id` in `ignored_row_ids` → `ignored_by_rule`; tier T0/T1/T2 → `matched`; T3 → `ambiguous`; T4 (or no match result) → `unmatched`; rows still `needs-structuring` with no match result → `needs_structuring_unresolved` (counts as a failure state).
    - **Sum check:** buckets must sum to `total` or `ok=False` with warning `{"code": "coverage-sum-mismatch"}` — the run then fails loudly (Task 11 aborts on `ok=False`).
    - Warning `{"code": "extraction-failures"}` when `extraction_failed > 0`; `{"code": "low-coverage-red-banner"}` when `(extraction_failed + ignored_by_rule + needs_structuring_unresolved) / total > 0.10`.
    - Official side: `addressed` = rules matched by ≥1 row (T0/T1/T2); rules matched by ≥2 rows listed in `duplicate_coverage_rule_ids`.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_coverage.py`:

```python
import coverage


def _rows(n, status="ok"):
    return [{"row_id": f"R-{i:08d}", "status": status} for i in range(n)]


def _rules(n):
    return [{"rule_id": f"V-{1000+i}"} for i in range(n)]


def _match(rid, tier, rule=None):
    return {"row_id": rid, "tier": tier, "matched_rule_id": rule,
            "ambiguous_rule_ids": []}


def test_buckets_and_sum():
    rows = _rows(5)
    rows[4]["status"] = "extraction-failed"
    matches = [_match("R-00000000", "T1", "V-1000"),
               _match("R-00000001", "T2", "V-1001"),
               _match("R-00000002", "T3"),
               _match("R-00000003", "T4")]
    cov = coverage.compute(rows, _rules(3), matches, ignored_row_ids=set())
    c = cov["company"]
    assert (c["matched"], c["ambiguous"], c["unmatched"],
            c["extraction_failed"]) == (2, 1, 1, 1)
    assert cov["ok"] is True
    assert cov["official"]["addressed"] == 2
    assert cov["official"]["unaddressed"] == 1
    assert any(w["code"] == "extraction-failures" for w in cov["warnings"])


def test_duplicate_coverage_flagged():
    rows = _rows(2)
    matches = [_match("R-00000000", "T1", "V-1000"),
               _match("R-00000001", "T2", "V-1000")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert cov["official"]["duplicate_coverage_rule_ids"] == ["V-1000"]


def test_red_banner_over_ten_percent():
    rows = _rows(10)
    for r in rows[:2]:
        r["status"] = "extraction-failed"
    matches = [_match(r["row_id"], "T4") for r in rows[2:]]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert any(w["code"] == "low-coverage-red-banner" for w in cov["warnings"])


def test_unaccounted_row_fails_loudly():
    rows = _rows(3)          # one row has no match result and status ok
    matches = [_match("R-00000000", "T4"), _match("R-00000001", "T4")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    # missing rows are counted as unmatched, never silently dropped
    assert cov["company"]["unmatched"] == 3
    assert cov["ok"] is True


def test_needs_structuring_unresolved_counts():
    rows = _rows(2)
    rows[1]["status"] = "needs-structuring"
    matches = [_match("R-00000000", "T4")]
    cov = coverage.compute(rows, _rules(1), matches, set())
    assert cov["company"]["needs_structuring_unresolved"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_coverage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coverage'`.
(Note: the local module shadows the unrelated `coverage.py` PyPI package; that
package is not a dependency here so the shadow is harmless.)

- [ ] **Step 3: Implement `coverage.py`**

```python
"""Coverage accounting: pure arithmetic over item IDs (spec section 7)."""
from collections import Counter

RED_BANNER_THRESHOLD = 0.10


def compute(company_rows, official_rules, match_results, ignored_row_ids):
    by_row = {m["row_id"]: m for m in match_results}
    c = Counter()
    for row in company_rows:
        rid = row["row_id"]
        if row.get("status") == "extraction-failed":
            c["extraction_failed"] += 1
        elif rid in ignored_row_ids:
            c["ignored_by_rule"] += 1
        elif row.get("status") == "needs-structuring" and rid not in by_row:
            c["needs_structuring_unresolved"] += 1
        else:
            m = by_row.get(rid)
            tier = m["tier"] if m else "T4"
            if tier in ("T0", "T1", "T2"):
                c["matched"] += 1
            elif tier == "T3":
                c["ambiguous"] += 1
            else:
                c["unmatched"] += 1

    total = len(company_rows)
    company = {"total": total, "matched": c["matched"],
               "ambiguous": c["ambiguous"], "unmatched": c["unmatched"],
               "ignored_by_rule": c["ignored_by_rule"],
               "extraction_failed": c["extraction_failed"],
               "needs_structuring_unresolved": c["needs_structuring_unresolved"]}

    matched_rules = Counter(m["matched_rule_id"] for m in match_results
                            if m.get("matched_rule_id") and
                            m["tier"] in ("T0", "T1", "T2"))
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
    bad = (company["extraction_failed"] + company["ignored_by_rule"] +
           company["needs_structuring_unresolved"])
    if total and bad / total > RED_BANNER_THRESHOLD:
        warnings.append({"code": "low-coverage-red-banner",
                         "detail": f"{bad}/{total} rows not compared"})
    return {"company": company, "official": official,
            "warnings": warnings, "ok": ok}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_coverage.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/coverage.py stig-compare/tests/test_coverage.py
git commit -m "feat(stig-compare): coverage arithmetic with loud sum-mismatch failure"
```

---

### Task 11: Pipeline orchestration CLI

**Files:**
- Create: `stig-compare/scripts/pipeline.py`
- Test: `stig-compare/tests/test_pipeline.py`

**Interfaces:**
- Consumes: every module from Tasks 1–10.
- Produces a three-command CLI that SKILL.md drives. Claude passes happen *between* the commands — the agent reads `*_requests.jsonl` files, produces `*_responses.jsonl` files, and the next command validates and consumes them.
  - `python stig-compare/scripts/pipeline.py start --official <file> --company <file> --run-dir <dir>`
    Runs: extract both files → normalize → rules context → candidate generation. Writes into `<run-dir>`:
    - `manifest.json` — `{"official_file", "company_file", "official_sha256", "company_sha256", "started", "versions": {...}, "registry_version", "rule_conflicts": [...]}` (timestamp via `datetime.now().isoformat(timespec="seconds")`)
    - `official_rules.jsonl`, `company_rows.jsonl`, `extract_warnings.json`
    - `match_state.jsonl` — Task 7 `generate()` output, one record per comparable row
    - `structuring_requests.jsonl` — one per `needs-structuring` row: `{"row_id", "original_company_text", "context_grouping", "instructions_file": "prompts/structuring.md"}`
    - `matching_requests.jsonl` — one per row with `tier=None` and non-empty candidates: `{"row_id", "row": {...}, "candidates": [full rule records of the shortlist], "instructions_file": "prompts/matching.md"}`
    Prints a summary line: counts of T0/T1 matches, pending structuring, pending matching.
  - `python stig-compare/scripts/pipeline.py resolve --run-dir <dir>`
    Consumes `structuring_responses.jsonl` and `matching_responses.jsonl` (if present; both optional — absent means the agent had nothing to answer). For each response:
    - Structuring: validates every extracted field is a verbatim substring of the row's raw text (via `validate.quote_exists`); valid → row fields updated, `status="ok"`; invalid → row `status="extraction-failed"`, `notes="structuring-rejected:<codes>"`. Newly structured rows get candidates generated and appended to `matching_requests.jsonl` (second round).
    - Matching: `validate.validate_match_output` against the stored shortlist; valid `match` → `tier="T2"`, `matched_rule_id`, quotes stored; valid `none` → `tier="T4"`; valid `ambiguous` → `tier="T3"`, `ambiguous_rule_ids` stored; **invalid → the response is recorded in `validation_failures.jsonl` and the row stays pending** (one retry: the row reappears in `matching_requests.jsonl` with `"retry": true`; a second failure → `tier="T4"` with warning `"llm-output-rejected"`).
    Also: rows whose `margin_flag` is true and whose accepted match's `rule_quote` also appears verbatim in the runner-up candidate's text are downgraded to `tier="T3"` (quotes did not discriminate — spec §4.6). A response whose `row_id` has no pending request is recorded in `validation_failures.jsonl` with code `"no-such-request"` and never applied.
    Then runs deterministic verdicts (`compare_values.deterministic_verdict`) for all matched pairs. Before the verdict, if `rules.equivalent_by_rule(applied_rules_for_context, observed_raw, official_expected_raw)` returns a rule ID, the pair gets verdict `Compliant`, `basis="rule-equivalence"`, `deterministic=True`, and that rule ID in the finding's `applied_rules` list (spec §10: findings record the rules that influenced them). Deterministic findings go to `findings.jsonl`; pairs neither rule-resolved nor value-parseable go to `semantic_requests.jsonl`: `{"row_id", "rule_id", "row", "rule", "instructions_file": "prompts/semantic_compare.md"}`.
    Prints counts: resolved, retries pending, semantic pending.
  - `python stig-compare/scripts/pipeline.py finalize --run-dir <dir>`
    Consumes `semantic_responses.jsonl` (validated via `validate.validate_semantic_output`; invalid → same retry-then-reject protocol) and `skeptic_responses.jsonl` (each `{"finding_id", "outcome": "upheld"|"refuted"|"undetermined", "reason"}`). Then:
    - assembles final findings with `finding_id`, confidence class (High/Medium/Low per spec §6), `human_review_needed`, skeptic outcome (`"disputed"` findings keep both positions)
    - dedup + contradiction checks (`validate.dedup_findings`, `find_contradictions`)
    - coverage (`coverage.compute`) — **aborts with exit 3 if `cov["ok"] is False`**
    - writes `final.json`: `{"manifest", "findings", "match_state", "coverage", "warnings", "unmatched_rows", "unaddressed_rules", "ambiguous"}`
    - calls `report.render(run_dir)` (Task 12) to produce `report.html`; if Task 12 is not yet implemented, `finalize` accepts `--no-report`.
    - `ignored_row_ids` passed to coverage = rows whose `sheet_or_section` matches an active `ignore-field` rule scoped at `sheet-or-section` level; with the seed registry this set is always empty.
    If **any** request in `matching_requests.jsonl` or `semantic_requests.jsonl` has no accepted response, finalize **refuses to run** (exit 4, message lists pending counts per kind) unless `--allow-pending` is passed — then pending matching rows become `tier="T4"` with warning `"matching-pass-not-run"`, and pending semantic pairs become findings with `verdict="Cannot Assess"`, `basis="semantic-pass-not-run"`, `human_review_needed=true`. Unanswered work is never silently reclassified.
  - Confidence assignment function (exported for tests): `assign_confidence(match_record, finding, skeptic_outcome) -> str` implementing spec §6 exactly:
    - `"High"`: tier T0/T1 and finding deterministic; or tier T2 + deterministic finding + no validation failures recorded for the row
    - `"Medium"`: tier T2 + semantic finding + skeptic `"upheld"`
    - `"Low"`: everything else (margin_flag, skeptic `"undetermined"`/`"refuted"`, retries used, `needs-structuring` origin)
  - `human_review_needed` = true when: tier T3, skeptic ≠ `"upheld"` on a semantic finding, duplicate coverage on the matched rule, verdict `"Cannot Assess"` with non-empty `observed_value_or_evidence`, any `validation_failures` for the row, or any rule conflict touching the row's context.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_pipeline.py`:

```python
import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all
import common
import pipeline


@pytest.fixture()
def run(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    rc = pipeline.main(["start", "--official", str(fx["official_csv"]),
                        "--company", str(fx["company_docx"]),
                        "--run-dir", str(run_dir)])
    assert rc == 0
    return run_dir


def test_start_produces_artifacts_and_t1_match(run):
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["official_sha256"]) == 64
    assert "skill_version" in manifest["versions"]
    state = common.read_jsonl(run / "match_state.jsonl")
    by_tier = {}
    for m in state:
        by_tier.setdefault(m["tier"], []).append(m)
    assert len(by_tier.get("T1", [])) >= 1          # password_reuse_max row
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    assert all(r["candidates"] for r in requests)


def test_resolve_accepts_valid_match_and_rejects_invented_rule(run):
    requests = common.read_jsonl(run / "matching_requests.jsonl")
    req = requests[0]
    good = {"row_id": req["row_id"], "decision": "match",
            "rule_id": req["candidates"][0]["rule_id"],
            "ambiguous_rule_ids": [],
            "row_quote": req["row"]["original_company_text"][:20],
            "rule_quote": req["candidates"][0]["title"][:20],
            "basis": "same requirement"}
    bad_req = requests[1] if len(requests) > 1 else req
    bad = {"row_id": bad_req["row_id"], "decision": "match",
           "rule_id": "V-9999", "ambiguous_rule_ids": [],
           "row_quote": "x", "rule_quote": "y", "basis": "invented"}
    common.write_jsonl(run / "matching_responses.jsonl", [good, bad])
    rc = pipeline.main(["resolve", "--run-dir", str(run)])
    assert rc == 0
    state = {m["row_id"]: m for m in common.read_jsonl(run / "match_state.jsonl")}
    assert state[good["row_id"]]["tier"] == "T2"
    failures = common.read_jsonl(run / "validation_failures.jsonl")
    assert any(f["row_id"] == bad["row_id"] and
               "rule-not-in-shortlist" in f["errors"] for f in failures)
    retry = common.read_jsonl(run / "matching_requests.jsonl")
    assert any(r.get("retry") for r in retry if r["row_id"] == bad["row_id"])


def test_finalize_refuses_pending_requests(run):
    # no matching responses provided -> pending matching requests exist
    common.write_jsonl(run / "matching_responses.jsonl", [])
    pipeline.main(["resolve", "--run-dir", str(run)])
    rc = pipeline.main(["finalize", "--run-dir", str(run), "--no-report"])
    assert rc == 4


def test_finalize_allow_pending_yields_cannot_assess(run):
    common.write_jsonl(run / "matching_responses.jsonl", [])
    pipeline.main(["resolve", "--run-dir", str(run)])
    rc = pipeline.main(["finalize", "--run-dir", str(run),
                        "--no-report", "--allow-pending"])
    assert rc == 0
    final = json.loads((run / "final.json").read_text(encoding="utf-8"))
    assert final["coverage"]["ok"] is True
    for f in final["findings"]:
        if f.get("basis") == "semantic-pass-not-run":
            assert f["verdict"] == "Cannot Assess"
            assert f["human_review_needed"] is True


def test_assign_confidence():
    t1 = {"tier": "T1", "margin_flag": False}
    det = {"deterministic": True}
    sem = {"deterministic": False}
    assert pipeline.assign_confidence(t1, det, None) == "High"
    t2 = {"tier": "T2", "margin_flag": False}
    assert pipeline.assign_confidence(t2, det, None) == "High"
    assert pipeline.assign_confidence(t2, sem, "upheld") == "Medium"
    assert pipeline.assign_confidence(t2, sem, "undetermined") == "Low"
    t2m = {"tier": "T2", "margin_flag": True}
    assert pipeline.assign_confidence(t2m, det, None) == "Low"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: Implement `pipeline.py`**

Structure (implement fully — key logic shown; helpers follow the shapes defined in
the Interfaces block above):

```python
"""Pipeline orchestration: start -> (Claude) -> resolve -> (Claude) -> finalize.

Claude never talks to this module directly; it reads *_requests.jsonl and writes
*_responses.jsonl. Everything it writes is validated before use.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import candidates as candidates_mod
import common
import compare_values
import coverage as coverage_mod
import extract
import normalize
import rules as rules_mod
import validate

PKG_ROOT = Path(__file__).resolve().parent.parent

_COMPANY_NORM_FIELDS = ["stig_description", "stig_objective_or_requirement",
                        "stig_command_or_value",
                        "company_approved_setting_or_expected_value",
                        "observed_value_or_evidence"]
_OFFICIAL_NORM_FIELDS = ["title", "check_text", "fix_text", "expected_value"]


def assign_confidence(match_record, finding, skeptic_outcome):
    tier = match_record.get("tier")
    deterministic = bool(finding.get("deterministic"))
    if match_record.get("margin_flag") or match_record.get("retried"):
        return "Low"
    if tier in ("T0", "T1") and deterministic:
        return "High"
    if tier == "T2" and deterministic:
        return "High"
    if tier == "T2" and not deterministic and skeptic_outcome == "upheld":
        return "Medium"
    return "Low"


def cmd_start(args):
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    official = extract.extract_official(args.official)
    company = extract.extract_company(args.company)
    normalize.add_normalized(official["records"], _OFFICIAL_NORM_FIELDS)
    normalize.add_normalized(company["records"], _COMPANY_NORM_FIELDS)

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
    common.write_jsonl(run_dir / "company_rows.jsonl", company["records"])
    (run_dir / "extract_warnings.json").write_text(json.dumps(
        official["warnings"] + company["warnings"], indent=1), encoding="utf-8")

    match_state = candidates_mod.generate(company["records"], official["records"])
    common.write_jsonl(run_dir / "match_state.jsonl", match_state)

    structuring = [
        {"row_id": r["row_id"],
         "original_company_text": r["original_company_text"],
         "context_grouping": r["context_grouping"],
         "instructions_file": "prompts/structuring.md"}
        for r in company["records"] if r["status"] == "needs-structuring"]
    common.write_jsonl(run_dir / "structuring_requests.jsonl", structuring)

    rules_by_id = {r["rule_id"]: r for r in official["records"]}
    rows_by_id = {r["row_id"]: r for r in company["records"]}
    matching = [
        {"row_id": m["row_id"], "row": rows_by_id[m["row_id"]],
         "candidates": [rules_by_id[c["rule_id"]] | {"_score": c["score"]}
                        for c in m["candidates"]],
         "instructions_file": "prompts/matching.md"}
        for m in match_state
        if m["tier"] is None and m["candidates"]
        and rows_by_id[m["row_id"]]["status"] == "ok"]
    common.write_jsonl(run_dir / "matching_requests.jsonl", matching)

    t_counts = {}
    for m in match_state:
        t_counts[m["tier"]] = t_counts.get(m["tier"], 0) + 1
    print(f"start: tiers={t_counts} structuring_pending={len(structuring)} "
          f"matching_pending={len(matching)}")
    return 0
```

`cmd_resolve(args)` — implement exactly the behavior in the Interfaces block:
load state, apply `structuring_responses.jsonl` (substring-verify each field with
`validate.quote_exists(field_value, raw_text)`; on success set fields +
`status="ok"`, regenerate that row's candidates, append a matching request; on
failure set `status="extraction-failed"`, `notes="structuring-rejected"`),
apply `matching_responses.jsonl` (validate; T2/T3/T4 transitions; margin
downgrade check — if `margin_flag` and `validate.quote_exists(rule_quote,
runner_up_rule_text)` then set `tier="T3"` with both rule IDs; failures →
`validation_failures.jsonl` + retry flag, second failure → `tier="T4"`,
warning `llm-output-rejected`, `retried=True` on the match record), then for
every matched pair call `compare_values.deterministic_verdict`; deterministic
results append to `findings.jsonl` with `finding_id`; `None` results append a
request to `semantic_requests.jsonl`. Rewrite `match_state.jsonl` and print
counts.

`cmd_finalize(args)` — implement exactly the Interfaces block: validate
`semantic_responses.jsonl` entries into findings (with `deterministic: False`),
enforce the pending-semantic refusal (exit 4) unless `--allow-pending` (pending
→ Cannot Assess findings with `basis="semantic-pass-not-run"`), merge skeptic
outcomes from `skeptic_responses.jsonl`, run `validate.dedup_findings` +
`validate.find_contradictions`, assign confidence + `human_review_needed`,
run `coverage_mod.compute` (abort exit 3 when not `ok`), write `final.json`,
call `report.render(run_dir)` unless `--no-report` (import `report` lazily
inside the function so Tasks 11 and 12 stay independently testable).

`main(argv)` — argparse with the three subcommands and flags exactly as tested.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_pipeline.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite to catch regressions**

Run: `python -m pytest stig-compare/tests -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add stig-compare/scripts/pipeline.py stig-compare/tests/test_pipeline.py
git commit -m "feat(stig-compare): pipeline start/resolve/finalize with validated Claude handoffs"
```

---

### Task 12: HTML report renderer

**Files:**
- Create: `stig-compare/scripts/report.py`
- Test: `stig-compare/tests/test_report.py`

**Interfaces:**
- Consumes: `final.json` from Task 11's `finalize` (shape defined there).
- Produces:
  - `render(run_dir: str|Path) -> Path` — reads `<run_dir>/final.json`, writes `<run_dir>/report.html`, returns its path.
  - The HTML is fully self-contained: one `<style>` block, one `<script>` block, **zero** external URLs (no `http://`, `https://`, `//` references anywhere in the file). All text is escaped with `html.escape` — document content must never break the markup or inject script.
  - Page structure (spec §8), in order:
    1. `<header>` — filenames, SHA-256 hashes, run timestamp, all versions, "CONTAINS SENSITIVE DOCUMENT CONTENT" label.
    2. `<section id="warnings">` — always rendered (with "No warnings" when empty); one `<div class="warning">` per coverage/extract/rule-conflict/validation warning; `low-coverage-red-banner` renders as `<div class="warning red-banner">`. Never inside a `<details>` element.
    3. `<section id="dashboard">` — count tiles: Compliant, Non-Compliant, Cannot Assess, Ambiguous, Unmatched rows, Unaddressed rules; company + official coverage tables.
    4. `<section id="findings">` — one `<article class="finding" data-fid="...">` per finding: verdict + confidence badges, `human_review_needed` badge, side-by-side two-column layout (company row: raw original text + `source_reference`; official rule: ID, title, check text, expected value), the evidence quotes, match tier + candidate score table, skeptic outcome, applied rule IDs. Filter buttons (verdict / confidence / review) implemented in the inline JS by toggling a CSS class.
    5. `<section id="leftovers">` — ambiguous matches (all candidate rules shown), unmatched company rows, unaddressed official rules, ignored content. `<details>` allowed here **except** any item with `human_review_needed` — those render open.
    6. Feedback UI: per finding a `<select class="fb">` with options `correct / incorrect / wrong match / missed difference / not meaningful / wrong classification / other` + `<input class="fb-comment">`; an "Export feedback" button that serializes `{"run": manifest-subset, "feedback": [{"finding_id", "classification", "comment"}]}` and triggers a download named `feedback.json` via a `data:` URI (works from `file://`).

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_report.py`:

```python
import json
import re
from pathlib import Path

import report


def _final(tmp_path):
    final = {
        "manifest": {"official_file": "o.csv", "company_file": "c.docx",
                     "official_sha256": "a" * 64, "company_sha256": "b" * 64,
                     "started": "2026-08-10T12:00:00",
                     "versions": {"skill_version": "0.1.0", "prompt_hashes": {}},
                     "registry_version": 1, "rule_conflicts": []},
        "findings": [{
            "finding_id": "F-11112222", "row_id": "R-aaaa0001",
            "rule_id": "V-1001", "verdict": "Compliant",
            "finding_type": None, "deterministic": True,
            "confidence": "High", "human_review_needed": False,
            "basis": "value-comparison",
            "observation": {"observed": "9", "expected": "9 or more"},
            "interpretation": None, "skeptic": None, "applied_rules": [],
            "match": {"tier": "T1", "candidates": [
                {"rule_id": "V-1001", "score": 3.2}]},
            "company_row": {"original_company_text":
                            "High | <b>reuse</b> | 9",
                            "source_reference": {"table_index": 1,
                                                 "row_index": 1}},
            "official_rule": {"rule_id": "V-1001", "title": "Password reuse",
                              "check_text": "check", "expected_value": "9 or more"}}],
        "match_state": [], "ambiguous": [],
        "coverage": {"company": {"total": 1, "matched": 1, "ambiguous": 0,
                                 "unmatched": 0, "ignored_by_rule": 0,
                                 "extraction_failed": 0,
                                 "needs_structuring_unresolved": 0},
                     "official": {"total": 5, "addressed": 1, "unaddressed": 4,
                                  "duplicate_coverage_rule_ids": []},
                     "warnings": [{"code": "low-coverage-red-banner",
                                   "detail": "2/10 rows not compared"}],
                     "ok": True},
        "warnings": [], "unmatched_rows": [], "unaddressed_rules": []}
    (tmp_path / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return tmp_path


def test_render_self_contained(tmp_path):
    out = report.render(_final(tmp_path))
    html_text = Path(out).read_text(encoding="utf-8")
    assert "https://" not in html_text and "http://" not in html_text
    assert "F-11112222" in html_text
    assert "CONTAINS SENSITIVE DOCUMENT CONTENT" in html_text


def test_document_text_is_escaped(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert "<b>reuse</b>" not in html_text          # raw tag must not survive
    assert "&lt;b&gt;reuse&lt;/b&gt;" in html_text


def test_red_banner_never_in_details(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert "red-banner" in html_text
    warnings_section = re.search(
        r"<section id=\"warnings\">.*?</section>", html_text, re.S).group(0)
    assert "<details" not in warnings_section


def test_feedback_widgets_present(tmp_path):
    html_text = Path(report.render(_final(tmp_path))).read_text(encoding="utf-8")
    assert 'class="fb"' in html_text
    assert "wrong match" in html_text
    assert "Export feedback" in html_text
    assert "data-fid=\"F-11112222\"" in html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report'`

- [ ] **Step 3: Implement `report.py`**

Implementation notes (write the full renderer; it is plain string templating):

```python
"""Self-contained HTML report. Verification-first (spec section 8).

Every piece of document text passes through esc(). No external assets.
"""
import html
import json
from pathlib import Path

def esc(x):
    return html.escape(str(x if x is not None else ""))

_CSS = """
:root{--ok:#1a7f37;--bad:#b42318;--warn:#946200;--muted:#667085;
      font-family:Segoe UI,system-ui,sans-serif}
body{margin:0;padding:1.5rem;background:#f8fafc;color:#101828}
header{border-bottom:2px solid #d0d5dd;padding-bottom:1rem}
.sensitive{background:#fef0c7;color:#7a2e0e;padding:.4rem .8rem;
           font-weight:600;display:inline-block;border-radius:4px}
.warning{background:#fffaeb;border-left:4px solid var(--warn);
         padding:.6rem .9rem;margin:.4rem 0}
.warning.red-banner{background:#fef3f2;border-left-color:var(--bad);
                    font-weight:700}
.tiles{display:flex;gap:.8rem;flex-wrap:wrap;margin:1rem 0}
.tile{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
      padding:.8rem 1.2rem;min-width:8rem;text-align:center}
.tile b{display:block;font-size:1.6rem}
.finding{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
         padding:1rem;margin:.8rem 0}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;
       font-size:.8rem;font-weight:600;margin-right:.4rem}
.badge.Compliant{background:#ecfdf3;color:var(--ok)}
.badge.Non-Compliant{background:#fef3f2;color:var(--bad)}
.badge.review{background:#fef0c7;color:#7a2e0e}
.quote{background:#f2f4f7;border-left:3px solid #98a2b3;padding:.3rem .6rem;
       font-family:Consolas,monospace;font-size:.85rem;white-space:pre-wrap}
table{border-collapse:collapse}td,th{border:1px solid #e4e7ec;
      padding:.3rem .6rem;font-size:.85rem}
.hidden{display:none}
"""

_JS = """
function applyFilters(){ /* toggle .hidden on .finding by data attributes */ }
document.querySelectorAll('.filter').forEach(b=>b.addEventListener('click',e=>{
  b.classList.toggle('active');applyFilters();}));
function exportFeedback(){
  const items=[];
  document.querySelectorAll('.finding').forEach(f=>{
    const sel=f.querySelector('.fb'), c=f.querySelector('.fb-comment');
    if(sel && sel.value) items.push({finding_id:f.dataset.fid,
      classification:sel.value, comment:c?c.value:''});});
  const payload=JSON.stringify({run:window.RUN_META,feedback:items},null,1);
  const a=document.createElement('a');
  a.href='data:application/json;charset=utf-8,'+encodeURIComponent(payload);
  a.download='feedback.json';a.click();}
"""
```

`render(run_dir)` assembles the sections in the order given in the Interfaces
block, using only `esc()`-wrapped values inside markup, embeds
`window.RUN_META = {json of manifest subset: files, hashes, started, versions}`
in the script block, and writes `report.html` UTF-8. Findings filter data goes in
`data-verdict`, `data-confidence`, `data-review` attributes; `applyFilters` shows
a finding only if it matches every active filter group (implement it fully —
roughly 15 lines of JS). Feedback `<select>` options exactly:
`["", "correct", "incorrect", "wrong match", "missed difference",
"not meaningful", "wrong classification", "other"]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_report.py -v`
Expected: 4 passed

- [ ] **Step 5: Visual sanity check**

Run: `python -m pytest stig-compare/tests/test_pipeline.py -v` (regenerates a run),
then manually open one generated `report.html` in a browser once during this task
and confirm the dashboard, a finding card, and the export button render sensibly.
This is a human check — do not skip it; note the result in the commit message.

- [ ] **Step 6: Commit**

```bash
git add stig-compare/scripts/report.py stig-compare/tests/test_report.py
git commit -m "feat(stig-compare): self-contained verification-first HTML report with feedback export"
```

---

### Task 13: Feedback ingestion → stored feedback + regression case + candidate rule

**Files:**
- Create: `stig-compare/scripts/feedback.py`
- Create: `stig-compare/feedback/.gitkeep`, `stig-compare/tests/regression/.gitkeep`
- Test: `stig-compare/tests/test_feedback.py`

**Interfaces:**
- Consumes: `final.json` (Task 11), rule record shape (Task 9), `common.short_hash`.
- Produces:
  - `ingest(feedback_path, run_dir, package_root) -> dict` — reads a `feedback.json` (report-exported shape from Task 12: `{"run": {...}, "feedback": [{"finding_id", "classification", "comment"}]}`) and, for each item:
    1. Resolves the finding in `<run_dir>/final.json`; unknown `finding_id` → recorded in the returned `{"errors": [...]}` list, skipped (visible, not silent).
    2. Writes `<package_root>/feedback/FB-<8hex>.json` (`FB-` + `short_hash(finding_id, classification, run started timestamp)`): the feedback item + a **snapshot**: the finding, its company row (raw text + source_reference only), its official rule, match record, manifest subset (hashes, versions). Duplicate FB id → skipped with error `"duplicate-feedback"`.
    3. **Always** writes a regression case `<package_root>/tests/regression/RC-<same 8hex>.json`:
       `{"case_id", "feedback_id", "snapshot": {...}, "expected": {...}}` where `expected` is derived from the classification: `wrong match` → `{"not_matched_rule_id": <rule_id>}`; `incorrect`/`wrong classification` → `{"not_verdict": <verdict>}`; `missed difference` → `{"needs_human_review": true}`; `correct` → `{"verdict": <verdict>, "matched_rule_id": <rule_id>}` (a pin — protects a known-good result); `not meaningful`/`other` → `{"note_only": true}`.
    4. Drafts a candidate rule **only** for classifications that map to a category: `wrong match` → category `matching-key` with payload `{"exclude_rule_id": rule_id, "row_technical_tokens": [...]}`, scope `field`; `not meaningful` → category `ignore-field`, scope `field`, payload `{"field": "observed_value_or_evidence"}` only when the comment names no other field. Everything else drafts **no** rule. Drafts go to `<package_root>/rules/candidates/RL-<8hex>.json` with `status="candidate"`, provenance listing the feedback ID.
    - Returns `{"stored": [FB ids], "cases": [RC ids], "candidates": [RL ids], "errors": [...]}`.
  - CLI: `python stig-compare/scripts/feedback.py ingest <feedback.json> --run-dir <dir>` printing the summary counts.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_feedback.py`:

```python
import json
from pathlib import Path

import pytest

import feedback


@pytest.fixture()
def env(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "feedback").mkdir(parents=True)
    (pkg / "tests" / "regression").mkdir(parents=True)
    (pkg / "rules" / "candidates").mkdir(parents=True)
    run = tmp_path / "run"
    run.mkdir()
    final = {"manifest": {"started": "2026-08-10T12:00:00",
                          "official_sha256": "a" * 64,
                          "company_sha256": "b" * 64,
                          "versions": {"skill_version": "0.1.0"}},
             "findings": [{"finding_id": "F-11112222", "row_id": "R-aaaa0001",
                           "rule_id": "V-1001", "verdict": "Compliant",
                           "match": {"tier": "T2"},
                           "company_row": {"original_company_text": "row text",
                                           "source_reference": {"table_index": 1,
                                                                "row_index": 1}},
                           "official_rule": {"rule_id": "V-1001",
                                             "title": "t", "check_text": "c"}}]}
    (run / "final.json").write_text(json.dumps(final), encoding="utf-8")
    return pkg, run


def _fb(items):
    return {"run": {"started": "2026-08-10T12:00:00"}, "feedback": items}


def test_wrong_match_creates_case_and_candidate(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "wrong match",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert len(result["stored"]) == 1
    assert len(result["cases"]) == 1
    assert len(result["candidates"]) == 1
    case = json.loads(next((pkg / "tests" / "regression").glob("RC-*.json"))
                      .read_text(encoding="utf-8"))
    assert case["expected"] == {"not_matched_rule_id": "V-1001"}
    cand = json.loads(next((pkg / "rules" / "candidates").glob("RL-*.json"))
                      .read_text(encoding="utf-8"))
    assert cand["status"] == "candidate"          # never active automatically
    assert cand["provenance"]["feedback_ids"] == result["stored"]


def test_correct_pins_result_but_no_rule(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "correct",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert len(result["cases"]) == 1
    assert result["candidates"] == []
    case = json.loads(next((pkg / "tests" / "regression").glob("RC-*.json"))
                      .read_text(encoding="utf-8"))
    assert case["expected"] == {"verdict": "Compliant",
                                "matched_rule_id": "V-1001"}


def test_unknown_finding_is_visible_error(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-doesnot1",
                                  "classification": "incorrect",
                                  "comment": ""}])), encoding="utf-8")
    result = feedback.ingest(p, run, pkg)
    assert result["stored"] == []
    assert any("F-doesnot1" in e for e in result["errors"])


def test_duplicate_feedback_skipped(env, tmp_path):
    pkg, run = env
    p = tmp_path / "fb.json"
    p.write_text(json.dumps(_fb([{"finding_id": "F-11112222",
                                  "classification": "wrong match",
                                  "comment": ""}])), encoding="utf-8")
    feedback.ingest(p, run, pkg)
    result2 = feedback.ingest(p, run, pkg)
    assert result2["stored"] == []
    assert any("duplicate-feedback" in e for e in result2["errors"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_feedback.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'feedback'`

- [ ] **Step 3: Implement `feedback.py`**

Follow the Interfaces block exactly. Skeleton:

```python
"""Feedback ingestion. Feedback NEVER becomes an active rule directly
(spec section 9): it always becomes a regression case, and at most a
candidate rule draft awaiting the Task 14 review gate."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import candidates as candidates_mod
import common

_RULE_MAPPING = {"wrong match": "matching-key", "not meaningful": "ignore-field"}


def _expected_for(classification, finding):
    if classification == "wrong match":
        return {"not_matched_rule_id": finding["rule_id"]}
    if classification in ("incorrect", "wrong classification"):
        return {"not_verdict": finding["verdict"]}
    if classification == "missed difference":
        return {"needs_human_review": True}
    if classification == "correct":
        return {"verdict": finding["verdict"],
                "matched_rule_id": finding["rule_id"]}
    return {"note_only": True}


def ingest(feedback_path, run_dir, package_root):
    ...  # per the Interfaces block; ~80 lines
```

Candidate-rule draft for `wrong match` uses
`candidates_mod.technical_tokens(snapshot company row raw text)` for the payload
token list, scope `{"level": "field", "value": "stig_command_or_value"}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_feedback.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/feedback.py stig-compare/feedback stig-compare/tests
git commit -m "feat(stig-compare): feedback ingestion with regression cases and candidate rule drafts"
```

---

### Task 14: Regression suite runner and rule-approval gate

**Files:**
- Create: `stig-compare/scripts/regression.py`
- Test: `stig-compare/tests/test_regression.py`

**Interfaces:**
- Consumes: regression case shape (Task 13), rule registry (Task 9), `candidates.generate`, `compare_values.deterministic_verdict`.
- Produces:
  - `run_case(case: dict, registry: dict) -> dict` — replays the deterministic stages on the case's snapshot: rebuilds the one-row/one-ruleset match via `candidates.generate([company_row], official_rules_from_snapshot)` and the verdict via `compare_values.deterministic_verdict`, then evaluates `expected`:
    - `not_matched_rule_id` → pass if the replayed match does **not** deterministically (T0/T1) match that rule
    - `not_verdict` → pass if the replayed deterministic verdict is not that verdict (or is None → semantic, counts as pass with `"agent-evaluated": true`)
    - `verdict`+`matched_rule_id` (a pin) → pass if replay still produces them; semantic-only aspects → `"agent-evaluated": true`, advisory
    - `needs_human_review` / `note_only` → always `"agent-evaluated": true`, advisory
    - Returns `{"case_id", "passed": bool, "advisory": bool, "detail": str}`.
  - `run_suite(package_root, registry: dict|None = None) -> dict` — runs every `tests/regression/RC-*.json`; returns `{"total", "passed", "failed", "advisory", "failures": [case results]}`. `registry=None` loads the active registry.
  - `evaluate_candidate(package_root, candidate_path) -> dict` — the **approval gate**: loads the candidate rule, builds a trial registry = active registry + candidate with `status="active"`, runs `run_suite` twice (baseline and trial), and returns `{"candidate_id", "baseline": {...}, "trial": {...}, "regressions": [case ids that passed baseline but failed trial], "approvable": bool}` — `approvable` is `True` only when `regressions == []` and trial `failed == 0`. **This function never writes to the registry**; SKILL.md's review mode calls it and only a human approval leads to the write.
  - `approve_candidate(package_root, candidate_path, approver: str) -> dict` — moves the candidate into `registry.json` with `status="active"`, `provenance.approved_by=approver`, `provenance.approved=<now>`, bumps `registry_version`, deletes the candidate file. Raises `RuntimeError` if `evaluate_candidate` says not approvable (defense in depth — the gate cannot be skipped programmatically).

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_regression.py`:

```python
import json
from pathlib import Path

import pytest

import regression


_SNAPSHOT = {
    "company_row": {"row_id": "R-aaaa0001", "status": "ok",
                    "context_grouping": "High",
                    "stig_description": "reuse recent passwords",
                    "stig_objective_or_requirement":
                        "Password reuse must be restricted",
                    "stig_command_or_value":
                        "Run SHOW PARAMETER password_reuse_max",
                    "company_approved_setting_or_expected_value": "9 or more",
                    "observed_value_or_evidence": "9",
                    "original_company_text":
                        "High | reuse | password_reuse_max | 9"},
    "official_rules": [
        {"rule_id": "V-1001", "title": "Password reuse must be restricted",
         "severity": "high",
         "check_text": "Run SHOW PARAMETER password_reuse_max",
         "fix_text": "Set password_reuse_max to 9 or more.",
         "expected_value": "9 or more"}],
}


def _pkg(tmp_path, cases):
    pkg = tmp_path / "pkg"
    (pkg / "tests" / "regression").mkdir(parents=True)
    (pkg / "rules" / "candidates").mkdir(parents=True)
    (pkg / "rules" / "registry.json").write_text(
        json.dumps({"registry_version": 1, "rules": []}), encoding="utf-8")
    for i, case in enumerate(cases):
        (pkg / "tests" / "regression" / f"RC-{i:08d}.json").write_text(
            json.dumps(case), encoding="utf-8")
    return pkg


def test_pin_case_passes(tmp_path):
    case = {"case_id": "RC-00000000", "feedback_id": "FB-x",
            "snapshot": _SNAPSHOT,
            "expected": {"verdict": "Compliant", "matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [case])
    result = regression.run_suite(pkg)
    assert result["total"] == 1 and result["passed"] == 1


def test_not_matched_case_fails_when_replay_still_matches(tmp_path):
    case = {"case_id": "RC-00000000", "feedback_id": "FB-x",
            "snapshot": _SNAPSHOT,
            "expected": {"not_matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [case])
    result = regression.run_suite(pkg)
    assert result["failed"] == 1        # T1 still matches V-1001 -> user's
    #                                     complaint is not yet fixed by any rule


def test_gate_blocks_harmful_candidate(tmp_path):
    pin = {"case_id": "RC-00000000", "feedback_id": "FB-a",
           "snapshot": _SNAPSHOT,
           "expected": {"verdict": "Compliant", "matched_rule_id": "V-1001"}}
    pkg = _pkg(tmp_path, [pin])
    # candidate that would ignore observed evidence globally -> breaks the pin
    cand = {"rule_id": "RL-bad00001", "version": 1, "category": "ignore-field",
            "scope": {"level": "global", "value": None}, "status": "candidate",
            "payload": {"field": "observed_value_or_evidence"},
            "provenance": {"feedback_ids": ["FB-b"], "approved_by": None,
                           "created": "2026-08-10", "approved": None}}
    cpath = pkg / "rules" / "candidates" / "RL-bad00001.json"
    cpath.write_text(json.dumps(cand), encoding="utf-8")
    verdict = regression.evaluate_candidate(pkg, cpath)
    assert verdict["approvable"] is False
    assert "RC-00000000" in verdict["regressions"]
    with pytest.raises(RuntimeError):
        regression.approve_candidate(pkg, cpath, approver="tester")


def test_approve_writes_registry_and_bumps_version(tmp_path):
    pkg = _pkg(tmp_path, [])            # no cases -> nothing can regress
    cand = {"rule_id": "RL-good0001", "version": 1,
            "category": "equivalent-terminology",
            "scope": {"level": "field", "value": "observed_value_or_evidence"},
            "status": "candidate", "payload": {"a": "enabled", "b": "turned on"},
            "provenance": {"feedback_ids": ["FB-c"], "approved_by": None,
                           "created": "2026-08-10", "approved": None}}
    cpath = pkg / "rules" / "candidates" / "RL-good0001.json"
    cpath.write_text(json.dumps(cand), encoding="utf-8")
    regression.approve_candidate(pkg, cpath, approver="maintainer")
    reg = json.loads((pkg / "rules" / "registry.json").read_text(encoding="utf-8"))
    assert reg["registry_version"] == 2
    assert reg["rules"][0]["rule_id"] == "RL-good0001"
    assert reg["rules"][0]["status"] == "active"
    assert reg["rules"][0]["provenance"]["approved_by"] == "maintainer"
    assert not cpath.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_regression.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regression'`

- [ ] **Step 3: Implement `regression.py`**

Implement per the Interfaces block. The `ignore-field` rule's effect during
replay: when an active `ignore-field` rule applies (via
`rules.applicable_rules` with the case's field context), `run_case` blanks that
field on a **copy** of the snapshot's company row before replay — that is how a
harmful global ignore-rule breaks the pin case (blanked
`observed_value_or_evidence` forces Cannot Assess ≠ pinned Compliant).
`equivalent-terminology` rules have no deterministic replay effect (semantic
only) — they can never break a deterministic pin.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_regression.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/scripts/regression.py stig-compare/tests/test_regression.py
git commit -m "feat(stig-compare): regression suite and rule-approval gate that blocks harmful rules"
```

---

### Task 15: Prompt templates

**Files:**
- Create: `stig-compare/prompts/structuring.md`, `matching.md`, `semantic_compare.md`, `validator.md`
- Test: `stig-compare/tests/test_prompts_and_skill.py` (prompt half; Task 16 adds the SKILL.md half)

**Interfaces:**
- Consumes: request/response JSON shapes from Tasks 8 and 11 — the prompts must describe **exactly** those schemas, field for field.
- Produces: four prompt files. Common preamble in every file (verbatim):

```
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
```

- `structuring.md`: input = one `structuring_requests.jsonl` record; output schema `{"row_id", "stig_description", "stig_objective_or_requirement", "stig_command_or_value", "company_approved_setting_or_expected_value", "observed_value_or_evidence"}`; instruction that every non-empty field value must be a verbatim substring of `original_company_text`, and fields with no supporting text must be `""` (never paraphrase).
- `matching.md`: input = one `matching_requests.jsonl` record; output schema = Task 8's match schema (`decision/rule_id/ambiguous_rule_ids/row_quote/rule_quote/basis`); instructions: choose only among the listed candidates; if two candidates fit, answer `ambiguous` listing them; if none fits, answer `none`; severity similarity alone is never a basis; `row_quote` and `rule_quote` must be the discriminating evidence, not generic text.
- `semantic_compare.md`: input = one `semantic_requests.jsonl` record; output schema = Task 8's semantic schema (`finding_type/verdict/row_quote/rule_quote/interpretation`); instructions: verdict `Compliant` only when the row's evidence demonstrably satisfies the official expected value; missing/unclear evidence → `Cannot Assess`; document contradictions as `contradictory`; the `interpretation` field is the only place for reasoning.
- `validator.md`: input = one finding + raw evidence (row text, rule text) **without** the first pass's reasoning; instruction: your goal is to DISPROVE the finding — hunt for misquotes, wrong-record comparisons, meaning-changing normalization, formatting-only differences classified as semantic; output `{"finding_id", "outcome": "upheld"|"refuted"|"undetermined", "reason"}`; refute only with concrete evidence, otherwise `undetermined`.

- [ ] **Step 1: Write the failing tests**

`stig-compare/tests/test_prompts_and_skill.py`:

```python
from pathlib import Path

import common

PKG = Path(__file__).resolve().parent.parent
PROMPTS = ["structuring.md", "matching.md", "semantic_compare.md",
           "validator.md"]


def test_all_prompts_exist_with_strict_preamble():
    for name in PROMPTS:
        text = (PKG / "prompts" / name).read_text(encoding="utf-8")
        assert "STRICT RULES" in text
        assert "ONLY the evidence supplied" in text
        assert "VERBATIM" in text


def test_prompts_state_their_schemas():
    matching = (PKG / "prompts" / "matching.md").read_text(encoding="utf-8")
    for key in ["decision", "rule_id", "ambiguous_rule_ids", "row_quote",
                "rule_quote", "basis"]:
        assert f'"{key}"' in matching
    semantic = (PKG / "prompts" / "semantic_compare.md").read_text(encoding="utf-8")
    for key in ["finding_type", "verdict", "row_quote", "rule_quote",
                "interpretation"]:
        assert f'"{key}"' in semantic
    validator = (PKG / "prompts" / "validator.md").read_text(encoding="utf-8")
    assert "DISPROVE" in validator
    assert '"outcome"' in validator


def test_prompt_hashes_land_in_versions():
    v = common.load_versions(PKG)
    assert set(PROMPTS) <= set(v["prompt_hashes"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_prompts_and_skill.py -v`
Expected: FAIL with `FileNotFoundError` on the first prompt file

- [ ] **Step 3: Write the four prompt files**

Write each file with: title, the STRICT RULES preamble verbatim, an "Input"
section describing the request record fields, an "Output schema" section showing
the exact JSON object with every key quoted (matching Task 8/11 shapes), and a
short "Decision guide" section with the per-prompt instructions from the
Interfaces block. Keep each file under ~80 lines; no examples that could leak
into outputs as fabricated content.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest stig-compare/tests/test_prompts_and_skill.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add stig-compare/prompts stig-compare/tests/test_prompts_and_skill.py
git commit -m "feat(stig-compare): strict centralized prompt templates"
```

---

### Task 16: SKILL.md orchestration + end-to-end test

**Files:**
- Create: `stig-compare/SKILL.md`
- Test: `stig-compare/tests/test_end_to_end.py`; extend `stig-compare/tests/test_prompts_and_skill.py`

**Interfaces:**
- Consumes: everything.
- Produces: the Skill entry point. `SKILL.md` frontmatter + body must direct the agent (its future executor) through:
  1. **Trigger/description** (frontmatter): name `stig-compare`; description covering "compare a company STIG submission against an official STIG file and generate an HTML comparison report" and the three modes (compare, ingest feedback, review rules).
  2. **Compare mode**: ask the user for exactly two file paths (official + company) if not given; create `runs/<timestamp>` dir; run `pipeline.py start`; then for each record in `structuring_requests.jsonl` / `matching_requests.jsonl`: read the named `instructions_file`, follow it, append the JSON response to the matching `*_responses.jsonl`; run `pipeline.py resolve`; repeat while `resolve` reports retries or new requests (max 2 rounds); answer `semantic_requests.jsonl` the same way; **dispatch the skeptical validator via the Agent tool as an isolated subagent** — one dispatch per batch of semantic findings, subagent receives `validator.md` + the finding + raw evidence only, its output goes to `skeptic_responses.jsonl`; run `pipeline.py finalize`; present the report path plus a summary that leads with warnings and coverage, never with a confidence statement.
  3. **Hard rules for the executing agent** (verbatim in SKILL.md): "Never edit files in `runs/` except `*_responses.jsonl`. Never mark a response for a row that has no request. Never proceed past a non-zero pipeline exit code — surface it. Never summarize findings not present in `final.json`."
  4. **Feedback mode**: `feedback.py ingest <file> --run-dir <dir>`; report stored/case/candidate counts; remind that candidates need review.
  5. **Review mode**: for each file in `rules/candidates/`: show the rule + originating feedback, run `regression.evaluate_candidate`, show baseline vs trial and any regressions, ask the human maintainer explicitly, and only on their yes call `regression.approve_candidate` with their stated name. Never auto-approve.
- End-to-end test: full pipeline against the Task 2 fixtures with **scripted stand-in responses** (the test plays Claude's role — this keeps the suite deterministic and offline; the real prompts are exercised by the agent at runtime, guarded by the same validators the test goes through).

- [ ] **Step 1: Write the failing tests**

Append to `stig-compare/tests/test_prompts_and_skill.py`:

```python
def test_skill_md_orchestration_contract():
    text = (PKG / "SKILL.md").read_text(encoding="utf-8")
    assert "name: stig-compare" in text
    for needle in ["pipeline.py start", "pipeline.py resolve",
                   "pipeline.py finalize", "structuring_requests.jsonl",
                   "matching_requests.jsonl", "semantic_requests.jsonl",
                   "skeptic_responses.jsonl", "feedback.py ingest",
                   "evaluate_candidate", "Never auto-approve"]:
        assert needle in text
```

`stig-compare/tests/test_end_to_end.py`:

```python
import json
from pathlib import Path

import pytest

from fixtures.build_fixtures import build_all
import common
import pipeline


def _answer_matching(run_dir):
    """Scripted stand-in for the Claude matching pass."""
    requests = common.read_jsonl(run_dir / "matching_requests.jsonl")
    responses = []
    for req in requests:
        row = req["row"]
        # simple stand-in policy: match top candidate iff it shares a
        # technical token or >=4 common words; else none
        top = req["candidates"][0]
        row_words = set(row["original_company_text"].lower().split())
        rule_words = set((top["title"] + " " + top["check_text"]).lower().split())
        if len(row_words & rule_words) >= 4:
            responses.append({"row_id": req["row_id"], "decision": "match",
                              "rule_id": top["rule_id"],
                              "ambiguous_rule_ids": [],
                              "row_quote": row["stig_objective_or_requirement"]
                              or row["original_company_text"][:30],
                              "rule_quote": top["title"],
                              "basis": "shared requirement wording"})
        else:
            responses.append({"row_id": req["row_id"], "decision": "none",
                              "rule_id": None, "ambiguous_rule_ids": [],
                              "row_quote": "", "rule_quote": "", "basis": "no fit"})
    common.write_jsonl(run_dir / "matching_responses.jsonl", responses)


def _answer_semantic(run_dir):
    path = run_dir / "semantic_requests.jsonl"
    if not path.exists():
        return
    responses = []
    for req in common.read_jsonl(path):
        responses.append({"row_id": req["row_id"], "rule_id": req["rule_id"],
                          "finding_type": "cannot-determine",
                          "verdict": "Cannot Assess",
                          "row_quote": req["row"]["original_company_text"][:20],
                          "rule_quote": req["rule"]["title"][:20],
                          "interpretation": "stand-in: not decidable"})
    common.write_jsonl(run_dir / "semantic_responses.jsonl", responses)


def test_full_run_clean_docx(tmp_path):
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run"
    assert pipeline.main(["start", "--official", str(fx["official_csv"]),
                          "--company", str(fx["company_docx"]),
                          "--run-dir", str(run_dir)]) == 0
    _answer_matching(run_dir)
    assert pipeline.main(["resolve", "--run-dir", str(run_dir)]) == 0
    _answer_semantic(run_dir)
    assert pipeline.main(["finalize", "--run-dir", str(run_dir),
                          "--allow-pending"]) == 0

    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    cov = final["coverage"]
    assert cov["ok"] is True
    assert cov["company"]["total"] == 4
    # row 1 (password_reuse_max, observed 9): T1 match, deterministic Compliant
    compliant = [f for f in final["findings"] if f["verdict"] == "Compliant"]
    assert any(f["rule_id"] == "V-1001" and f["confidence"] == "High"
               for f in compliant)
    # row 3 (vague, no evidence): must be Cannot Assess, never Compliant
    vague = [f for f in final["findings"]
             if f.get("basis") == "missing-evidence"]
    assert all(f["verdict"] == "Cannot Assess" for f in vague)
    # row 4 (screensaver): unmatched, visible in leftovers
    assert cov["company"]["unmatched"] >= 1
    assert (run_dir / "report.html").exists()
    html_text = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "https://" not in html_text


def test_full_run_identical_content_no_false_positives(tmp_path):
    """Identical-files case: company xlsx mirrors official values exactly ->
    nothing may be Non-Compliant."""
    fx = build_all(tmp_path / "fx")
    run_dir = tmp_path / "run2"
    pipeline.main(["start", "--official", str(fx["official_csv"]),
                   "--company", str(fx["company_xlsx"]),
                   "--run-dir", str(run_dir)])
    _answer_matching(run_dir)
    pipeline.main(["resolve", "--run-dir", str(run_dir)])
    _answer_semantic(run_dir)
    pipeline.main(["finalize", "--run-dir", str(run_dir), "--allow-pending"])
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    row1 = [f for f in final["findings"] if f["rule_id"] == "V-1001"]
    assert all(f["verdict"] != "Non-Compliant" for f in row1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest stig-compare/tests/test_end_to_end.py stig-compare/tests/test_prompts_and_skill.py -v`
Expected: e2e may partially pass (pipeline exists); `test_skill_md_orchestration_contract` FAILS with `FileNotFoundError` — and any e2e failure found here is a real integration bug to fix now.

- [ ] **Step 3: Write `SKILL.md`**

Frontmatter:

```markdown
---
name: stig-compare
description: Compare a company STIG submission (Word/Excel) against an official
  STIG file (CSV/JSON/Excel) and generate a self-contained HTML comparison
  report. Also ingests report feedback and reviews candidate comparison rules.
  Use when the user wants to check a STIG submission, compare STIG files, or
  mentions STIG compliance review.
---
```

Body: the three mode walkthroughs exactly as specified in the Interfaces block,
including the verbatim hard-rules block, the request→response loop instructions
(read `instructions_file`, answer one JSON object per request line, append to
`*_responses.jsonl`), the Agent-tool dispatch for `validator.md` (isolated
subagent, evidence only, never the first-pass reasoning), and the final
presentation rule (lead with warnings + coverage; the report path; offer the
feedback flow).

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest stig-compare/tests -v`
Expected: all tests pass, including both e2e scenarios

- [ ] **Step 5: Commit**

```bash
git add stig-compare/SKILL.md stig-compare/tests
git commit -m "feat(stig-compare): SKILL.md orchestration and end-to-end pipeline tests"
```

---

## Adversarial Review Gate (after all tasks)

The spec's §16-17 adversarial review is part of this plan, not optional polish.
After Task 16, walk each item and fix material findings before declaring done:

- [ ] Hallucination containment: grep the pipeline for any path where a Claude
  response field reaches `final.json` without passing through `validate.py`.
  There must be none.
- [ ] Wrong-record risk: confirm `resolve` rejects a response whose `row_id`
  has no pending request (add the check if missed).
- [ ] Silent skips: confirm every company row appears in exactly one coverage
  bucket in a run against `company_docx_messy` with no responses provided.
- [ ] Normalization: confirm `classify_difference("60 days", "90 days")` is
  `"different"` and no normalizer strips digits or units.
- [ ] Confidentiality: grep `scripts/` for `print`/logging of row text — only
  IDs, counts, and codes may be printed; report content lives only in the
  report and artifacts.
- [ ] Failure visibility: force `extract_official` on a corrupted file (write
  3 junk bytes as `.xlsx`) — exit code 2 and a typed error, no traceback dump
  of content.
- [ ] Proposal fidelity: re-read `PROPOSAL.md` §5-7 and confirm the output
  fields (`matched_stig_id`→`rule_id`, `match_confidence`→`confidence`,
  `compliance_verdict`→`verdict`, `human_review_needed`) all surface in
  `final.json` and the report.

## Execution Notes

- Tasks 1–10 are independent of Claude entirely; Tasks 11–16 wire the handoffs.
  Implement strictly in order — later tasks import earlier modules.
- The pytest suite is fully offline and deterministic; the real Claude passes
  are exercised only at Skill runtime and are guarded by the same validators
  the tests exercise.
- If `python-docx` or `openpyxl` turn out to be missing in the target
  environment, stop and surface it — do not substitute hand-rolled parsers
  without a plan revision (spec decision: libraries are available).
