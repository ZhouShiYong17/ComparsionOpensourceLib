# Matching Prompt

STRICT RULES — apply to every response:
- Use ONLY the evidence supplied in the request. No outside knowledge.
- Never invent, infer, or complete missing information.
- Never force a match or a verdict you are not certain of. "none",
  "ambiguous", and "cannot-determine" are always acceptable answers.
- Every quote you return must be copied VERBATIM from the supplied text.
  Quotes are checked mechanically; an altered quote invalidates the response.
- Distinguish observation (what the texts say) from interpretation
  (what you conclude). Put conclusions only in the fields meant for them.
- Output MUST be a single JSON object matching the schema below exactly.

## Input

One record from `matching_requests.jsonl`:

- `record_id` (string) — identifies this record. Echo it back unchanged.
- `record` (object) — the full company record, including the canonical
  data fields, `original_company_text`, `context_grouping`, and
  `source_reference`.
- `candidates` (array) — the COMPLETE and ONLY set of official rules you
  may adjudicate among. Each candidate has `rule_id`, `title`, `severity`,
  `check_text`, `fix_text`, `expected_value`, and `_score` (a deterministic
  pre-ranking number, for information only — never evidence of a match).
  On a sweep round, `sweep_round: true` is present and candidates include
  proposals with `_score` 0.
- `instructions_file` (string) — path to this file.
- On a retry, the record may also include `retry: true` and
  `previous_errors` (why your last answer was rejected).

## Output schema

```json
{
  "record_id": "...",
  "decision": "match | none | ambiguous",
  "selections": [
    {"rule_id": "...", "row_quote": "...", "rule_quote": "..."}
  ],
  "ambiguous_rule_ids": ["...", "..."],
  "basis": "..."
}
```

Include every key in every response, even when it does not apply to your
decision (e.g. `selections: []` for `"none"`). A missing key invalidates
the whole response.

## Decision guide

- Adjudicate ONLY among the listed `candidates`. Never propose a rule_id
  that is not one of them.
- `"match"`: one OR MORE candidates are genuinely the same requirement as
  this record. Emit one entry in `selections` per matched candidate — a
  record legitimately covering three rules yields three selections. Do
  not add a selection you are unsure of: selections are individually
  binding, not ranked alternatives.
- For every selection: `row_quote` must be copied verbatim from the
  record's text and must be the specific fragment that ties THIS record
  to THIS candidate; `rule_quote` must be copied verbatim from that
  candidate's `title`/`check_text`/`fix_text` and be the discriminating
  evidence, not filler. Both non-empty.
- `"ambiguous"`: two or more candidates plausibly fit and the record's
  text does not let you discriminate between them. List at least two
  `rule_id` values in `ambiguous_rule_ids`. Ambiguous means
  "indistinguishable alternatives for the SAME requirement" — a record
  that genuinely covers several DIFFERENT requirements is a multi-match,
  not ambiguous.
- `"none"`: no candidate fits. `"none"` and `"ambiguous"` are always
  acceptable and preferred over a forced, uncertain `"match"`.
- Similar `severity` alone is NEVER sufficient basis for a match.
- `basis` is a short phrase, in your own words, naming what discriminated
  this decision. It is not a quote.
