# Comparison Prompt (verdict per matched official row)

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

One record from `comparison_requests.jsonl`:

- `comparison_id`, `record_id` (strings) — echo back unchanged.
- `record` (object) — the COMPLETE company record: verbatim cells,
  continuation cells, header row, narrative, provenance, canonical-field
  aids, `company_claim_reading`.
- `official_rows` (array) — EVERY official row this record was matched to,
  each COMPLETE (all columns verbatim). Together they form the requirement
  set this record is judged against.
- `match_basis` (object) — the adjudication pass's own quotes and basis
  for these matches (same-side context, not independent evidence).
- `sweep_origin_row_ids` (array) — which of the rows entered via the
  reverse sweep.
- `precedents` (array) — prior human-reviewer feedback recorded against
  these official rows, verbatim: `{feedback_id, official_row_id,
  classification, comment, prior_verdict}`. Precedents are context from
  past reviews of OTHER submissions — judge yourself whether each one
  applies to this record, and say so in `reasoning` when one does.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "comparison_id": "...",
  "record_id": "...",
  "per_rule": [
    {"official_row_id": "...",
     "match_rationale": "...",
     "field_alignment": [
       {"company_ref": "APPROVED SETTING", "official_column": "Expected Value",
        "company_quote": "...", "official_quote": "...",
        "relation": "identical | equivalent | differs | company-missing | official-missing"}
     ],
     "semantic_differences": "...",
     "change_analysis": ["omitted", "weakened"],
     "verdict": "Compliant | Deviating | Incomplete | Ambiguous | Cannot Assess",
     "confidence": "High | Medium | Low",
     "human_review": false,
     "row_quote": "...",
     "official_quote": "...",
     "reasoning": "..."}
  ],
  "claim_consistency": "consistent | contradicted | no-claim",
  "record_notes": ""
}
```

## Decision guide

- `per_rule` must contain EXACTLY ONE entry per row in `official_rows` —
  every row, no extras, no duplicates. When several rows together form the
  requirement, judge them JOINTLY (does the record satisfy the set?) but
  still report each row's own entry.
- `field_alignment`: walk the meaningful correspondences between the
  record's cells and the official row's columns. `company_ref` names the
  company side (a header text, or `cell<i>` when the column has no
  header); `official_column` names the official column. `company_quote` /
  `official_quote` are verbatim fragments from those cells. Use relation
  `company-missing` when the official side states something the record
  nowhere addresses (then `company_quote` may be `""`), and
  `official-missing` for company content with no official counterpart
  (then `official_quote` may be `""`). Cover every material
  correspondence and every material absence — not every trivial cell.
- `change_analysis` — zero or more tags, each used only when it concretely
  applies to how the company version relates to the official requirement:
  - `omitted` — required information/steps absent from the company row.
  - `contradicted` — the company row states the opposite.
  - `weakened` — the company version is less strict (longer timeout,
    fewer checks, narrower enforcement).
  - `strengthened` — the company version is more strict.
  - `materially-changed` — scope, subject, or meaning altered in a way
    the other tags don't capture.
- `verdict` — exactly one of:
  - `Compliant` — the record's evidence demonstrably satisfies the
    official requirement(s); present in the text, no real doubt.
  - `Deviating` — the record departs from the requirement: a declared
    deviation, or an approved/current setting that does not meet it.
  - `Incomplete` — the record addresses this requirement but required
    information or evidence is partially missing.
  - `Ambiguous` — the record's text genuinely supports conflicting
    readings and you cannot decide between them.
  - `Cannot Assess` — nothing in the record lets you evaluate this
    requirement. Never guess compliance from silence.
- `confidence` is YOUR calibrated confidence in this entry's verdict.
- `human_review`: set `true` whenever a human should look regardless of
  the verdict — conflicting evidence, unusual wording, a precedent that
  cuts against your reading, judgment calls a reviewer may weigh
  differently.
- `row_quote` / `official_quote` (headline quotes) must NEVER be empty:
  copy the most decisive fragment from the record's cells (continuation
  cells count) and from the official row's cell values. For
  `Cannot Assess`, quote the nearest text that fails to supply the needed
  evidence.
- `claim_consistency`: compare the record's OWN stated compliance stance
  against your verdicts — `consistent`, `contradicted` (e.g. the row
  claims compliance but you found it Deviating), or `no-claim` when the
  record states no stance.
- `match_rationale`, `semantic_differences`, and `reasoning` are your
  words (no verbatim requirement): why this row matches, what differs
  semantically, and how you reached the verdict. `record_notes` is for
  record-level remarks spanning all rules; `""` when nothing to note.
- Include every key in every response and in every `per_rule` entry.
