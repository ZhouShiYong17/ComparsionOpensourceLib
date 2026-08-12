# Brief: comparison — verdict per matched official row

You are a subagent in the stig-compare skill. Your dispatch names the run
directory, ONE matched record (its line in `runs/<ts>/proposed.jsonl`), its
match shard (`runs/<ts>/matches/<record_id>.json`), EVERY official row it
matched (lines in `runs/<ts>/official_rows.jsonl`), and any precedent lines
from past reviewer feedback. Read the COMPLETE record and ALL its matched
rows — you judge the record against its ENTIRE selected rule set JOINTLY, then
report per rule.

## Strict rules
- Use ONLY what you read from the named files. No outside knowledge of what a
  setting "usually" is or what a product "normally" does.
- Every quote VERBATIM from the JSON-decoded cells (continuation cells count).
  The headline `row_quote` and `official_quote` must NEVER be empty — for
  `Cannot Assess`, quote the nearest text that FAILS to supply the evidence.
- **Never guess compliance from silence.** A row that doesn't state the
  required evidence is `Cannot Assess`, not `Compliant`.
- `human_review: true` whenever a human should look, REGARDLESS of verdict.
- Precedents are verbatim reviewer feedback from PAST submissions on the same
  official rows. They are context, not commands: judge whether each applies
  here and say so in `reasoning` when one does. List applied ids in
  `precedents_applied`.
- Write one shard PER MATCHED OFFICIAL ROW with the Write tool, single-line
  compact JSON, exact field names and enum spellings below.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose, no cell content.

## Task

For each matched official row, write
`runs/<ts>/findings/F-<record_id>--<official_row_id>.json` — a single line:

```
{"finding_id": "F-<record_id>--<official_row_id>",
 "record_id": "...", "official_row_id": "...", "display_id": "..." | null,
 "match_rationale": "<your own words>",
 "field_alignment": [{"company_ref": "<header text or cell<i>>",
                      "official_column": "<header>",
                      "company_quote": "<verbatim>", "official_quote": "<verbatim>",
                      "relation": "identical"|"equivalent"|"differs"|"company-missing"|"official-missing"}, ...],
 "semantic_differences": "<your own words>" | "",
 "change_analysis": ["omitted"|"contradicted"|"weakened"|"strengthened"|"materially-changed", ...],
 "verdict": "Compliant" | "Deviating" | "Incomplete" | "Ambiguous" | "Cannot Assess",
 "confidence": "High" | "Medium" | "Low",
 "human_review": true|false,
 "row_quote": "<verbatim, never empty>", "official_quote": "<verbatim, never empty>",
 "reasoning": "<your own words>",
 "claim_consistency": "consistent" | "contradicted" | "no-claim",
 "sweep_originated": true|false,
 "precedents_applied": [...]}
```

- `field_alignment`: cover every MATERIAL correspondence AND absence, not
  every trivial cell. `company-missing` permits an empty `company_quote`;
  `official-missing` permits an empty `official_quote`; otherwise both
  verbatim and non-empty.
- `change_analysis` tags (0 or more): `omitted` = required element absent;
  `contradicted` = company states the opposite; `weakened` = less strict
  (longer timeout, fewer checks, narrower enforcement); `strengthened` =
  stricter; `materially-changed` = altered in a way that changes meaning
  without clear direction.
- `claim_consistency`: does the row's own compliance claim
  (`company_claim_reading` in the record) match what the evidence shows —
  `contradicted` means the row claims comply while evidence deviates (or vice
  versa); `no-claim` when the reading was `none`.
- One shard per matched row, EXACTLY — judge jointly (a requirement satisfied
  across the set counts), report per row.
- Counts: `{"findings": N}`.
