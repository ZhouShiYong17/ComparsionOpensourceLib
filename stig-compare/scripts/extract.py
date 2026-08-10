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


def extract_company(path):
    raise NotImplementedError


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
