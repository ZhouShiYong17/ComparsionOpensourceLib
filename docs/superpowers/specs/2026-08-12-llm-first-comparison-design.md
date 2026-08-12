# stig-compare 0.3.0 — LLM-First Comparison Design

Status: approved by user 2026-08-12; implemented on branch `llm-first-comparison`.
Supersedes the matching/verdict portions of `2026-08-10-stig-comparison-skill-design.md`
and `2026-08-11-claude-first-extraction-design.md` (whose extraction layer largely survives).

## 1. Mandate

All semantic decisions are made by the LLM: which rows match, whether
controls are equivalent, whether the submission complies or deviates,
whether a finding is valid. No deterministic Python for any of these — no
lexical similarity, keyword/rule matching, scoring thresholds, or
hard-coded comparison rules. Python is limited to: file parsing, lossless
extraction, chunking by size, provenance tracking, shape/enum/quote
validation, state machine, coverage arithmetic, report generation.

Information preservation is the top requirement. The comparison unit is one
COMPLETE company-submission row (verbatim cells, continuation-row cells,
header row, sheet/section, preceding narrative, row number, merged info,
provenance, additive canonical-field aids) vs COMPLETE official STIG row(s)
(ALL columns verbatim, headers, sheet, row number, provenance). Verbatim
originals stay available to the LLM through matching, comparison, AND
validation.

User decisions locked 2026-08-12:
1. Verdicts: `{Compliant, Deviating, Incomplete, Ambiguous, Cannot Assess}`
   + orthogonal LLM-set `human_review` flag + change-analysis tags
   `{omitted, contradicted, weakened, strengthened, materially-changed}`.
2. Feedback: rule registry + deterministic replay retired. Feedback stored
   verbatim; precedents mechanically keyed by official row, injected into
   future comparison requests, applicability judged by the LLM. Regression
   replay re-runs the LLM passes (advisory only).
3. Scale target: official corpus ~150–500 rules; byte-budget chunking,
   constants centralized in `scripts/schema.py`.

## 2. Architecture

- `scripts/schema.py` — every LLM-chosen enum + every batch/chunk constant.
- `scripts/payloads.py` — single source of truth for complete-row request
  payloads (`company_record_payload`, `official_row_payload`); the
  information-preservation invariant is testable here.
- `scripts/extract.py` — lossless official extraction: all columns verbatim
  (`cells` positional + `raw_record` view), stable `OR-` hash join keys,
  `display_id`/`column_roles` filled later from the LLM structure pass.
  `OFFICIAL_HEADER_SYNONYMS` deleted.
- `scripts/skeleton.py` — unchanged (already lossless).
- `scripts/canonical.py` — mechanics only: chunking, record shape (full raw
  row + nested additive `canonical_fields`), reconciliation. Regex claim
  classification deleted; the LLM emits `company_claim_reading`.
- `scripts/pipeline.py` — state machine. CLI: `start | resolve | sweep |
  rollup | finalize [--no-report] [--allow-pending]`. `resolve` is the
  single advancer consuming all nine response kinds. Two-strike settlements
  are pipeline statuses, never verdicts. Retry echo (`retry: true`) and
  sweep-round echo (`sweep_round: true`) are validator-enforced so re-round
  answers are never byte-identical to consumed lines (closes the
  sweep-replay fingerprint blind spot).
- `scripts/validate.py` — mechanical firewall only. Quote sources span
  parent + continuation-row cells (closes the merged-row quote blind spot)
  and all official columns. Includes the uphold-consistency check
  (`upheld` with `independent_verdict != claimed` is rejected as
  incoherent output).
- `scripts/coverage.py` — counts LLM decisions: buckets `matched /
  ambiguous / unmatched / unresolved / ignored_irrelevant_table /
  separator / extraction_failed`; official `addressed / unaddressed /
  multi_matched_row_ids` (drives rollup). Red banner over
  `extraction_failed + unresolved`.
- `scripts/report.py` — full-row evidence, field-alignment table,
  validation panels, rollup + unresolved sections, 5-verdict badges.
- `scripts/feedback.py` — verbatim storage + `feedback/precedents.jsonl`
  index + advisory regression cases. No parsing of reviewer text.
- `scripts/regression.py` — advisory LLM replay (`build_replay` /
  `evaluate_replay`). No gate, no registry.

Deleted: `candidates.py`, `compare_values.py`, `rules.py`, `normalize.py`,
`rules/` registry tree, review mode, `assign_confidence`, the
margin-override, the Python human-review trigger ladder.

## 3. Pass sequence

start → official_structure + table_mapping (2-round loops) →
row_interpretation (2) → match_scoping (record batches × full-corpus byte
slices; zero nominations across all slices = the LLM's "none") →
match_adjudication (binding, multi-select, no override) → sweep once
(reverse recall, full payloads, proposals re-adjudicated with sweep_round
echo) → comparison (one request per matched record covering its ENTIRE
selected set — joint N:1; byte-split only if oversized, warned + forced
review) → rollup once (per official row with ≥2 matchers — 1:N) →
finalize --no-report (gates, then emits validation requests; exit 4 is the
designed continue signal) → validation via isolated Agent-tool subagents
(reversed blinding: full first-pass reasoning included, but
independent-verdict-first protocol) → finalize --allow-pending (merge:
revised swaps effective verdict keeping `first_pass_verdict`; refuted sets
`disputed`; coverage; report).

`human_review_needed` = LLM `human_review` OR integrity reasons only
(validation refuted/revised/needs-human/missing/rejected, claim
contradicted, uncertain table, scoping incomplete, comparison split,
rejected output touching the record, rollup-verdict-differs) — recorded in
`review_reasons` for audit.

## 4. Deliberate deviations & accepted limitations

- Rollup requests are NOT byte-split (splitting a joint assessment defeats
  its purpose); oversized rollups are warned + forced review.
- Ambiguous match decisions get no comparison pass (ambiguous leftovers),
  matching prior behavior.
- `sweep_originated` is a badge, not a forced-review trigger (adjudication
  + comparison + validation all re-verify).
- Validation cannot revise confidence, only verdicts.
- No recognizable official ID column → `display_id` null, OR- hash keys;
  precedents then don't travel across official files.
- Parked previously, still accepted: w:sdt content controls skipped in the
  docx skeleton; xlsx `data_only` formula-cache loss.
