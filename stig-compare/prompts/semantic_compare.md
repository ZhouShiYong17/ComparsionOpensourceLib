# Semantic Compare Prompt

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

One record from `semantic_requests.jsonl`:

- `row_id` (string) — echo back unchanged.
- `rule_id` (string) — echo back unchanged.
- `row` (object) — the full company row already matched to this rule,
  including `original_company_text`, the structured fields, and
  `observed_value_or_evidence`.
- `rule` (object) — the full official rule: `rule_id`, `title`,
  `severity`, `check_text`, `fix_text`, `expected_value`.
- `instructions_file` (string) — path to this file.
- On a retry, the record may also include `retry: true` and
  `previous_errors`.

## Output schema

```json
{
  "row_id": "...",
  "rule_id": "...",
  "finding_type": "equivalent | stronger | weaker | changed-scope | contradictory | cannot-determine",
  "verdict": "Compliant | Non-Compliant | Cannot Assess",
  "row_quote": "...",
  "rule_quote": "...",
  "interpretation": "..."
}
```

`row_id` and `rule_id` must exactly echo the request's values.

## Decision guide

- `verdict: "Compliant"` ONLY when the row's evidence demonstrably
  satisfies the official `expected_value`/`check_text` — the evidence must
  actually be present in the row's text and leave no real doubt.
- If the row's evidence is missing, vague, or does not directly address
  what the rule requires, use `verdict: "Cannot Assess"`. Never guess
  compliance from silence or ambiguity.
- If the row's evidence directly contradicts what the rule requires, use
  `finding_type: "contradictory"`.
- `finding_type` must be exactly one of: `equivalent`, `stronger`,
  `weaker`, `changed-scope`, `contradictory`, `cannot-determine` — pick
  the one word that best describes how the row's requirement compares to
  the rule's requirement.
- `row_quote` must be copied verbatim from `row`'s text; `rule_quote` must
  be copied verbatim from `rule`'s `title`/`check_text`/`fix_text`. Both
  are observation only — no reasoning inside a quote.
- `row_quote` and `rule_quote` must NEVER be empty, in every response you
  send, with no exception for `"Cannot Assess"` or `"cannot-determine"`.
  If the row's evidence is missing or unclear, still quote the nearest
  relevant fragment — e.g. the row field text that fails to supply the
  needed evidence, and the rule's `expected_value`/`check_text` fragment
  it fails to satisfy. An empty quote is rejected unconditionally; `""`
  is never a valid answer here (unlike the structuring prompt's fields).
- `interpretation` is the ONLY field for your reasoning and conclusions.
  Keep `row_quote`/`rule_quote` limited to what the texts literally say.
