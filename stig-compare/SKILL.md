---
name: stig-compare
description: Compare a company STIG submission (Word/Excel) against an official
  STIG file (CSV/JSON/Excel) and generate a self-contained HTML comparison
  report. Every semantic decision (matching, comparison, verdicts, validation)
  is made by the LLM over complete rows. Use when the user wants to check a
  STIG submission, compare STIG files, or mentions STIG compliance review.
  Also use when the user wants to submit feedback on a comparison report,
  ingest reviewer feedback, or replay past feedback against current prompts.
---

# stig-compare

Compares a company's STIG (Security Technical Implementation Guide)
submission against an official STIG source, producing a self-contained HTML
report. All scripts live in `scripts/` and are invoked from the
`stig-compare` package root (`python scripts/pipeline.py ...`, etc.) — always
run them from, or with paths relative to, that root.

**The division of labor is absolute:** every semantic decision — which rows
match, whether a control is equivalent, whether the submission complies or
deviates, whether a finding survives scrutiny — is made by you (the LLM) in
a prompt-driven pass, over the COMPLETE rows of both documents. Python only
parses, chunks by size, validates mechanically (shapes, enums, verbatim
quotes), counts coverage, and renders the report. It never scores, ranks,
or overrides your answers, and a two-strike settlement is always a pipeline
status (`llm-output-rejected`, `*-pass-not-run`) — never a verdict.

This skill has three modes: **compare**, **feedback**, and **replay**.

- **Compare**: check a company STIG submission against an official STIG
  file. -> Compare mode.
- **Feedback**: the user has a `feedback.json` exported from a report's
  "Export feedback" button. -> Feedback mode.
- **Replay**: the user wants past reviewer feedback re-checked against the
  current prompts (advisory only). -> Replay mode.

## Hard rules for the executing agent

These apply throughout every mode, no exceptions:

- Never edit files in `runs/` except `*_responses.jsonl`.
- Never mark a response for a row that has no request.
- Never proceed past a non-zero pipeline exit code — surface it.
- Never summarize findings not present in `final.json`.
- When a request carries `retry: true`, your response MUST echo
  `"retry": true`; a sweep-round adjudication request carries
  `sweep_round: true` and your response MUST echo it. A missing echo is
  rejected mechanically (this is what makes a retried answer
  byte-distinguishable from a replay).

Everything you write into a `*_responses.jsonl` file is untrusted input
from the pipeline's point of view — it is mechanically re-validated (quotes
must be verbatim substrings of the supplied evidence, IDs must reference a
real pending request, enums must be one of the allowed values) before it
can affect `final.json`. A response that fails validation never silently
disappears: it becomes a `validation_failures.jsonl` entry, and every
response kind — `official_structure`, `table_mapping`, `interpretation`,
`scoping`, `adjudication`, `comparison`, `rollup`, `validation` — gets one
retry (two strikes total) before the pipeline settles the unit mechanically
instead of asking again: a table becomes `mapping-failed`, a chunk becomes
`interpretation-rejected` (its rows fall back to `extraction-failed`
records), a scoping cell becomes `scoping-cell-rejected` (its records are
flagged `scoping_incomplete`), a record's match becomes
`unresolved-llm-output-rejected`, a comparison unit's pairs land in
`unresolved_pairs`, and a validation becomes `llm-output-rejected` with
forced human review. (`sweep` has no retry of its own — a rejected sweep
response is simply dropped from that batch; the sweep pass itself never
repeats within a run.) Do not try to work around a validation failure by
inventing content that isn't actually in the evidence you were given — fix
your answer using only what the request supplied, or leave the row for
human review.

Designed exceptions to "never proceed past a non-zero exit code", scoped
exactly as described: `finalize` exit `4` is the pending-work continue
signal for the loops in steps 10–11, and `sweep`/`rollup` exit `4` means
"an earlier stage is still pending — finish it first". Every other
non-zero exit code, anywhere in any mode, must be surfaced rather than
worked around.

**Cost expectation:** the scoping pass reads the ENTIRE official corpus for
every batch of company records — roughly `ceil(records/8) ×
ceil(official_bytes/60KB)` requests. That is the price of never letting a
Python heuristic pre-filter what you see. All batch/chunk constants live in
`scripts/schema.py`.

## Compare mode

1. **Get inputs.** If the user has not already given you exactly two file
   paths — one official STIG file (`.csv`/`.json`/`.xlsx`) and one company
   submission (`.docx`/`.xlsx`) — ask for exactly those two paths. Don't
   guess file locations.

2. **Create the run directory.** Make `runs/<timestamp>` (e.g.
   `runs/2026-08-12T143205`) under the package root.

3. **Start the run:**
   ```
   python scripts/pipeline.py start --official <official_path> \
       --company <company_path> --run-dir runs/<timestamp>
   ```
   On an unreadable or corrupted input file, `start` exits `2` and prints
   `pipeline: cannot read file: <ExceptionTypeName>` (never document
   content) — report that exception type and stop; do not retry the same
   file, re-parse it yourself, or fabricate extraction results.

4. **Answer official-structure and table-mapping requests, then resolve —
   repeat while there is new work, capped at 2 rounds each.**
   - `official_structure_requests.jsonl`: one request per sheet/section of
     the official file. Follow `prompts/official_structure.md` — identify
     the display-ID column and a role for every column. This is annotation
     only; nothing you answer here drops any official content.
   - `table_mapping_requests.jsonl`: one request per company table. Follow
     `prompts/table_mapping.md` — classification (`stig_relevant |
     irrelevant | uncertain`), column annotation (canonical field or
     `other`), verbatim `context_grouping`. `irrelevant` is the only
     content-excluding decision; prefer `uncertain` when unsure.
   - Append responses (one JSON object per line) to the matching
     `*_responses.jsonl`, then run
     `python scripts/pipeline.py resolve --run-dir runs/<timestamp>`.
   - A unit that fails validation once comes back with `retry: true` and
     `previous_errors` — answer only newly-appended entries, echoing
     `retry: true`. Two failures settle it mechanically.

5. **Answer row-interpretation requests — same loop shape, capped at 2
   rounds.** Every `stig_relevant`/`uncertain` table is split into ≤40-row
   chunks in `interpretation_requests.jsonl`. Follow
   `prompts/row_interpretation.md`: account for EVERY row exactly once
   (`record | separator | continuation`), extract canonical-field aids with
   cell-verbatim provenance, and read the row's own compliance claim
   (`company_claim_reading`). Remember the full raw row travels regardless
   — sparse fields are fine, invented text is not. `resolve` after
   answering; when a table's chunks are all done, its records are built and
   scoping requests appear.

6. **Answer match-scoping requests — capped at 2 rounds.**
   `scoping_requests.jsonl` crosses every batch of ~8 complete company
   records with every ~60KB slice of the complete official corpus — this
   is the big pass; answer every cell. Follow `prompts/match_scoping.md`:
   nominate every plausible (record, official row) pair in the slice.
   Unbounded, empty allowed, recall over precision. You are not deciding
   matches here. `resolve` after answering; once a record's every corpus
   slice is answered, its adjudication request appears (or, with zero
   nominations anywhere, the pipeline records your collective "none").

7. **Answer adjudication requests — capped at 2 rounds.**
   `adjudication_requests.jsonl` gives each record with ALL its nominated
   official rows, complete on both sides. Follow
   `prompts/match_adjudication.md`: `match` (multi-select with per-selection
   verbatim quotes), `none`, or `ambiguous`. Your decision is final — no
   code overrides it. `resolve` after answering; comparisons appear for
   every match.

8. **Run the sweep once:**
   ```
   python scripts/pipeline.py sweep --run-dir runs/<timestamp>
   ```
   Exit `4` means scoping/adjudication is still pending — finish steps 6–7
   first. `sweep: nothing-to-sweep` means move on. Otherwise answer
   `sweep_requests.jsonl` batches (complete unmatched records × complete
   unaddressed official rows) per `prompts/sweep.md` — proposals, not
   matches; empty allowed. `resolve` turns proposals into fresh
   adjudication requests marked `sweep_round: true`; answer those exactly
   as in step 7, ECHOING `"sweep_round": true`, then `resolve`. The sweep
   never repeats, so this is one extra adjudication round, not a loop.

9. **Answer comparison requests — capped at 2 rounds.** One request per
   matched record in `comparison_requests.jsonl`, carrying the complete
   record, EVERY official row it matched (judge them jointly), the match
   basis, and any precedents from past reviewer feedback. Follow
   `prompts/comparison.md`: per official row — field-by-field alignment,
   semantic differences, change-analysis tags, verdict (`Compliant |
   Deviating | Incomplete | Ambiguous | Cannot Assess`), your confidence,
   and whether a human should review; plus record-level claim consistency.
   `resolve` after answering.

10. **Run rollup once, answer, resolve:**
    ```
    python scripts/pipeline.py rollup --run-dir runs/<timestamp>
    ```
    Exit `4` means comparisons (or the sweep) are still pending. It emits
    one request per official row that ≥2 records matched — follow
    `prompts/rule_rollup.md` to judge whether the records JOINTLY satisfy
    the requirement. Answer, then `resolve`. `rollup: groups=0` just means
    no official row had multiple matchers.

11. **Finalize (validation gate), dispatch validation, finish.**
    - Run `python scripts/pipeline.py finalize --run-dir runs/<timestamp>
      --no-report` — WITHOUT `--allow-pending`.
      - Exit `4` naming pending mapping/interpretation/scoping/matching/
        comparison/rollup work: an earlier step still has unanswered
        retries — go answer them (steps 4–10), `resolve`, and try again.
        Do NOT reach for `--allow-pending` while an answerable retry
        remains; that would sweep it into a false `*-pass-not-run`.
      - Exit `4` printing `pending validation=N`: the gate has emitted
        `validation_requests.jsonl` — one request per finding and per
        rollup. This is the designed continue signal; dispatch validation
        now.
    - **Dispatch the validation pass using the Agent tool, as isolated
      subagents with no access to this conversation's reasoning.** Give
      each subagent ONLY the contents of `prompts/validation.md` and the
      raw request line(s) from `validation_requests.jsonl`. The request
      deliberately CONTAINS the first pass's reasoning and verdict — the
      independence lives in the subagent's required protocol (own
      conclusion FIRST, then compare), not in evidence blinding, and in
      the fact that the subagent shares none of your working context. You
      may batch several requests into one subagent, but never validate a
      finding inline in this conversation. Append each subagent's JSON
      answers to `validation_responses.jsonl`, then `resolve`. A rejected
      validation answer gets one retry (echo `retry: true`).
    - Re-run `finalize --no-report` until it exits `0` (all validations
      resolved), answering any retries in between. If after 2 validation
      rounds something remains unanswered, run once with `--allow-pending`
      (keep `--no-report`) so it is honestly marked — last resort only.
    - **Final render:**
      ```
      python scripts/pipeline.py finalize --run-dir runs/<timestamp> --allow-pending
      ```
      This is the only `finalize` call that omits `--no-report`. It merges
      validation outcomes (an outcome of `revised` swaps the effective
      verdict and keeps `first_pass_verdict`; `refuted` marks the finding
      `disputed`), computes coverage, writes `final.json`, and renders
      `report.html`. Exit `3` (coverage arithmetic) must be surfaced.

12. **Present the results.** Report, in this order:
    1. Warnings — everything in `final.json["warnings"]`. Lead with these.
    2. Coverage — `final.json["coverage"]`: company rows
       matched/ambiguous/unmatched/unresolved/ignored (note
       `ignored_irrelevant_table` — rows correctly excluded by triage,
       distinct from rows that were lost), official rows
       addressed/unaddressed, and `multi_matched_row_ids`. Check
       `final.json["table_triage"]` and call out any `uncertain` or
       `mapping-failed` table by name.
    3. The report path: `runs/<timestamp>/report.html` — self-contained,
       open directly from disk.
    4. Offer the feedback flow: the report's "Export feedback" button
       downloads a `feedback.json`; the user can hand that back for
       feedback mode.

    Never lead with, or make, a confidence statement about the comparison
    as a whole — only report what `final.json` actually contains: specific
    findings, their individual `confidence`/`human_review_needed`/
    `validation` fields, and the warnings and coverage numbers above.

## Feedback mode

The user supplies a `feedback.json` file (from a report's "Export feedback"
button) and the `runs/<timestamp>` directory the report came from.

```
python scripts/feedback.py ingest <feedback.json> --run-dir runs/<timestamp>
```

This prints `ingest: stored=N cases=N precedents=N errors=N`. Report those
counts:
- `stored` — feedback items recorded verbatim under `feedback/` (audit
  trail; nothing is parsed or interpreted by code).
- `precedents` — lines added to `feedback/precedents.jsonl`, keyed by
  official row. Future comparison requests citing those rows carry the
  feedback verbatim, and the comparing LLM judges whether it applies.
- `cases` — advisory regression cases under `tests/regression/`, replayable
  via Replay mode.
- `errors` — items referencing a `finding_id` not in that run's
  `final.json`; surface these, don't silently drop them.

## Replay mode

Re-checks past feedback against the current prompts. Advisory only — it
never gates, blocks, or rewrites anything.

1. Build the frozen requests:
   ```python
   import regression
   regression.build_replay(package_root, replay_dir)
   ```
2. Answer `replay_requests.jsonl` exactly like comparison requests
   (`prompts/comparison.md`), appending to `replay_responses.jsonl`. These
   are real LLM comparisons over frozen inputs — same rules, verbatim
   quotes and all.
3. Evaluate:
   ```python
   regression.evaluate_replay(package_root, replay_dir)
   ```
   Report from `replay_report.json`: for each case, the fresh verdict vs
   the prior one, whether they agree, and the reviewer's classification
   and comment VERBATIM. Disagreements are information for the human
   maintainer — never "failures", and never something to auto-fix.
