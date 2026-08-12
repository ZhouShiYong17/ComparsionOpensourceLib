# Validation Prompt (independent second judgment on one finding)

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

One record from `validation_requests.jsonl`:

- `validation_id`, `finding_id` (strings) — echo `validation_id` and
  `finding_id` back unchanged.
- `kind` — `"comparison"` (one record vs its matched official rows) or
  `"rollup"` (several records vs one official row).
- `record` (object) or `records` (array, rollup findings) — the COMPLETE
  company record(s): verbatim cells, continuation cells, header row,
  narrative, provenance, canonical-field aids.
- `official_rows` (array) — the COMPLETE official row(s) of this finding.
- `claimed` (object) — the first pass's ENTIRE output for this finding:
  verdict, change analysis, field alignment, match rationale, reasoning,
  confidence, quotes, and the adjudication's match basis. This is the
  CLAIM under review, not evidence.

## Required protocol — in this order

1. **Read the evidence first.** Study `record`(s) and `official_rows` ONLY
   — do not read `claimed` yet. Reach your own conclusion about the match
   and the verdict, and fix it as `independent_verdict`. This field must
   reflect the conclusion you formed BEFORE consulting the claim.
2. **Then read `claimed`.** Compare it against your independent
   conclusion. Check specifically:
   - Is the match itself right — do the official rows actually govern
     this record? Should other listed rows have decided the verdict?
   - Do the cited quotes exist verbatim and mean what the claim says?
   - Does the field alignment miss, distort, or invent a correspondence?
   - Do the change-analysis tags and verdict follow from the evidence?
   - Does the reasoning contain leaps the texts do not support?
3. **Deliver the outcome.** Your job is to catch what the first pass got
   wrong, not to ratify it. Do not merely confirm.

## Output schema

```json
{
  "validation_id": "...",
  "finding_id": "...",
  "independent_verdict": "Compliant | Deviating | Incomplete | Ambiguous | Cannot Assess",
  "outcome": "upheld | refuted | revised | needs-human",
  "revised_verdict": null,
  "revised_change_analysis": null,
  "reason": "...",
  "evidence_quote": ""
}
```

## Decision guide

- `outcome: "upheld"` ONLY when your independent conclusion agrees with
  the claimed verdict AND you checked every question in step 2 and found
  nothing wrong. An uphold whose `independent_verdict` differs from the
  claimed verdict is mechanically rejected as self-contradictory.
- `outcome: "refuted"` when the claim is wrong and you can cite concrete
  evidence why — put the decisive verbatim fragment in `evidence_quote`
  (from the record's cells or the official rows' cell values) and the
  explanation in `reason`.
- `outcome: "revised"` when the claimed verdict is wrong but the evidence
  clearly supports a different one: set `revised_verdict` (required, same
  vocabulary) and optionally `revised_change_analysis` (tags from:
  omitted, contradicted, weakened, strengthened, materially-changed).
- `outcome: "needs-human"` when the evidence genuinely supports more than
  one reading, the match itself is doubtful in ways you cannot settle, or
  anything else a reviewer must weigh. Never guess.
- `evidence_quote` may be `""` only when no single fragment is decisive;
  when non-empty it must be verbatim from the supplied evidence.
- Include every key in every response (`revised_verdict` /
  `revised_change_analysis` are `null` unless `outcome` is `"revised"`).
