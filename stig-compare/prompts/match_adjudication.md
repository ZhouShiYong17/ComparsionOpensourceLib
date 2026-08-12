# Match Adjudication Prompt (binding match decision)

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- When the request carries `retry: true` or `sweep_round: true`, echo the
  same key(s) with value `true` in your response — a response missing a
  required echo is rejected mechanically.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `adjudication_requests.jsonl`:

- `record_id` (string) — echo back unchanged.
- `record` (object) — the COMPLETE company record: verbatim cells,
  continuation cells, header row, narrative, provenance, canonical-field
  aids.
- `nominated_rows` (array) — every official row nominated for this record
  by the scoping pass, each COMPLETE (all columns verbatim). These are the
  rows you adjudicate among.
- `sweep_round` (bool) — `true` when these nominations came from the
  reverse-sweep pass; echo it back.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "record_id": "...",
  "decision": "match | none | ambiguous",
  "selections": [
    {"official_row_id": "...", "row_quote": "...", "official_quote": "..."}
  ],
  "ambiguous_official_row_ids": ["...", "..."],
  "basis": "..."
}
```

Include every key in every response, even when it does not apply to your
decision (e.g. `selections: []` for `"none"`). A missing key invalidates
the whole response.

## Decision guide

- Your decision is FINAL: no code re-scores, overrides, or second-guesses
  it. Do not lean on a safety net — there is none. Decide only what the
  full evidence supports.
- Adjudicate ONLY among `nominated_rows`. Never select an
  `official_row_id` that is not one of them.
- `"match"`: one OR MORE nominated rows are genuinely the same requirement
  as this record. Emit one entry in `selections` per matched row — a
  record legitimately covering three official rows yields three
  selections. Do not add a selection you are unsure of: selections are
  individually binding, not ranked alternatives.
- For every selection: `row_quote` must be copied verbatim from the
  record's cells (continuation-row cells count) and must be the specific
  fragment that ties THIS record to THIS official row; `official_quote`
  must be copied verbatim from that official row's cell values and be the
  discriminating evidence, not filler. Both non-empty.
- `"ambiguous"`: two or more nominated rows plausibly fit and the record's
  text does not let you discriminate between them. List at least two
  `official_row_id` values in `ambiguous_official_row_ids`. Ambiguous
  means "indistinguishable alternatives for the SAME requirement" — a
  record that genuinely covers several DIFFERENT requirements is a
  multi-match, not ambiguous.
- `"none"`: no nominated row fits. `"none"` and `"ambiguous"` are always
  acceptable and preferred over a forced, uncertain `"match"`.
- Similar severity alone is NEVER sufficient basis for a match.
- `basis` is a short phrase, in your own words, naming what discriminated
  this decision. It is not a quote.
