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

import docx
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
        if not records and not warnings:
            warnings.append({"code": "empty-official-file", "detail": "csv: no data rows"})
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
        elif all(not any(rec[k] for k in OFFICIAL_HEADER_SYNONYMS)
                for rec in records):
            # Records parsed, but none of their keys matched a canonical
            # field name (JSON records are matched by exact canonical key,
            # not the header-synonym table used for CSV/XLSX) -- surface
            # that instead of silently emitting N all-blank records.
            warnings.append({"code": "unmapped-json-keys",
                             "detail": f"{len(records)} records, all "
                                      "canonical fields empty"})
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

COMPANY_HEADER_HINTS = COMPANY_HEADER_SYNONYMS

_COMPANY_FIELDS = list(COMPANY_HEADER_SYNONYMS)


def _has_merged_cells(docx_row):
    """Detect if a docx row has merged cells by checking XML attributes."""
    from docx.oxml.ns import qn
    if not docx_row.cells:
        return False
    # Check for gridSpan > 1 or vMerge attributes which indicate cell merging
    for cell in docx_row.cells:
        tcPr = cell._element.find(qn('w:tcPr'))
        if tcPr is not None:
            gridSpan = tcPr.find(qn('w:gridSpan'))
            vMerge = tcPr.find(qn('w:vMerge'))
            if gridSpan is not None or vMerge is not None:
                return True
    return False


def _company_tables(path):
    """Yield (table_index, sheet_or_section, header_row, data_rows, merged_flags)."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        d = docx.Document(str(path))
        for ti, table in enumerate(d.tables, start=1):
            rows = [[c.text for c in row.cells] for row in table.rows]
            merged_flags = [False] + [_has_merged_cells(row) for row in table.rows[1:]]
            if rows:
                yield ti, "document-body", rows[0], rows[1:], merged_flags[1:]
    elif path.suffix.lower() == ".xlsx":
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        for ti, ws in enumerate(wb.worksheets, start=1):
            rows = _rows_from_xlsx_sheet(ws)
            if rows:
                yield ti, f"sheet={ws.title}", rows[0], rows[1:], [False] * len(rows[1:])
    else:
        raise ValueError(f"unsupported company file type: {path.suffix}")


def extract_company(path):
    records, warnings = [], []
    any_table = False
    for ti, section, headers, data_rows, merged_flags in _company_tables(path):
        any_table = True
        mapping = _map_headers(headers, COMPANY_HEADER_SYNONYMS)
        mapped_fields = {v for v in mapping.values() if v}
        mappable = len(mapped_fields) >= 3
        if not mappable:
            warnings.append({"code": "unmapped-headers", "detail": f"table={ti}"})
        for ri, (row, has_merged) in enumerate(zip(data_rows, merged_flags), start=1):
            original = " | ".join(str(c) for c in row)
            rec = {f: "" for f in _COMPANY_FIELDS}
            rec["row_id"] = common.row_id(ti, ri, original)
            rec["source_reference"] = {"table_index": ti, "row_index": ri,
                                       "sheet_or_section": section}
            rec["original_company_text"] = original
            rec["notes"] = ""
            if has_merged:
                # Merged cells indicate ambiguous content
                rec["status"] = "needs-structuring"
                rec["context_grouping"] = common.fold_ws(str(row[0])) if row else ""
                rec["notes"] = "merged-cells"
                warnings.append({"code": "merged-cells", "detail": f"table={ti},row={ri}"})
            elif not any(common.fold_ws(str(c)) for c in row):
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
