# Brief: match adjudication — the binding match decision

You are a subagent in the stig-compare skill. Your dispatch names the run
directory, ONE record (its line in `runs/<ts>/proposed.jsonl`), the nominated
official rows (their lines in `runs/<ts>/official_rows.jsonl`), and whether
this is a `sweep_round`. Read the COMPLETE record and the COMPLETE nominated
rows — every cell, both sides.

## Strict rules
- Use ONLY what you read from the named files. Adjudicate ONLY among the
  nominated rows in your dispatch — no other ids exist for you.
- **Your decision is FINAL and binding — nothing downstream re-scores or
  overrides it. Do not lean on a safety net.**
- **`none` and `ambiguous` are preferred over a forced `match`.** Similar
  severity alone is NEVER sufficient; a shared topic without a substantive
  requirement connection is not a match.
- Both quotes in every selection must be non-empty and VERBATIM
  (character-for-character from the JSON-decoded cells; continuation cells
  count). `row_quote` is the record fragment that ties THIS record to THIS
  official row; `official_quote` must be discriminating — text that
  distinguishes this row from its neighbors, not boilerplate.
- Every key below appears in every shard, even when inapplicable
  (`"selections": []` for `none`) — a missing key invalidates the unit.
- `basis` is your own words (display-only), not a quote.
- Write the shard with the Write tool as a single line of compact JSON.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose, no cell content.

## Task

Decide what this record actually addresses:

- `match` — multi-select: one `selections` entry per official row this record
  genuinely addresses. A record covering several DIFFERENT requirements is a
  multi-match (that is normal), not ambiguous. Selections are individually
  binding statements, not ranked alternatives.
- `none` — the record addresses none of the nominated rows.
- `ambiguous` — two or more nominated rows are INDISTINGUISHABLE alternatives
  for the SAME requirement and the record's text cannot separate them. List
  ≥2 ids in `ambiguous_official_row_ids`.

Write `runs/<ts>/matches/<record_id>.json` — a single line:

```
{"record_id": "...",
 "decision": "match" | "none" | "ambiguous",
 "selections": [{"official_row_id": "...", "row_quote": "<verbatim>", "official_quote": "<verbatim>"}, ...],
 "ambiguous_official_row_ids": [...],
 "basis": "<your own words>",
 "sweep_round": true|false}
```

`sweep_round` echoes your dispatch. Counts:
`{"selections": N}`.
