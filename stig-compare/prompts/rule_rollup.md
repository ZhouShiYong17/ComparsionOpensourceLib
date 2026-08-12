# Rule Rollup Prompt (joint assessment of one official row across records)

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

One record from `rollup_requests.jsonl`:

- `rollup_id` (string) — echo back unchanged.
- `official_row` (object) — one COMPLETE official row (all columns
  verbatim) that more than one company record matched.
- `company_records` (array) — every matching company record, COMPLETE.
- `per_record_findings` (array) — each contributing record's comparison
  finding for this row, verbatim: `{record_id, verdict, change_analysis,
  reasoning, row_quote, official_quote}`.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "rollup_id": "...",
  "contributing_record_ids": ["CR-...", "CR-..."],
  "joint_verdict": "Compliant | Deviating | Incomplete | Ambiguous | Cannot Assess",
  "coverage_of_requirement": "fully-covered | partially-covered | conflicting",
  "reasoning": "...",
  "confidence": "High | Medium | Low",
  "human_review": false
}
```

## Decision guide

- The question: taken TOGETHER, do these company records satisfy this
  official row's requirement? A requirement split across several rows may
  be fully covered jointly even though each row alone looks partial — or
  the rows may conflict with each other.
- `contributing_record_ids` must echo exactly the `record_id` values of
  `company_records` (any order, no extras, no omissions).
- `coverage_of_requirement`: `fully-covered` when the records jointly
  address every part of the requirement; `partially-covered` when parts
  remain unaddressed; `conflicting` when the records disagree with each
  other about the same requirement.
- `joint_verdict` uses the same verdict vocabulary as the comparison pass,
  applied to the JOINT picture.
- You may disagree with the individual per-record verdicts — say so in
  `reasoning`. Your disagreement is surfaced as a warning for human
  review; it never overwrites the per-record findings.
- `human_review`: `true` whenever a human should inspect the joint
  picture (conflicting records, split coverage that is hard to call).
- Include every key in every response.
