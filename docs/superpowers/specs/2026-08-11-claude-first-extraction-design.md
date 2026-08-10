# Claude-First Company Extraction — stig-compare Redesign

**Date:** 2026-08-11
**Status:** Approved in brainstorming; pending user review of this document
**Supersedes:** the extraction and structuring portions (§4 stages 2–3, company side of
§2/§3) of `2026-08-10-stig-comparison-skill-design.md`. Everything not restated here
(feedback loop, rules registry, review mode, skeptic isolation, confidentiality,
versioning) remains as designed there.
**Foundation:** `PROPOSAL.md` (STIG Comparison Using Only Two Files)

## 1. Problem

Real company submissions defeat the current deterministic company-side extraction:

- `extract.py` requires ≥3 exact header-synonym hits per table; real tables
  ("System Value/Parameter", "REPORTING yes/no", "ADOPT COMPANY STANDARDS
  DEVIATION/COMPLY", ...) match almost nothing, so whole tables fall to
  `needs-structuring`.
- Per-row structuring sees only the row's raw text — no table headers, no section
  headings — and must return contiguous verbatim substrings of the joined row. A bare
  "YES" under an "ENFORCING" header is unrecoverable in that model.
- Lexical candidate shortlisting then runs over those weak fields, so rows finish
  unmatched. Too many unmatched rows makes the report useless in practice.
- Submissions also contain non-STIG tables (Instructions, General Information,
  sign-off) that today just become unmapped-header noise.

Observed real formats (two of many variations):

1. Heading "JB.1.1 STIG HARDENING - SEVERITY HIGH"; columns: STIG Requirement /
   Description / Command to Verify / Approved Setting.
2. Heading "IM-1.1 Settings related to Policy or Standards"; columns: (row number) /
   System Value/Parameter / Description / Reporting yes-no / Enforcing yes-no / Adopt
   Company Standards deviation-comply / Company Agreed Setting-Command to Implement /
   Severity / Current Setting / Remarks-Justification.

## 2. Decisions locked during brainstorming

1. **Approach:** two-phase Claude canonicalization over a lossless Python skeleton
   dump (Approach A). Rejected: single-pass whole-document conversion (silent row
   loss at 200–1000 rows), flat-text free segmentation (loses cell provenance and
   stable IDs).
2. **Matching:** deterministic lexical shortlist per canonical record, Claude
   multi-select adjudication, plus one LLM sweep round over unmatched records ×
   unaddressed rules.
3. **Evidence discipline:** canonical field values must be verbatim (whitespace-folded)
   substrings of the specific cell named in `field_provenance`; Claude decides
   semantically which cell feeds which field. A separate `interpretation_note` field
   carries labeled interpretation and is never usable as matching evidence.
4. **Verdicts:** computed from value comparison, never from the company's own
   compliance claim. The claim is captured, displayed, and drives flags
   (`company-declared-deviation`, `claim-contradicted`) and `human_review_needed`.
5. **Scale target:** 10–40 tables, 200–1000 rows. Per-table requests with row
   chunking, in-session; no subagent fan-out required for extraction.

Priority order and core principle carry over unchanged: accuracy > traceability >
FP/FN reduction > reproducibility > maintainability > aesthetics; optimize for
defensible, not confident-looking. An unmatched row is acceptable; a wrong match is
not — but systematic unmatching of matchable rows is the failure this redesign fixes.

## 3. Canonical company record

One record per (table row × sub-record). PROPOSAL.md's four levels are preserved;
new fields absorb what real submissions carry.

| Field | Meaning |
|---|---|
| `record_id` | `short-hash(table_index, row_index, sub_index, raw_row_text)`; `sub_index` 0 unless a row was split |
| `row_id` | `short-hash(table_index, row_index, raw_row_text)` — kept for feedback/regression durability; shared by sub-records of one row |
| `context_grouping` | Table-level grouping from Phase 1: preceding heading + table title (e.g. "JB.1.1 STIG HARDENING - SEVERITY HIGH"), refined by in-table separator rows |
| `stig_description` | Level 1 |
| `stig_objective_or_requirement` | Level 2 |
| `stig_command_or_value` | Level 3 ("Command to Verify", "System Value/Parameter") |
| `company_approved_setting_or_expected_value` | Level 4 ("Approved Setting", "Company Agreed Setting/Command to Implement") |
| `observed_value_or_evidence` | "Current Setting" and similar |
| `company_compliance_claim` | New. Verbatim cell text plus Python-normalized `claim_normalized` enum: `comply` / `deviation` / `unknown` (synonym list, extendable via the rules registry's equivalent-terminology category) |
| `company_severity` | New. Row-level severity cell, verbatim (severity encoded in a heading stays in `context_grouping`) |
| `remarks_or_justification` | New. Verbatim |
| `extra_fields` | New. `{original_header: verbatim value}` for columns mapped to none of the above (e.g. "REPORTING yes/no") — nothing is dropped |
| `interpretation_note` | New. Claude's optional labeled interpretation (free text). Display-only: excluded from candidate scoring, matching quotes, and value comparison inputs |
| `field_provenance` | New. `{field_name: {row_index, cell_index}}` for every non-empty data field; `row_index` defaults to the record's own row and differs only for merged continuation records |
| `source_reference` | `{table_index, row_index, sub_index, sheet_or_section, table_title}` |
| `original_company_text` | Full raw row text (all cells joined), as today |
| `status` | `ok` / `separator` / `extraction-failed` (plus table-level `ignored-irrelevant`) |

**Evidence rule:** every non-empty data field value must be a verbatim
(whitespace-folded) substring of the cell named in `field_provenance`. This replaces
today's "contiguous substring of the whole joined row" rule. `interpretation_note`
is the single sanctioned non-verbatim field. Validation is mechanical in
`validate.py`; a failed value invalidates that response line, not the whole chunk.

Sub-records: when one Word row genuinely covers several settings, Claude may split it
into sub-records (`sub_index` 0..n). Each sub-record's values must still satisfy the
cell-verbatim rule against that same row's cells.

## 4. Pipeline

(D) = deterministic Python, (C) = Claude in-session via `prompts/` template with
schema-validated JSON, (S) = isolated subagent. Official-side extraction is
unchanged from the previous design (official files are genuinely structured).

1. **Skeleton dump (D)** — company file → `skeleton.json`: every table (index, header
   row, all rows/cells, merged-cell flags) and every narrative block (headings,
   paragraphs) with document position, so each table carries the narrative text
   immediately preceding it. Lossless; zero interpretation; no mappable gate; nothing
   dropped. XLSX: one "table" per sheet, sheet name as narrative context.
2. **Phase 1 — table triage + column mapping (C)** — one request per table containing:
   header row, preceding narrative text, first 5 data rows, header-synonym hints
   (the old synonym table, demoted from decider to hint). Response per table:
   - `classification`: `stig_relevant` / `irrelevant` / `uncertain`
   - `irrelevant_reason`: `instructions` / `general-info` / `toc` / `signoff` / `other`
   - `column_mapping`: column index → canonical field name | `extra_field` | `ignore`
   - `context_grouping`: verbatim text drawn from the narrative/table title
   Validation: indexes in range, enums legal, mapped fields are known field names.
   `uncertain` → processed as relevant and flagged `human_review_needed`. Irrelevant
   tables skip Phase 2; their row counts land in the `ignored-irrelevant-table`
   coverage bucket and are listed in the report's triage panel.
3. **Phase 2 — row canonicalization (C)** — per relevant table, chunks of ≤40 rows.
   Claude applies the Phase-1 mapping and handles per-row exceptions:
   - separator/subheading rows → `status: separator`, text refines `context_grouping`
     for subsequent rows in that table;
   - merged-cell continuation rows → `continuation_of: <row_index>`, merged into the
     previous record (field values may then cite cells from either row; provenance
     records which);
   - multi-setting rows → split into sub-records.
   **Count reconciliation (D):** every (table_index, row_index) in the skeleton must be
   accounted for as record / separator / continuation / empty. Missing rows are
   re-requested once; still missing → `extraction-failed`. This is the no-silent-row-
   loss guarantee.
4. **Normalize (D)** — unchanged (additive `normalized_*`, raw retained).
5. **Candidate shortlist (D)** — `candidates.py` unchanged in mechanism, fed clean
   canonical fields. `interpretation_note` and `extra_fields` are excluded from
   scoring. Deterministic tiers survive: T0 (official rule ID verbatim in row),
   T1 (unique technical signature).
6. **Match adjudication (C)** — per record with its top-K shortlist (K=5 default):
   Claude selects **0..N** rules (was exactly-one), each selection with verbatim
   quotes from both sides; `NONE` and `AMBIGUOUS` remain legal answers. Validation
   unchanged: selected IDs ∈ shortlist, quotes verbatim, two-strike retry protocol.
7. **Sweep (C)** — one round, after adjudication settles: unmatched records ×
   still-unaddressed official rules, batched against a compact rule index (rule_id,
   title, key technical tokens). Claude proposes candidate **pairs only**; proposals
   are injected as shortlist entries and go through stage-6 adjudication and
   validation like any other candidate — a sweep proposal can never become a match
   directly. Exactly one sweep round; then the matching loop closes.
8. **Deterministic comparison (D)** — as before (numbers, ranges, booleans,
   durations; missing observed value → Cannot Assess, no LLM override), plus:
   `claim_normalized` computation; `deviation` → `human_review_needed: true` and a
   `company-declared-deviation` warning on the finding; `comply` + computed
   Non-Compliant → `claim-contradicted` flag. The claim alone never produces a
   verdict: a deviation row with no observed value is still Cannot Assess.
9. **Semantic comparison (C)** — unchanged shape, runs per (record, rule) pair.
10. **Deterministic validation (D)** — as before, extended with the cell-verbatim
    rule, Phase-1/Phase-2 schemas, and count reconciliation.
11. **Skeptical validation (S)** — unchanged (semantic findings only, isolated
    subagent, evidence-only input).
12. **Coverage (D)** — see §6.
13. **Report (D)** — see §7.

### Orchestration

The request/response JSONL + `resolve`/`finalize` pattern is retained exactly:
fingerprinted response lines, 2-round retry caps per stage, LLM output treated as
untrusted input. New file pairs in the run directory: `table_mapping_requests/
responses.jsonl`, `canonicalize_requests/responses.jsonl`, `sweep_requests/
responses.jsonl` — joining the existing `matching_*` and `semantic_*`. SKILL.md's
compare mode gains: answer table-mapping requests → resolve → answer canonicalize
requests (loop, 2 rounds) → resolve → matching loop as today → sweep round →
adjudicate sweep-injected candidates → semantic loop → skeptic → finalize.

### Prompts

- `prompts/table_mapping.md` — new (Phase 1).
- `prompts/canonicalize.md` — new (Phase 2); replaces retired `prompts/structuring.md`.
- `prompts/matching.md` — updated for 0..N multi-select with per-selection quotes.
- `prompts/sweep.md` — new (pair proposal only; explicitly states proposals are
  candidates, not matches).
- `prompts/semantic_compare.md`, `prompts/validator.md` — unchanged.

All prompts keep the strict-rules header (evidence-only, no invention, NONE/AMBIGUOUS
always acceptable, observation vs interpretation separation, schema-valid JSON).

## 5. Matching and verdict semantics

- Findings keyed `(record_id, rule_id)`; a record matching three rules yields three
  findings, each independently compared, validated, and skeptic-checked (semantic
  ones). `finding_id = short-hash(record_id, rule_id, finding_type)`.
- Multiple records matching one rule: legal, flagged duplicate coverage (unchanged).
- Confidence classes unchanged (High: T0/T1 or T2+deterministic verdict; Medium:
  T2+semantic upheld; Low: narrow margin / weak quotes / skeptic undetermined).
  Sweep-originated matches cap at Medium: the sweep exists because lexical signal was
  weak, so High (which implies strong deterministic corroboration) is not available
  to them.
- `human_review_needed` gains triggers: table triage `uncertain`, company-declared
  deviation, claim-contradicted, any sweep-originated match.

## 6. Coverage

Every skeleton row lands in exactly one bucket:
`matched / ambiguous / unmatched / ignored-irrelevant-table / ignored-by-rule /
separator / extraction-failed`. A split row counts once (its sub-records aggregate:
any sub-record matched → matched; else best outcome). Buckets must sum to skeleton
row totals or the run fails loudly. Official side unchanged: addressed / unaddressed,
duplicate coverage flagged. Warning thresholds unchanged (any extraction failure
warns; >10% failed or ignored → red banner) with `ignored-irrelevant-table` excluded
from the red-banner ratio but always listed in the triage panel.

## 7. Report additions

- **Table triage panel** — every table: classification, reason, row count, mapped
  columns. A wrongly-ignored table is one glance away.
- Per-finding: company claim vs computed verdict; `claim-contradicted` and
  `company-declared-deviation` badges; sweep-originated matches labeled with their
  adjudication evidence; `interpretation_note` rendered visibly as interpretation,
  styled apart from evidence.
- Everything else (self-contained HTML, warnings never collapsible, feedback export)
  unchanged.

## 8. Testing

New/updated, on top of the existing suite:

- Fixtures replicating both observed real formats (§1) plus an Instructions table, a
  General Information table, and a mixed document containing all four.
- Count-reconciliation: no silent row loss through Phase 2 (missing rows retried then
  extraction-failed; totals always balance).
- Cell-verbatim validation: paraphrased/invented values rejected; whitespace folding
  tolerated; sub-record values checked against the parent row's cells.
- Split/merge/separator handling; continuation-row provenance.
- Multi-match: coverage arithmetic, duplicate flagging, per-pair findings, dedup.
- Sweep: single-round cap; proposals must pass adjudication; confidence capped Medium.
- Claim normalization and claim-contradiction flags; deviation-without-evidence still
  Cannot Assess.
- LLM behavior remains tested by contract (schemas + mechanical guards), never by
  pretending to unit-test the model.

## 9. Migration

- Retired: `prompts/structuring.md`, `needs-structuring` status, company-side
  header-synonym mapping as decider (kept as Phase-1 hints), the ≥3-columns gate.
- `extract.py` company side becomes the skeleton dump; official side untouched.
- Existing regression cases: matching/comparison-stage cases survive; structuring-
  stage cases are marked `retired` (not deleted — audit trail).
- Feedback mode and Review mode: unchanged.
- `VERSIONS.json`: extraction and pipeline versions bump; prompt hashes updated; old
  reports remain attributable to old versions.

## 10. Limitations and risks

- **Phase-1 misclassification:** a STIG-relevant table marked irrelevant would drop
  all its rows from comparison. Mitigations: `uncertain` processed-and-flagged rather
  than skipped, triage panel lists every table with row counts, ignored rows counted
  in coverage. Not eliminable.
- **Column-mapping errors:** a wrong mapping mislabels a whole table's fields.
  Mitigations: per-row Phase-2 deviation is allowed; cell-verbatim validation bounds
  damage to mislabeling (never invention); feedback loop can correct via rules.
- **Sweep cost/recall trade:** one round only; rows still unmatched after the sweep
  are honestly reported unmatched with the shortlist shown.
- **Interpretation leakage:** guarded by excluding `interpretation_note` from scoring
  and quotes mechanically, not by prompt discipline alone.
- Extraction ceiling (scanned/image tables), semantic-verdict fallibility, regression
  scope, single-machine trust: unchanged from the previous design.
