# Brief: official structuring — column annotation and verbatim index

You are a subagent in the stig-compare skill. Your dispatch block names the run
directory, the mode (A or B), and the exact lines of
`runs/<ts>/official_rows.jsonl` that are yours. Each line of that file is one
official STIG row: `{"official_row_id", "sheet_or_section", "row_number",
"headers", "cells", "provenance"}` — cells are verbatim and ATOMIC (a comma or
newline inside a cell is content, never a boundary).

## Strict rules
- Use ONLY what you read from the files named in your dispatch. No outside
  knowledge of STIGs, products, or "usual" column layouts. Never invent, infer,
  or complete missing text.
- Quotes and index text must be VERBATIM — character-for-character copies of
  the JSON-decoded cell content. Paraphrase, summary, and truncation are
  forbidden in Mode B.
- `null` / `other` are normal answers and beat a guess.
- Write shards with the Write tool, compact JSON, one object per line, exact
  field names and enum spellings below.
- Your final message must be ONLY compact JSON:
  `{"unit_id": "...", "status": "ok"|"failed", "counts": {...}}` plus
  `"errors": [...]` when failed. No prose, no row content.

## Mode A — structure annotation (one unit per sheet/section)

Read the first ~15 data lines of your sheet's range (plus the `headers` array)
and decide what each column IS. This is ANNOTATION ONLY — nothing you answer
here drops, filters, or reduces any official row; every row travels onward
complete regardless.

Write `runs/<ts>/structure/<sheet-slug>.json` — a single line:

```
{"sheet_or_section": "...",
 "display_id_column": "<verbatim header>" | null,
 "column_roles": {"<verbatim header or col<i>>": "id|title|severity|check|fix|expected|other", ...},
 "notes": ""}
```

- `display_id_column`: the verbatim header of the column holding the
  human-facing rule identifier (V-number, SV-number, STIG ID, Rule ID). Use
  `null` when no column is clearly an identifier — null beats a guess.
- `column_roles`: EVERY header gets exactly one role. `other` is a normal
  answer. `title` = short rule name; `check`/`fix` = procedure text;
  `expected` = required value/setting.
- `notes` is the only free-text field (`""` when nothing to say).
- Counts: `{"columns": N}`.

## Mode B — verbatim index (one unit per ≤40-row chunk)

Your dispatch supplies the sheet's Mode-A structure shard content and your
chunk's line range. For each row in the range, write one index line copying the
identity-bearing text VERBATIM.

Write `runs/<ts>/index/<sheet-slug>-r<first_row_number>.jsonl` — one line per
row:

```
{"official_row_id": "...", "display_id": "<verbatim cell>" | null,
 "title": "<verbatim cell(s)>", "requirement": "<verbatim cell(s)>"}
```

- `display_id` comes from the Mode-A `display_id_column` (null when that is
  null or the cell is empty).
- `title` = the full verbatim content of the `title`-role column.
- `requirement` = the full verbatim content of the column(s) that state WHAT is
  required — the requirement / objective / discussion / `expected`-role
  column(s) — joined with a single `\n`, each cell intact.
- **Exclude step-by-step verification and remediation procedures** (`check`,
  `fix`) from the index. They are the bulk of an official STIG's bytes and they
  describe HOW to verify, not what is required; every one of them is still read
  in full later, when complete rows are adjudicated and compared. Including
  them here can triple or quadruple the index that every scoping agent must
  read, which costs recall as much as tokens.
- Fall back to the check/fix text ONLY when no other column states the
  requirement — a rule whose entire substance lives in its check procedure must
  still be findable.
- NEVER paraphrase, summarize, or truncate what you do include: the index
  compacts by DROPPING procedure columns, never by rewriting. A detail lost to
  a rewrite causes a silent mismatch no later pass can recover.
- If Mode A found no `title` and no requirement-bearing column at all, copy ALL
  cells verbatim into `requirement` (cells only, `\n`-joined — do not emit
  `header: cell` pairs).
- Every row in your range gets exactly one line — no skips, no additions.
- Counts: `{"rows_indexed": N}`.
