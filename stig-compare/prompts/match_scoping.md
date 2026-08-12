# Match Scoping Prompt (nominate candidate official rows)

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

One record from `scoping_requests.jsonl`:

- `scoping_id` (string) — echo back unchanged.
- `records` (array) — a batch of COMPLETE company records: verbatim cells,
  continuation cells, header row, surrounding narrative, provenance, and
  the additive canonical-field aids.
- `official_rows` (array) — one slice of the official corpus, each row
  COMPLETE: all columns verbatim (`headers`/`cells`/`raw_record`),
  sheet/section, row number, provenance. Other slices of the corpus are
  handled by separate requests — you only judge this slice.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "scoping_id": "SC-T3B0-K1",
  "nominations": [
    {"record_id": "CR-1a2b3c4d", "official_row_id": "OR-9f8e7d6c",
     "note": "same password-reuse parameter"}
  ]
}
```

## Decision guide

- For EACH record in `records`, nominate EVERY official row in this
  request's `official_rows` that might plausibly address the same
  requirement. You are NOT deciding matches here — a separate adjudication
  pass examines every nomination with full evidence and makes the binding
  decision. A missed nomination is unrecoverable; an over-generous one is
  filtered later. Prefer recall over precision.
- Read the WHOLE record — every cell, continuation cells, the narrative
  and grouping context — and the WHOLE official row, not just titles.
- Never nominate on severity alone or on a shared generic topic word
  alone; there must be a plausible substantive connection (same setting,
  parameter, command, control objective, or requirement subject).
- The number of nominations is unbounded: a record may nominate many rows,
  a row may be nominated by many records, and a record with no plausible
  row in this slice simply appears in no nominations. An empty
  `nominations` array is an acceptable answer for the whole request.
- `note` is a short phrase naming the connection; it is display-only.
- `record_id` / `official_row_id` values must come from THIS request.
- Include both keys in every response.
