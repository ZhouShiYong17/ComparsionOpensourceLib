# Structuring Prompt

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

One record from `structuring_requests.jsonl`:

- `row_id` (string) — identifies this row. Echo it back unchanged.
- `original_company_text` (string) — the raw, messy text pulled from the
  company's document for this row. This is the ONLY source of truth for
  every field you produce.
- `context_grouping` (string) — already extracted separately; not yours to
  recover, provided for context only.
- `instructions_file` (string) — path to this file.

## Task

Split `original_company_text` into the four-and-one structured fields below,
filling in only what the row's own text actually supports.

## Output schema

```json
{
  "row_id": "...",
  "stig_description": "",
  "stig_objective_or_requirement": "",
  "stig_command_or_value": "",
  "company_approved_setting_or_expected_value": "",
  "observed_value_or_evidence": ""
}
```

## Decision guide

- `row_id` must exactly echo the request's `row_id`.
- Every non-empty field value MUST be an exact, contiguous, VERBATIM
  substring of `original_company_text` — copy-paste, never paraphrase,
  summarize, reorder, translate, or add words. Only whitespace differences
  are tolerated; wording must match exactly.
- If `original_company_text` contains no text that supports a given field,
  set that field to `""`. Do not guess, infer, or fabricate a value to
  avoid leaving a field empty — an empty field is always an acceptable,
  correct answer.
- Do not stitch together multiple non-adjacent fragments into one field;
  pick the single best verbatim span for each field.
- Include all five fields in every response, even when several are `""`.
