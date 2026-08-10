# Table Mapping Prompt (Phase 1: triage + column mapping)

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

One record from `table_mapping_requests.jsonl`:

- `table_index` (int) — echo back unchanged.
- `sheet_or_section` (string), `preceding_narrative` (string) — the heading
  and paragraph text that appeared immediately before this table in the
  document.
- `header_row` (array of strings) — the table's first row.
- `sample_rows` (array of arrays) — up to the first 5 data rows.
- `row_count` (int) — total data rows in the table.
- `header_hints` (object) — canonical field -> known header synonyms.
  Hints only; your semantic judgment of the actual headers wins.
- On a retry: `retry: true` and `previous_errors`.

## Output schema

```json
{
  "table_index": 1,
  "classification": "stig_relevant | irrelevant | uncertain",
  "irrelevant_reason": "instructions | general-info | toc | signoff | other",
  "column_mapping": {"0": "stig_objective_or_requirement", "1": "ignore"},
  "context_grouping": "..."
}
```

## Decision guide

- `classification`: `stig_relevant` when the table's rows each describe a
  security setting, requirement, parameter, or hardening control.
  `irrelevant` for instructions, general information, table-of-contents,
  sign-off/approval, or revision-history tables — set `irrelevant_reason`.
  `uncertain` when you genuinely cannot tell; uncertain tables ARE
  processed, then flagged for human review — prefer `uncertain` over a
  wrong `irrelevant`, because `irrelevant` removes every row from
  comparison.
- `column_mapping` keys are column indexes as strings ("0"-based). Values
  must be one of: `stig_description`, `stig_objective_or_requirement`,
  `stig_command_or_value`, `company_approved_setting_or_expected_value`,
  `observed_value_or_evidence`, `company_compliance_claim`,
  `company_severity`, `remarks_or_justification`, `extra_field`, `ignore`.
- Guidance for real-world headers: "Command to Verify" / "System
  Value/Parameter" -> `stig_command_or_value`; "Approved Setting" /
  "Company Agreed Setting/Command to Implement" ->
  `company_approved_setting_or_expected_value`; "Current Setting" /
  "Actual Value" -> `observed_value_or_evidence`; "Adopt Company Standards
  Deviation/Comply" -> `company_compliance_claim`; "Severity" ->
  `company_severity`; "Remarks/Justification" ->
  `remarks_or_justification`; yes/no process columns like "Reporting" or
  "Enforcing" -> `extra_field`; row-number columns -> `ignore`.
- Map each canonical field to AT MOST one column. Unmappable but
  informative columns -> `extra_field` (nothing is dropped). For
  `irrelevant` tables, `column_mapping` may be `{}`.
- `context_grouping`: the grouping title for this table, copied VERBATIM
  from `preceding_narrative`, `sheet_or_section`, or the header row —
  e.g. "JB.1.1 STIG HARDEING- SEVERITY HIGH". Use `""` if nothing fits.
  Never compose or paraphrase a title.
- Include every key in every response.
