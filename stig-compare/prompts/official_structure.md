# Official Structure Prompt (annotate the official file's columns)

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

One record from `official_structure_requests.jsonl`:

- `structure_id` (string) — echo back unchanged.
- `sheet_or_section` (string) — which sheet/section of the official file
  this request covers.
- `headers` (array of strings) — the full header row, verbatim.
- `sample_rows` (array of arrays) — up to the first 15 data rows, all
  columns verbatim.
- `row_count` (int) — total data rows in this sheet/section.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "structure_id": "OS-0",
  "display_id_column": "Rule ID",
  "column_roles": {"Rule ID": "id", "Title": "title", "Notes": "other"},
  "notes": ""
}
```

## Decision guide

- This pass is ANNOTATION ONLY. Nothing you answer here drops, filters, or
  reduces any official row — every column of every row travels to matching
  and comparison verbatim regardless. Your annotations help the report and
  later passes label columns.
- `display_id_column`: the header of the column that holds the official
  rule's human-facing identifier (e.g. a V-number or STIG ID column). It
  must be copied verbatim from `headers`. Use `null` when no column is
  clearly an identifier — `null` is always acceptable and preferred over a
  guess.
- `column_roles`: assign EVERY header in `headers` exactly one role from:
  `id`, `title`, `severity`, `check`, `fix`, `expected`, `other`. When a
  column does not clearly fit a specific role, use `other` — that is a
  normal answer, not a failure.
- `notes` is the only free-text field: anything a human should know about
  this sheet's structure (e.g. "two header-like rows"). Use `""` when
  there is nothing to note.
- Include every key in every response.
