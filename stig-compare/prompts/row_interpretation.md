# Row Interpretation Prompt (Phase 2: additive row annotation)

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- When the request carries `retry: true`, echo `"retry": true` in your
  response — a response missing a required echo is rejected mechanically.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `interpretation_requests.jsonl`:

- `chunk_id` (string) — echo back unchanged.
- `table_index` (int), `context_grouping` (string), `header_row` (array),
  `preceding_narrative` (string).
- `column_mapping` (object) — the approved Phase-1 annotation: column index
  (string) -> canonical field | "other". A hint, not a gate.
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
        "company_claim_reading": "comply | deviation | unclear | none",
        "interpretation_note": ""}]},
    {"row_index": 2, "disposition": "separator", "separator_text": "..."}
  ]
}
```

## Decision guide

- Everything you extract here is an ADDITIVE aid: the complete verbatim row
  (all cells, continuation cells, headers, narrative) travels to matching,
  comparison, and validation regardless of what you put in `fields`. A
  sparse `fields` object is a normal answer — extract only what is clearly
  present.
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
  `{"row_index", "cell_index"}` in `field_provenance`. Skip empty cells
  and `other` columns (their cells still travel with the full row).
- Deviate from the column mapping ONLY when the row itself demands it
  (e.g. a value sitting in the wrong column) — provenance must still point
  at the actual cell the text came from, and the text must remain
  verbatim. Never merge text from two cells into one field.
- Splitting: when one row genuinely covers several distinct settings,
  emit several records with `sub_index` 0, 1, ... — each field value still
  a verbatim substring of a single cell of this row (or its continuation
  rows).
- `company_claim_reading`: what THIS row's own text states about the
  company's compliance stance. `comply` when the row states the company
  complies/adopts the requirement; `deviation` when it declares a
  deviation or non-adoption; `unclear` when the row addresses its stance
  but you cannot tell which; `none` when the row states no stance at all.
  NEVER infer a stance the row does not state — silence is `none`, not
  `comply`.
- `interpretation_note` is the ONLY free-text field: use it to note what a
  human reviewer should know (e.g. "the DEVIATION entry appears to apply
  only to the second setting"). It is display-only and never used as
  matching evidence. Use `""` when there is nothing to note.
- Include every key shown in the schema for each entry you emit.
