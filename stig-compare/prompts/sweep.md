# Sweep Prompt (one-round recall pass)

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

One record from `sweep_requests.jsonl`:

- `sweep_id` (string) — echo back unchanged.
- `records` (array) — company records that matched nothing so far. Each
  has `record_id`, `context_grouping`, and the canonical data fields.
- `rules_index` (array) — official rules not yet addressed by any match.
  Each has `rule_id`, `title`, `expected_value`, `tech_tokens`.

## Output schema

```json
{
  "sweep_id": "S0",
  "proposals": [{"record_id": "CR-1a2b3c4d", "rule_id": "V-1004"}]
}
```

## Decision guide

- Propose a (record, rule) pair ONLY when the record's content plausibly
  addresses that rule's requirement. Your proposals are candidates, not matches
  — every proposal goes through the normal matching adjudication (with quotes
  and validation) afterwards, so a missed proposal here is unrecoverable but a
  weak proposal is filtered later. Prefer recall over precision, but never
  propose on severity or topic-word overlap alone.
- A record may appear in multiple proposals; a rule may appear in
  multiple proposals.
- An empty `proposals` array is an acceptable answer.
- Include both keys in every response.
