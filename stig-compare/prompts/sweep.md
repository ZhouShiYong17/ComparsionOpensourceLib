# Brief: reverse sweep — one-round recall over the leftovers

You are a subagent in the stig-compare skill. Your dispatch names the run
directory, the still-unmatched records (records adjudicated `none` or
`ambiguous` — their lines in `runs/<ts>/proposed.jsonl`), a LINE RANGE of
`runs/<ts>/official_rows.jsonl` that is yours to read, and a skip-list of
already-addressed `official_row_id`s. Read your slice's COMPLETE rows (skip
the addressed ones) and the COMPLETE records.

## Strict rules
- Use ONLY what you read from the named files; every id you emit must exist
  there.
- Proposals are candidates, NOT matches — every proposal goes through normal
  adjudication (complete rows, verbatim quotes, binding decision). **A missed
  proposal is unrecoverable; a weak one is filtered later — prefer recall.**
  But never propose on severity alone or a shared generic topic word alone.
- Read the WHOLE record and the WHOLE official row, not just titles.
- Many-to-many allowed; an empty proposal list is an acceptable, meaningful
  answer.
- Write your shard with the Write tool, compact JSON lines, exactly two keys
  per line.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose.

## Task

This is the safety net for the index-based scoping pass: the one round where
unmatched records see COMPLETE unaddressed official rows. For each record ×
row pairing in your slice that could plausibly be a match, write one line to
`runs/<ts>/sweep_proposals/s<slice_number>.jsonl`:

```
{"record_id": "...", "official_row_id": "..."}
```

Counts: `{"records": N, "rows_read": N, "proposals": N}`.
