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
