"""Extraction: official STIG source (CSV/JSON/XLSX). Lossless, zero mapping.

Every data row is preserved with ALL of its columns verbatim (positional
`cells` plus a `raw_record` header->value view), full provenance, and a
stable hashed `official_row_id` join key. No header synonyms, no canonical
field reduction, no severity folding — which column means what is decided by
the Claude official-structure pass downstream, never here. Unreadable
content becomes warnings, never silent drops. No document text in error
output.

Company-submission extraction is handled by skeleton.py (lossless dump) plus
the Claude-driven table-mapping/interpretation passes in pipeline.py.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import openpyxl

import common


def _rows_from_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _rows_from_xlsx_sheet(ws):
    return [["" if c.value is None else str(c.value) for c in row]
            for row in ws.iter_rows()]


def _raw_record(headers, cells):
    """Header->value convenience view. Positional `cells` stays the lossless
    source of truth; empty or duplicate headers get positional keys so no
    column is ever shadowed."""
    raw = {}
    for i, val in enumerate(cells):
        header = str(headers[i]) if i < len(headers) else ""
        key = header if common.fold_ws(header) else f"col{i}"
        if key in raw:
            key = f"{key}#col{i}"
        raw[key] = str(val)
    return raw


def _official_from_table(rows, source_file, locator_prefix, sheet_or_section):
    records, warnings = [], []
    if len(rows) < 2:
        warnings.append({"code": "empty-official-file",
                         "detail": f"{locator_prefix}: no data rows"})
        return records, warnings
    headers = [str(h) for h in rows[0]]
    for n, row in enumerate(rows[1:], start=2):
        cells = [str(c) for c in row]
        if not any(common.fold_ws(c) for c in cells):
            continue
        locator = f"{locator_prefix},row={n}"
        records.append({
            "official_row_id": common.official_row_id(
                Path(source_file).name, locator, cells),
            "display_id": None,
            "headers": headers,
            "cells": cells,
            "raw_record": _raw_record(headers, cells),
            "sheet_or_section": sheet_or_section,
            "row_number": n,
            "provenance": {"source_file": Path(source_file).name,
                           "locator": locator},
            "column_roles": None,
        })
    return records, warnings


def extract_official(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records, warnings = _official_from_table(
            _rows_from_csv(path), path, "csv", "csv")
        if not records and not warnings:
            warnings.append({"code": "empty-official-file",
                             "detail": "csv: no data rows"})
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        records, warnings = [], []
        for n, item in enumerate(data):
            headers = [str(k) for k in item.keys()]
            cells = [str(v) for v in item.values()]
            if not any(common.fold_ws(c) for c in cells):
                continue
            locator = f"json,index={n}"
            records.append({
                "official_row_id": common.official_row_id(
                    path.name, locator, cells),
                "display_id": None,
                "headers": headers,
                "cells": cells,
                "raw_record": {str(k): str(v) for k, v in item.items()},
                "sheet_or_section": "json",
                "row_number": n,
                "provenance": {"source_file": path.name, "locator": locator},
                "column_roles": None,
            })
        if not records:
            warnings.append({"code": "empty-official-file",
                             "detail": "json: empty"})
    elif suffix == ".xlsx":
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        records, warnings = [], []
        for ws in wb.worksheets:
            r, _w = _official_from_table(
                _rows_from_xlsx_sheet(ws), path,
                f"sheet={ws.title}", f"sheet={ws.title}")
            records.extend(r)
        if not records:
            warnings.append({"code": "empty-official-file",
                             "detail": "xlsx: no data rows in any sheet"})
    else:
        raise ValueError(f"unsupported official file type: {suffix}")

    return {"rows": records, "warnings": warnings}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    p = sub.add_parser("official")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        result = extract_official(args.file)
    except Exception as e:                        # no document text in errors
        print(f"extract: cannot read file: {type(e).__name__}", file=sys.stderr)
        return 2
    common.write_jsonl(args.out, result["rows"])
    Path(str(args.out) + ".warnings.json").write_text(
        json.dumps(result["warnings"], indent=1), encoding="utf-8")
    print(f"{args.kind}: {len(result['rows'])} rows, "
          f"{len(result['warnings'])} warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
