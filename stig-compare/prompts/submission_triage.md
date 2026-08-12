# Brief: submission triage — table classification and column annotation

You are a subagent in the stig-compare skill. Your dispatch names the run
directory and ONE table (or document section) of the company submission: where
to read it (`runs/<ts>/submission_dump.json` table index, or a raw-file line
range when ingest fell back to direct reading), its `header_row`,
`preceding_narrative`, and row count. Read up to ~15 sample rows yourself.
Cells are ATOMIC — commas/newlines inside a cell are content. When reading raw
CSV text, a quoted field containing commas or newlines is ONE cell.

## Strict rules
- Use ONLY what you read from the named files. No outside knowledge, no
  format assumptions from other companies' submissions. Never invent, infer,
  or complete.
- `uncertain` and `other` are normal answers. **Prefer `uncertain` over a
  wrong `irrelevant`** — `irrelevant` is the ONLY decision in this pass that
  excludes content from comparison, and an `uncertain` table is still fully
  processed, just flagged.
- Copy-only fields (`context_grouping`) must be VERBATIM; never compose or
  paraphrase them.
- Write your shard with the Write tool as a single line of compact JSON, exact
  field names and enum spellings below.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose, no cell content.

## Task

Write `runs/<ts>/triage/t<table_index>.json` — a single line:

```
{"table_index": N,
 "classification": "stig_relevant" | "irrelevant" | "uncertain",
 "irrelevant_reason": "instructions" | "general-info" | "toc" | "signoff" | "other" | null,
 "column_mapping": {"<0-based column index as string>": "<canonical field>", ...},
 "context_grouping": "<verbatim>" | "",
 "notes": ""}
```

- `irrelevant_reason` is non-null exactly when classification is `irrelevant`.
- `column_mapping` is annotation, not a gate — an unmapped column's content
  still travels with every record. Canonical fields (each maps to AT MOST one
  column): `stig_description`, `stig_objective_or_requirement`,
  `stig_command_or_value`, `company_approved_setting_or_expected_value`,
  `observed_value_or_evidence`, `company_compliance_claim`,
  `company_severity`, `remarks_or_justification`, `other`.
- Real-world header cheat-sheet (guidance, not a rule — judge the actual
  content): "Command to Verify" → `stig_command_or_value`; "Approved Setting" /
  "Company Agreed Setting" → `company_approved_setting_or_expected_value`;
  "Current Setting" / "Actual Value" / "Observed Value" / "Evidence" →
  `observed_value_or_evidence`; "Adopt Company Standards Deviation/Comply" or
  any comply/deviate column → `company_compliance_claim`; "Severity" →
  `company_severity`; "Remarks" / "Justification" → `remarks_or_justification`;
  "Description" / "Details" → `stig_description`; "STIG Requirement" /
  "Requirement" / "Objective" / "Control" / "Policy" →
  `stig_objective_or_requirement`; yes/no process columns and row-number
  columns → `other`.
- `context_grouping`: a grouping title copied VERBATIM from the preceding
  narrative, section heading, or header area (e.g. a component name the whole
  table falls under); `""` when nothing fits.
- Counts: `{"columns": N, "rows": N}`.
