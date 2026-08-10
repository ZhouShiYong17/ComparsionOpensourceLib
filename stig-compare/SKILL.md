---
name: stig-compare
description: Compare a company STIG submission (Word/Excel) against an official
  STIG file (CSV/JSON/Excel) and generate a self-contained HTML comparison
  report. Also ingests report feedback and reviews candidate comparison rules.
  Use when the user wants to check a STIG submission, compare STIG files, or
  mentions STIG compliance review. Also use when the user wants to submit
  feedback on a comparison report, ingest reviewer feedback, or review and
  approve candidate comparison rules.
---

# stig-compare

Compares a company's STIG (Security Technical Implementation Guide)
submission against an official STIG source, producing a self-contained HTML
report. All scripts live in `scripts/` and are invoked from the
`stig-compare` package root (`python scripts/pipeline.py ...`, etc.) — always
run them from, or with paths relative to, that root. This skill has three
modes: **compare**, **feedback**, and **review**. Work out which one the
user wants before doing anything:

- **Compare**: the user has (or wants to check) a company STIG submission
  against an official STIG file. -> Compare mode.
- **Feedback**: the user has a `feedback.json` file exported from a report's
  "Export feedback" button (or otherwise wants report feedback recorded).
  -> Feedback mode.
- **Review**: the user wants to review, approve, or reject candidate
  comparison rules that feedback ingestion has drafted. -> Review mode.

## Hard rules for the executing agent

These apply throughout every mode, no exceptions:

- Never edit files in `runs/` except `*_responses.jsonl`.
- Never mark a response for a row that has no request.
- Never proceed past a non-zero pipeline exit code — surface it.
- Never summarize findings not present in `final.json`.

Everything you (the agent) write into a `*_responses.jsonl` file is
untrusted input from the pipeline's point of view — it is mechanically
re-validated (quotes must be verbatim substrings of the supplied evidence,
IDs must reference a real pending request, enums must be one of the allowed
values) before it can affect `final.json`. A response that fails validation
never silently disappears: it becomes a `validation_failures.jsonl` entry,
and every response kind — `table_mapping`, `canonicalize`, `matching`,
`sweep`, `semantic` — gets one retry (two strikes total) before the
pipeline settles the unit mechanically instead of asking again: a table
becomes `mapping-failed`, a chunk becomes `canonicalize-rejected` (its rows
fall back to `extraction-failed` records), a record's match becomes
`T4`/`llm-output-rejected`, and a semantic pair becomes `Cannot
Assess`/`llm-output-rejected`. (`sweep` has no retry of its own — a
rejected sweep response is simply dropped from that batch; the sweep pass
itself never repeats within a run.) Do not try to work around a validation
failure by inventing content that isn't actually in the evidence you were
given — fix your answer using only what the request supplied, or leave the
row for human review.

One designed exception to "never proceed past a non-zero exit code": step 8
below uses `finalize` exit code `4` (refused — pending extraction/matching/
semantic work) as its retry loop's expected continue signal, not a failure.
That exception is scoped exactly to that loop and its documented round cap
— every other non-zero exit code, anywhere in any mode, must still be
surfaced rather than worked around.

## Compare mode

1. **Get inputs.** If the user has not already given you exactly two file
   paths — one official STIG file (`.csv`/`.json`/`.xlsx`) and one company
   submission (`.docx`/`.xlsx`) — ask for exactly those two paths. Don't
   guess file locations.

2. **Create the run directory.** Make `runs/<timestamp>` (e.g.
   `runs/2026-08-10T143205`) under the package root — this is where every
   artifact for this comparison lives.

3. **Start the run:**
   ```
   python scripts/pipeline.py start --official <official_path> \
       --company <company_path> --run-dir runs/<timestamp>
   ```
   A non-zero exit code here means extraction failed (bad file, unreadable
   format, etc.) — surface the error and stop; do not try to patch around
   it. On an unreadable or corrupted input file, `start` exits with code
   `2` and prints `pipeline: cannot read file: <ExceptionTypeName>` to
   stderr (never document content) — report that exception type and stop;
   do not retry the same file, do not attempt to re-parse or repair it
   yourself, and do not fabricate extraction results to keep going.

4. **Answer table-mapping requests, then resolve — repeat while there is
   new work, capped at 2 rounds.** `start` classifies nothing itself: every
   table the company file contains lands in
   `runs/<timestamp>/table_mapping_requests.jsonl` needing an answer (a
   table already answered in an earlier round is never rewritten — only the
   newly appended retries need answers this round).
   - For each table you have not yet answered: read the file named by its
     `instructions_file` (`prompts/table_mapping.md`), follow it exactly,
     and produce one JSON object per table — `table_index`,
     `classification` (`stig_relevant | irrelevant | uncertain`),
     `irrelevant_reason`, `column_mapping` (column index -> canonical
     field, `extra_field`, or `ignore`), and `context_grouping` (copied
     verbatim, never composed or paraphrased). Append each response as one
     line to `table_mapping_responses.jsonl`.
   - Run `python scripts/pipeline.py resolve --run-dir runs/<timestamp>`.
     A non-zero exit code must be surfaced, not worked around.
   - A table that fails validation once comes back in
     `table_mapping_requests.jsonl` with `retry: true` and
     `previous_errors` — answer only that newly-appended entry on the next
     round. A table that fails twice is settled mechanically as
     `mapping-failed` (its rows surface later as `extraction_failed`
     coverage plus a `mapping-failed` warning) and is never re-requested.
   - Stop once a `resolve` call reports no new/retried table-mapping
     entries, or after 2 rounds total — whichever comes first.

5. **Answer canonicalize requests — same loop shape, capped at 2 rounds.**
   Every `stig_relevant` or `uncertain` table from step 4 is split into one
   or more row chunks in `canonicalize_requests.jsonl` (an `irrelevant`
   table produces none).
   - For each chunk you have not yet answered: read `prompts/canonicalize.md`,
     follow it exactly, and produce one response object per chunk —
     `chunk_id` plus one entry per row (`disposition: record | separator |
     continuation`, with `records`/`fields`/`field_provenance` for a
     `record` disposition). **Every row of every chunk must be accounted
     for exactly once** — a response that loses or duplicates a
     `row_index` is rejected mechanically. Append to
     `canonicalize_responses.jsonl`.
   - Run `resolve` again. A chunk that fails validation once is
     re-requested with `retry: true`/`previous_errors`; one that fails
     twice is settled as `canonicalize-rejected` and its rows become
     `extraction-failed` records rather than blocking the run. Once every
     chunk of a table is done, that same `resolve` call builds its
     canonical company records and their matching shortlists —
     `matching_requests.jsonl` appears (or grows) at that point.
   - Stop once nothing new appears in `canonicalize_requests.jsonl`, or
     after 2 rounds total.

6. **Answer matching requests — 2-round loop as before** (multi-select:
   one selection per genuinely-matching candidate; `none`/`ambiguous`
   always acceptable), then:
   - For each record in `matching_requests.jsonl` you have not yet
     answered: read `prompts/matching.md`, follow it, and append one JSON
     object per record to `matching_responses.jsonl`. A record can
     genuinely satisfy more than one official rule — emit one `selections`
     entry per matched `rule_id`, each with its own verbatim
     `row_quote`/`rule_quote`, rather than picking only the best one.
   - Run `resolve` again. A rejected matching answer gets one retry
     (`retry: true`/`previous_errors` on the re-appended request) before
     the record is forced to tier `T4` with warning `llm-output-rejected`
     — never fabricate a match to avoid that outcome.
   - Stop once `resolve` reports no new/retried matching entries, or after
     2 rounds total.

7. **Run the sweep once:**
   ```
   python scripts/pipeline.py sweep --run-dir runs/<timestamp>
   ```
   This is a single deterministic pass, not a loop — a second `sweep` call
   on the same run is a safe no-op. If every record already matched, or
   every official rule is already addressed, it prints
   `sweep: nothing-to-sweep` and there is nothing further to do here; move
   on to step 8. Otherwise it writes `sweep_requests.jsonl`: batches of up
   to 20 still-unmatched records against an index of the still-unaddressed
   rules.
   - For each batch, read `prompts/sweep.md` and follow it — **its
     proposals are candidates for the matching pass to evaluate, not
     matches themselves.** Propose a `(record_id, rule_id)` pair only when
     the record plausibly speaks to that rule at all; an empty
     `proposals` array is an acceptable answer. Append one response object
     per batch to `sweep_responses.jsonl`, then `resolve`.
   - `resolve` turns each accepted proposal into a fresh entry in
     `matching_requests.jsonl` (marked `sweep_round: true`). Answer those
     exactly as in step 6, then `resolve` once more. Because the sweep
     pass itself never repeats, this is at most one extra round of
     matching, not a new loop.

8. **Answer semantic requests, then dispatch the skeptic and finalize for
   real.** If `runs/<timestamp>/semantic_requests.jsonl` doesn't exist at
   this point, every match in this run was decided deterministically —
   skip straight to the skeptic dispatch below. Otherwise:
   - **Semantic loop — same retry-loop shape as steps 4–6, capped at 2
     rounds, and never with `--allow-pending` inside the loop:**
     - For each record in `semantic_requests.jsonl` you have not yet
       answered (on a second round, that means the newly-appended records
       carrying `retry: true` / `previous_errors`): read its
       `instructions_file` (`prompts/semantic_compare.md`), follow it, and
       append one JSON object per line to `semantic_responses.jsonl`.
     - Run `python scripts/pipeline.py finalize --run-dir runs/<timestamp> --no-report`
       — **without** `--allow-pending`.
       - Exit `0`: every table-mapping/canonicalize/matching/semantic pair
         now has a real resolution — the two-strike protocol already
         turns a second bad retry into an honest `Cannot Assess`/
         `llm-output-rejected` finding automatically, inside this same
         call, with no need for `--allow-pending`. Stop looping;
         `final.json` is ready for the skeptic dispatch below.
       - Exit `4` (prints `pending mapping=…/pending canonicalize=…/pending
         matching=…/pending semantic=…`): this is this loop's designed
         continue signal (see the hard-rules note above), not a failure.
         Check the newly-appended `retry: true` record(s) and the new
         entries in `validation_failures.jsonl` for why. If you are under
         2 rounds, go back to the top of this loop and answer only the new
         retry records. **Do not reach for `--allow-pending` here** —
         doing so before a retry has been given its second chance would
         silently and permanently sweep an answerable pair into a
         `*-pass-not-run` finding that falsely claims that pass never ran.
       - Any other non-zero exit must be surfaced per the hard rules — do
         not loop past it.
     - If you reach 2 rounds and `finalize --no-report` (still without
       `--allow-pending`) is still refusing, that means something was
       never answered at all (not merely retried and rejected twice) — run
       it once more with `--allow-pending` added (keep `--no-report`) so
       the genuinely-unanswered work is honestly marked `*-pass-not-run` /
       `human_review_needed: true` instead of being left in limbo. This is
       the only place before the skeptic dispatch where `--allow-pending`
       may be used, and only as this last resort after both rounds are
       exhausted.
   - **Dispatch the skeptical validator, then finalize for real.**
     - The `final.json` produced by the semantic loop's last `finalize`
       call already has, for every finding (deterministic or semantic),
       exactly the evidence shape `prompts/validator.md` expects:
       `finding_id`, `row_id`, `rule_id`, `verdict` (the claim being
       tested), `finding_type`, `observation`, `company_row`
       (`original_company_text` + `source_reference` only), and
       `official_rule` (`rule_id`/`title`/`check_text`/`expected_value` —
       deliberately no `fix_text`/`severity`).
     - For every finding in `final.json` whose `finding_type` is not `null`
       (a semantic-comparison finding — deterministic findings, where
       `finding_type` is `null`, do not go through the skeptic), dispatch
       the skeptical validator **using the Agent tool**, as an isolated
       subagent with no access to this conversation's reasoning. Give that
       subagent ONLY: the contents of `prompts/validator.md`, and the
       finding's raw evidence (`finding_id`, `row_id`, `rule_id`,
       `verdict`, `finding_type`, `observation`, `company_row`,
       `official_rule`) — **never** the first pass's `interpretation`, and
       never anything from your own earlier matching/semantic reasoning.
       You may batch multiple findings into one subagent dispatch, but the
       subagent itself must be fresh and isolated — it forms its own
       conclusion from the raw evidence, not from what the first pass
       already decided. Its job is to try to DISPROVE the finding
       (misquotes, wrong-record comparisons, meaning-changing paraphrase,
       formatting-only differences misclassified as semantic) and answer
       `{"finding_id": "...", "outcome": "upheld | refuted | undetermined",
       "reason": "..."}`. Append one such JSON object per line to
       `skeptic_responses.jsonl`.
     - Run `python scripts/pipeline.py finalize --run-dir runs/<timestamp> --allow-pending`
       **one final time — this is the only `finalize` call in the whole
       compare-mode flow that omits `--no-report`, and the only one that
       unconditionally carries `--allow-pending`.** By this point the
       semantic loop has already given every retry its full 2 rounds, so
       `--allow-pending` here cannot prematurely sweep anything
       answerable — it only (a) merges the skeptic outcomes (`disputed`,
       `skeptic.outcome`/`skeptic.reason`) into the findings, (b)
       recomputes `confidence`/`human_review_needed`, and (c) renders
       `report.html`. Because responses are fingerprinted, calling
       `finalize` again here is always safe. A non-zero exit code (e.g.
       exit 3 if coverage accounting doesn't add up) must still be
       surfaced, not silently retried past.

9. **Present the results.** Report, in this order:
   1. Warnings — everything in `final.json["warnings"]` (extraction
      warnings, `uncertain-table`, `mapping-failed`, rule conflicts,
      dropped duplicate findings, `company-declared-deviation`,
      `claim-contradicted`, contradictory verdicts, low-coverage red
      banners). Lead with these.
   2. Coverage — `final.json["coverage"]`: how many company rows were
      matched/ambiguous/unmatched/ignored/unresolved (note the
      `ignored_irrelevant_table` bucket specifically — rows correctly
      excluded by table triage, distinct from rows that were lost), and
      how many official rules were addressed/unaddressed. Also check
      `final.json["table_triage"]` (every table's classification,
      `irrelevant_reason`, and `column_mapping`) and call out any
      `uncertain` or `mapping-failed` table by name.
   3. The report path: `runs/<timestamp>/report.html`. It is
      self-contained (no network calls) — open it directly from disk; its
      dashboard includes the same table-triage panel.
   4. Offer the feedback flow: the report has an "Export feedback" button
      that downloads a `feedback.json`; if the user reviews the report and
      has corrections, they can hand that file back for feedback mode.

   Never lead with, or make, a confidence statement about the comparison as
   a whole ("I'm confident this submission is compliant", etc.) — only
   report what `final.json` actually contains: specific findings, their
   individual `confidence`/`human_review_needed` fields, and the warnings
   and coverage numbers above. Never summarize findings not present in
   `final.json`.

## Feedback mode

The user supplies a `feedback.json` file (from a report's "Export feedback"
button) and the `runs/<timestamp>` directory the report came from.

```
python scripts/feedback.py ingest <feedback.json> --run-dir runs/<timestamp>
```

This prints a line like `ingest: stored=N cases=N candidates=N errors=N`.
Report those four counts to the user:
- `stored` — feedback items recorded (each becomes an audit-trail record
  under `feedback/`).
- `cases` — regression cases written under `tests/regression/`, used to
  make sure future rule changes don't reintroduce the same mistake.
- `candidates` — draft comparison rules written under `rules/candidates/`.
  A candidate rule is never active on its own — remind the user that
  candidates need review (see Review mode below) before they can affect any
  future comparison.
- `errors` — feedback items that referenced a `finding_id` not present in
  that run's `final.json`, or were otherwise unusable; surface these, don't
  silently drop them.

## Review mode

For each candidate rule file in `rules/candidates/` (each `RL-*.json`):

1. **Show the rule and its origin.** Read the candidate file — it carries
   `rule_id`, `category`, `scope`, `payload`, and
   `provenance.feedback_ids`. Look up each feedback ID under `feedback/` to
   show the maintainer the original finding and the reviewer's comment that
   led to this draft — never ask for a decision without showing the
   originating feedback.

2. **Evaluate it.** Run the approval gate (it never writes anything itself):
   ```python
   import regression
   verdict = regression.evaluate_candidate(package_root, candidate_path)
   ```
   This replays the full regression suite (`tests/regression/RC-*.json`)
   twice — once against the currently active registry (`baseline`), once
   with this candidate added as if active (`trial`) — and returns
   `{"candidate_id", "baseline", "trial", "regressions", "approvable"}`.

3. **Show baseline vs. trial, and any regressions.** Report
   `baseline["passed"]/["failed"]/["total"]` next to
   `trial["passed"]/["failed"]/["total"]`, and list `verdict["regressions"]`
   explicitly (case IDs that passed on the baseline registry but fail once
   this candidate is added) — these are cases this candidate would newly
   break. `verdict["approvable"]` is `True` only when there are zero
   regressions and zero trial failures.

4. **Ask the human maintainer explicitly.** Never decide on your own. Ask
   by name whether they approve this specific candidate rule, and if
   `verdict["approvable"]` is `False`, say so plainly before asking — do not
   soften or bury a non-approvable result.

5. **Only on an explicit yes, approve it — using their stated name:**
   ```python
   import regression
   regression.approve_candidate(package_root, candidate_path, approver)
   ```
   where `approver` is the name the maintainer gave you, not a placeholder.
   This re-checks the gate itself before writing (so it can never approve a
   regressing candidate even if step 2's result is stale), then moves the
   rule into `rules/registry.json` as active and deletes the candidate
   file. If they decline, or don't give a clear yes, leave the candidate
   file exactly where it is and move to the next one.

**Never auto-approve.** A candidate rule may only become active after a
human maintainer has seen the baseline/trial regression comparison and
explicitly said yes, by name, to that specific candidate. No batch
approvals, no defaults, no "looks fine, approving all of these."
