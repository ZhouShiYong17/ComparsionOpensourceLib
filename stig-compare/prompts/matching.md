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

- `row_id` (string) — identifies this row. Echo it back unchanged.
- `row` (object) — the full company row, including
  `original_company_text`, `context_grouping`, `stig_description`,
  `stig_objective_or_requirement`, `stig_command_or_value`,
  `company_approved_setting_or_expected_value`,
  `observed_value_or_evidence`, and `source_reference`.
- `candidates` (array) — the COMPLETE and ONLY set of official rules you
  may adjudicate among. Each candidate has `rule_id`, `title`, `severity`,
  `check_text`, `fix_text`, `expected_value`, and `_score` (a deterministic
  pre-ranking number, for information only — never evidence of a match).
- `instructions_file` (string) — path to this file.
- On a retry, the record may also include `retry: true` and
  `previous_errors` (why your last answer was rejected).

## Output schema

```json
{
  "row_id": "...",
  "decision": "match | none | ambiguous",
  "rule_id": "...",
  "ambiguous_rule_ids": ["...", "..."],
  "row_quote": "...",
  "rule_quote": "...",
  "basis": "..."
}
```

Include every key in every response, even when it does not apply to your
decision (e.g. `rule_id: ""` and `ambiguous_rule_ids: []` for `"none"`).
A missing key invalidates the whole response.

## Decision guide

- Adjudicate ONLY among the listed `candidates`. Never propose a rule_id
  that is not one of them.
- `"match"`: exactly one candidate is genuinely the same requirement as
  this row. Set `rule_id` to that candidate's `rule_id`.
- `"ambiguous"`: two or more candidates plausibly fit and the row's text
  does not let you discriminate between them. List at least two of their
  `rule_id` values in `ambiguous_rule_ids`.
- `"none"`: no candidate fits this row.
- `"none"` and `"ambiguous"` are always acceptable and are preferred over
  a forced, uncertain `"match"`.
- Similar `severity` alone (e.g. both "high"/"CAT I") is NEVER sufficient
  basis for a match — it must never be the deciding factor.
- `row_quote` must be copied verbatim from the row's text and must be the
  specific fragment that discriminates this candidate from the others —
  not generic or boilerplate text.
- `rule_quote` must be copied verbatim from the chosen candidate's
  `title`/`check_text`/`fix_text` and must likewise be the discriminating
  evidence, not filler.
- `basis` is a short phrase, in your own words, naming what discriminated
  this decision. It is not a quote.
