# STIG Comparison Skill — Design

**Date:** 2026-08-10
**Status:** Approved in brainstorming; pending user review of this document
**Foundation:** `PROPOSAL.md` (STIG Comparison Using Only Two Files)

## 1. Purpose and scope

A Claude Code Skill (`stig-compare`) that compares a company STIG submission against the
official STIG rule set using only two user-selected files, and produces a polished,
self-contained HTML report designed for human verification.

Decisions locked during brainstorming:

- **Comparison model:** asymmetric compliance check per `PROPOSAL.md`. One file is the
  official STIG baseline (CSV, JSON, or XLSX); the other is the company submission
  (DOCX or XLSX). "Excel or Word" means format flexibility on both inputs — this is
  not a generic version-diff tool.
- **Runtime:** Python 3 with `openpyxl` and `python-docx` available in the internal
  Claude Code environment. No network access of any kind.
- **Rule approval:** in-Skill review command gated by the regression suite plus explicit
  human approval. Git history is the audit trail.
- **Architecture:** deterministic-core pipeline with narrow, verifiable Claude passes
  (Approach A), with the skeptical validator isolated in a subagent.

Priority order (from the brief): accuracy > traceability > false-positive/false-negative
reduction > reproducibility > maintainability > UI aesthetics.

Core principle: **never optimize for making the comparison look confident; optimize for
making it defensible.** An unmatched row is acceptable; a wrong match is not.

## 2. Package layout

```
stig-compare/
  SKILL.md                  # trigger, orchestration workflow, modes
  scripts/
    ingest.py               # file-type detection; parse official + company files
    extract.py              # -> official_rules.jsonl / company_rows.jsonl with provenance
    normalize.py            # reversible normalization; raw always preserved
    candidates.py           # lexical top-K candidate generation per company row
    compare_values.py       # deterministic value parsing + verdicts
    validate.py             # quote existence, ID membership, dedup, contradiction, schemas
    coverage.py             # coverage arithmetic over item IDs
    report.py               # self-contained HTML renderer
    feedback.py             # ingest feedback JSON; draft candidate rules; snapshot regression cases
    rules.py                # registry load/validate; scope precedence; conflict handling
    regression.py           # regression suite runner
  prompts/
    structuring.md          # column mapping / 4-level structuring (strict)
    matching.md             # candidate adjudication
    semantic_compare.md     # semantic verdicts
    validator.md            # skeptical disproof pass
  rules/
    registry.json           # active rules (versioned)
    candidates/             # candidate rules awaiting review
  feedback/                 # ingested feedback records
  tests/
    fixtures/               # synthetic docx/xlsx/csv built by script
    regression/             # cases distilled from feedback
    test_*.py
  runs/                     # per-run artifacts (gitignored)
  VERSIONS.json             # component versions + prompt hashes
```

Skill modes (selected by how the user invokes it):

1. **Compare** (default): user supplies two file paths → full pipeline → HTML report.
2. **Ingest feedback**: user supplies a `feedback.json` exported from a report (or gives
   feedback conversationally) → stored feedback + regression case + optional candidate rule.
3. **Review pending rules**: maintainer reviews candidates → regression gate → approval.

## 3. Canonical data model

All pipeline state lives as JSON artifacts in `runs/<run-id>/`. Every stage reads the
previous artifact and writes its own; each stage is independently re-runnable and
inspectable.

**Official rule** (from CSV/JSON/XLSX): `rule_id` (from the file — e.g. V-/SV-number),
`title`, `severity`, `check_text`, `fix_text`, `expected_value` (when present), plus
provenance (`source_file`, sheet/row or record index) and `raw_record`.

**Company row** (from DOCX/XLSX): the proposal's structure, verbatim:

- `context_grouping`, `stig_description`, `stig_objective_or_requirement`,
  `stig_command_or_value`, `company_approved_setting_or_expected_value`
- `observed_value_or_evidence`, `source_reference` (table index, row index, sheet/page
  context), `original_company_text` (full raw row text)

**Stable IDs:** official rules keep their file-native ID. Company rows get
`row_id = short-hash(table_index, row_index, raw_row_text)` — the same file always
produces the same IDs, which makes feedback and regression cases durable. Findings get
`finding_id = short-hash(row_id, rule_id, finding_type)`.

**Evidence discipline:** every downstream claim may reference only these IDs plus
verbatim quotes. `validate.py` rejects any finding whose quotes do not literally exist
in the cited source (comparison after whitespace folding only).

## 4. Pipeline

Stages in order. (D) = deterministic Python, (C) = Claude in-session following a
`prompts/` template with schema-validated JSON output, (S) = isolated subagent.

1. **Ingest (D)** — detect formats, hash inputs (SHA-256), parse workbooks/documents.
   Unreadable sheets/tables/rows become `extraction-failed` items, never silent drops.
2. **Extract (D)** — produce `official_rules.jsonl` and `company_rows.jsonl` with full
   provenance. Column mapping for the official file and for well-labeled company tables
   is deterministic via a header-synonym table (extendable by rules).
3. **Structuring (C, only when needed)** — for company tables whose headers cannot be
   mapped deterministically, Claude assigns cell content to the 4-level structure.
   Constraint: every extracted field value must be a verbatim substring of the row's raw
   text — enforced by `validate.py`. Rows that fail go to `extraction-failed`.
4. **Normalize (D)** — whitespace, Unicode NFC, casing for comparison keys, numeric and
   date canonicalization. Raw values always retained; normalization is additive
   (`normalized_*` fields), never destructive.
5. **Candidate generation (D)** — for each company row, score all official rules with
   explainable features: IDF-weighted token overlap against title/check/fix text; shared
   technical tokens (setting names, commands, registry/file paths) at high weight;
   value overlap at low weight; severity agreement as tie-breaker only (never
   sufficient, per proposal §7). Keep top K (default 5) with per-feature score
   breakdown. Below the floor → tier T4 unmatched, Claude never consulted.
6. **Match adjudication (C)** — tiers:
   - **T0 exact ID:** company row contains an official ID → deterministic match.
   - **T1 unique technical signature:** an extracted setting/command/path appears in
     exactly one official rule's check/fix text → deterministic match.
   - **T2 shortlist adjudication:** Claude sees the row and its K candidates (with
     scores) and must answer one of {candidate ID, NONE, AMBIGUOUS} with verbatim
     quotes from both sides. Validator enforces: returned ID ∈ shortlist; quotes exist.
   - **T3 ambiguous:** two-plus plausible candidates, or top-2 scores within margin and
     Claude's quotes do not discriminate → reported ambiguous with all candidates shown.
   - **T4 unmatched.**
   Multiple company rows matching the same rule are allowed but flagged as duplicate
   coverage.
7. **Deterministic comparison (D)** — parse both sides as numbers, ranges
   ("9 or more" → ≥9), booleans, durations, enumerated states. Both parse → verdict
   (Compliant / Non-Compliant) computed by code. Also classifies formatting-only and
   normalized-equivalent differences. Hard rule (proposal §7): missing
   `observed_value_or_evidence` → **Cannot Assess**, deterministically; no Claude
   output can override this.
8. **Semantic comparison (C)** — only for pairs the deterministic stage could not
   decide. Typed findings: equivalent / stronger / weaker / changed-scope /
   contradictory / cannot-determine, each with quotes from both sides. Every finding
   separates `observation` (values, quotes, locations) from `interpretation` (the
   semantic claim and its basis).
9. **Deterministic validation (D)** — quote existence, ID membership, orphan
   references, dedup by (row, rule, type), contradiction detection, JSON-schema
   validation of all Claude outputs (one retry, then visible hard failure).
10. **Skeptical validation (S)** — per semantic finding, an isolated subagent receives
    the finding plus raw evidence only (never the first pass's reasoning) with a
    mandate to disprove. Outcomes: upheld / refuted / undetermined. Refuted →
    "disputed", displayed with both positions, never dropped. Undetermined → confidence
    capped at Low.
11. **Coverage + confidence (D)** — bucket arithmetic (see §6/§7).
12. **Report (D)** — render self-contained HTML.

## 5. Where Claude runs, and the prompt contract

Claude passes are the session agent following the centralized templates in `prompts/`;
the skeptical validator runs via the Agent tool for isolation. Every template enforces:

- use only supplied evidence; no outside knowledge; no invention
- never force an uncertain match; AMBIGUOUS and NONE are always acceptable answers
- separate fact from interpretation; surface uncertainty explicitly
- return schema-valid JSON with evidence quotes and item IDs
- prefer "unable to determine" over speculation

The pipeline treats LLM output as untrusted input: everything is schema-validated and
evidence-checked before it can enter a report. Agreement between two Claude passes is
never treated as proof — evidence checks are.

## 6. Confidence and review classification

Confidence is a class with criteria, not a score:

- **High:** T0/T1 match; or T2 with discriminating quotes + deterministic verdict +
  validator upheld.
- **Medium:** T2 with verified quotes + semantic verdict upheld by validator.
- **Low:** narrow candidate margin, weak/non-discriminating quotes, or validator
  undetermined.

**Human review required** is an orthogonal boolean set by: ambiguity (T3), disputed
findings, duplicate coverage, Cannot Assess with partial evidence, rule conflicts, or
any validation disagreement.

## 7. Coverage

Pure arithmetic over item IDs. Every company row lands in exactly one bucket:
matched / ambiguous / unmatched / ignored-by-rule / extraction-failed. Every official
rule: addressed / unaddressed (with duplicate-coverage flagged). Buckets must sum to
extraction totals or the run fails loudly. The report leads with coverage numbers and
shows a prominent warning banner when extraction failures or ignored content exceed
thresholds (default: any extraction failure warns; >10% of rows failed or ignored →
top-level red banner).

## 8. HTML report

One self-contained file per run: inline CSS/JS, no external assets, works from
`file://` offline. Structure:

1. **Run metadata** — filenames, SHA-256 hashes, timestamp, all component versions.
2. **Warning banner** — never collapsible: extraction failures, low coverage, disputed
   findings, rule conflicts.
3. **Dashboard** — compliant / non-compliant / cannot-assess / ambiguous / unmatched
   counts; per-file coverage.
4. **Findings** — filterable by verdict, confidence, review flag. Each expands to
   side-by-side evidence: company row (raw text + provenance) vs official rule (ID,
   title, check text, expected value), highlighted value diff, match tier + candidate
   score breakdown ("why matched"), validation status, applied rules.
5. **Dedicated sections** — ambiguous matches, unmatched company rows, unaddressed
   official rules, ignored content. Collapsible sections are allowed for bulk, but
   warnings and review-required items are never hidden.

## 9. Feedback loop

- Every finding shows its stable `finding_id` and classification buttons: correct /
  incorrect / wrong match / missed difference / not meaningful / wrong classification /
  other, plus a comment field. Client-side JS accumulates selections; "Export feedback"
  downloads `feedback.json` via data URI (no server needed).
- Equivalent conversational path: the user tells the agent "finding F-3f2a is a wrong
  match" and the Skill writes the same schema.
- Ingestion stores the feedback with run reference, input hashes, and a snapshot of the
  involved row + rule (minimal excerpts, not whole documents). Deduplicated by
  finding ID.
- Every ingested feedback **always** produces a regression case. It produces a
  **candidate rule only** when the correction maps onto a supported rule category, and
  the draft is scoped as narrowly as the evidence supports.

## 10. Rules registry and lifecycle

`rules/registry.json` entries: stable `rule_id`, `version`, `category`
(equivalent-terminology / normalization-exception / matching-key / ignore-field /
exact-compare-field / severity-override / semantic-equivalence), `scope` (global /
document-type / sheet-or-section / field), `status`, provenance (originating feedback
IDs, approver, timestamps).

Lifecycle: feedback → stored → **candidate** (never active automatically) → maintainer
runs review mode → Skill shows the candidate with its originating feedback and runs the
**full regression suite with the rule enabled** → suite pass + explicit human approval →
active; registry version bumps. A candidate that fixes its case but breaks others is
rejected with the diff shown.

Precedence: narrowest scope wins. Two same-scope conflicting rules: both suspended for
the affected item, warning recorded in the run and shown in the report — no silent
resolution. Every finding records the rules that influenced it.

## 11. Regression testing

Each feedback-derived case stores: input snapshots (company row, official rule,
relevant candidates), the applied configuration, and the expected outcome.
`regression.py` replays deterministic stages against the snapshots and asserts on
deterministic facts: match tier, shortlist membership, verdict class, quote validity,
coverage buckets. Genuinely semantic expectations are marked **agent-evaluated** and
advisory; deterministic assertions are the gate for rule activation.

## 12. Versioning and reproducibility

`VERSIONS.json` records: skill version, extraction version, pipeline version, report
schema version, a content hash per prompt file, and the rule registry version. All are
stamped into every run artifact and the report header. Given a report, a future
engineer can identify exactly which code, prompts, and rules produced it.

## 13. Failure visibility

- Per-item status at every stage; unreadable content becomes `extraction-failed` items
  that count against coverage and appear in the report.
- Malformed Claude output: one retry, then a visible hard failure for that stage with
  the affected items listed. The pipeline either fails the run or degrades with a
  recorded, displayed warning — never silently.
- Duplicate official rule IDs in the input, empty sheets, and zero-row tables are
  detected at ingest and surfaced as warnings.

## 14. Confidentiality

- No network calls anywhere in scripts or report (no external assets, no telemetry).
- Logs carry IDs, counts, statuses, rule usage, warnings — never document text.
- Run artifacts and reports stay local under `runs/` (gitignored).
- Feedback snapshots keep minimal excerpts, not full documents.
- The report necessarily contains document content (that is its purpose) and is labeled
  sensitive in its header.

## 15. Testing strategy

- **Pytest over deterministic stages** with a script-built synthetic fixture library
  (docx/xlsx/csv): identical files; formatting-only differences; numbers/dates changed;
  rows added/removed/reordered; duplicate identifiers; multi-sheet Excel; Word tables
  (incl. merged cells); extraction failures; ambiguous matching; low coverage;
  normalization meaning-preservation property tests; value-parser edge cases ("9 or
  more", "≥ 9", "enabled", "15 minutes"); coverage arithmetic; validator quote checks;
  rule precedence and conflicts; feedback → candidate → approval lifecycle; regression
  gate blocking a harmful rule.
- **LLM behavior tested by contract:** JSON-schema validation plus the deterministic
  guards (shortlist membership, quote existence, Cannot-Assess override). The tests
  prove that bad LLM output cannot pass through — they do not pretend to unit-test the
  model.
- False-positive/false-negative attention: candidate-generation recall tests ensure the
  correct rule appears in the shortlist for known-good pairs; margin tests ensure
  near-ties surface as ambiguous rather than resolving arbitrarily.

## 16. Deviations from PROPOSAL.md

The proposal's intent, company-row structure (§4), output fields (§5 step 4), and
honesty rules (§7) are preserved. Deviations, each for an accuracy reason:

1. **"One LLM run" (proposal §9) → multi-stage pipeline.** A single pass over both full
   files invites hallucination, missed content, and wrong-record matching. The pipeline
   keeps the same inputs and outputs but stages the work with deterministic guards.
2. **LLM compares "against every official STIG rule" (proposal §5 step 3) →
   deterministic candidate shortlisting first.** Claude adjudicates among top-K
   pre-screened candidates; a low floor plus coverage warnings mitigate shortlist
   misses.
3. **Official file formats extended** from CSV/JSON to CSV/JSON/XLSX; company file
   extended from DOCX to DOCX/XLSX (per the user's brief).
4. **Output schema extended** with evidence quotes, match tier, candidate scores,
   validation status, applied rules, and stable IDs — required for traceability and
   the feedback loop.

## 17. Limitations and risks

- **Shortlist miss:** if the correct rule never enters the top-K, the row reports
  unmatched (false negative). Mitigated by low floor, K=5, recall tests, and the
  unaddressed-rules section making gaps visible; not eliminable.
- **Extraction ceiling:** severely malformed Word tables (nested tables, images of
  tables, scanned content) may fail extraction; these surface as extraction-failed
  items, not silent gaps — but the content still is not compared.
- **Semantic verdicts remain judgments:** validated and evidence-bound, but a
  paraphrase equivalence call can still be wrong; confidence classes and the review
  flag exist precisely because of this.
- **Regression suite scope:** it gates on deterministic assertions; semantic
  regressions are advisory only.
- **Single-machine trust:** rule approval integrity depends on git discipline in the
  internal environment.
