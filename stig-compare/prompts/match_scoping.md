# Brief: match scoping — nominate candidate pairs (recall pass)

You are a subagent in the stig-compare skill. Your dispatch names the run
directory, a batch of ~8 record lines to Read from `runs/<ts>/proposed.jsonl`
(by line numbers), and the index file `runs/<ts>/index.jsonl` (Read it in
full — it carries every official row's verbatim display_id, title, and
requirement text).

## Strict rules
- Use ONLY what you read from the named files. Never invent ids — every
  `record_id` and `official_row_id` you emit must exist in the files you read.
- You are NOT deciding matches. Adjudication (a later, binding pass) sees the
  COMPLETE rows for every pair you nominate and filters freely. **A missed
  nomination is unrecoverable; an over-generous one is filtered later —
  prefer recall over precision.**
- Read the WHOLE record (all cells, continuation cells, narrative) and the
  WHOLE index entry — not just titles.
- Never nominate on severity alone or on a shared generic topic word alone
  ("password", "audit") — there must be a plausible substantive connection.
- Unbounded cardinality both ways: one record may nominate many official rows
  and vice versa. An EMPTY nomination list for a record is an acceptable,
  meaningful answer — it means you saw the whole index and found nothing
  plausible.
- Write your shard with the Write tool, compact JSON lines, exact field names
  below.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose.

## Task

For each record in your batch, ask: **"Given everything stated in this
company row — description, settings, evidence, remarks, narrative context —
which official requirements COULD it plausibly be addressing?"**

Write `runs/<ts>/nominations/b<batch_number>.jsonl` — one line per nomination:

```
{"record_id": "...", "official_row_id": "...", "note": "<short display-only phrase>"}
```

Records with zero nominations still need visibility: append one line
`{"record_id": "...", "official_row_id": null, "note": "no-candidates"}` for
each, so downstream accounting sees the record was scoped.

Counts: `{"records": N, "nominations": N, "no_candidates": N}`.
