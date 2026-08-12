# Sweep Prompt (one-round reverse recall pass)

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

One record from `sweep_requests.jsonl`:

- `sweep_id` (string) — echo back unchanged.
- `records` (array) — company records that matched nothing so far, each
  COMPLETE: verbatim cells, continuation cells, header row, narrative,
  provenance, canonical-field aids.
- `official_rows` (array) — one slice of the official rows not yet
  addressed by any match, each COMPLETE (all columns verbatim).

## Output schema

```json
{
  "sweep_id": "SW-B0-K1",
  "proposals": [{"record_id": "CR-1a2b3c4d", "official_row_id": "OR-9f8e7d6c"}]
}
```

## Decision guide

- Propose a (record, official row) pair ONLY when the record's content
  plausibly addresses that row's requirement. Your proposals are
  candidates, not matches — every proposal goes through the normal
  adjudication (with quotes and validation) afterwards, so a missed
  proposal here is unrecoverable but a weak proposal is filtered later.
  Prefer recall over precision, but never propose on severity or
  topic-word overlap alone.
- Read the WHOLE record and the WHOLE official row — every cell and the
  surrounding context, not just titles.
- A record may appear in multiple proposals; an official row may appear in
  multiple proposals.
- An empty `proposals` array is an acceptable answer.
- `record_id` / `official_row_id` values must come from THIS request.
- Include both keys in every response.
