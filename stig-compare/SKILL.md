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
never silently disappears: it becomes a `validation_failures.jsonl` entry
and, for matching/semantic decisions, gets one retry before the row is
marked `Cannot Assess` / rejected. Do not try to work around a validation
failure by inventing content that isn't actually in the evidence you were
given — fix your answer using only what the request supplied, or leave the
row for human review.

One designed exception to "never proceed past a non-zero exit code": step 5
below uses `finalize` exit code `4` (refused — pending matching/semantic
work) as the retry loop's expected continue signal, not a failure. That
exception is scoped exactly to that loop and its documented round cap —
every other non-zero exit code, anywhere in any mode, must still be
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

4. **Answer structuring and matching requests, then resolve — repeat while
   there is new work, capped at 2 rounds.** After `start` (and after every
   `resolve`), `runs/<timestamp>/structuring_requests.jsonl` and
   `matching_requests.jsonl` may contain pending records (a record already
   answered in an earlier round is never rewritten — only the newly
   appended ones need answers this round):
   - For each record in `structuring_requests.jsonl` you have not yet
     answered: read the file named by that record's `instructions_file`
     (`prompts/structuring.md`), follow it exactly, and produce one JSON
     object per record. Append each response as one line to
     `structuring_responses.jsonl` in the run directory.
   - For each record in `matching_requests.jsonl` you have not yet
     answered: read its `instructions_file` (`prompts/matching.md`), follow
     it, and append one JSON object per line to `matching_responses.jsonl`.
   - Run `python scripts/pipeline.py resolve --run-dir runs/<timestamp>`.
     A non-zero exit code must be surfaced, not worked around.
   - `resolve` prints counts including `retries_pending` and regenerates
     `matching_requests.jsonl` with newly-appended records when a row was
     just structured or a matching answer needs a retry (bad/unverifiable
     quote, rule not in the shortlist, etc. — the `previous_errors` field on
     the retry record explains why). If `retries_pending > 0`, or either
     `*_requests.jsonl` file grew, go back to the top of this step and
     answer only the new records, then `resolve` again. Stop once a
     `resolve` call reports nothing new, or after 2 rounds total — whichever
     comes first. (Because every response line is fingerprinted, replaying
     an already-answered line is always a safe no-op, so accumulating
     answers across rounds in the same `*_responses.jsonl` file is fine.)

5. **Answer semantic requests — same retry-loop shape as step 4, capped at
   2 rounds, and never with `--allow-pending` inside the loop.** If
   `runs/<timestamp>/semantic_requests.jsonl` doesn't exist after step 4,
   there is nothing to answer — every match in this run was decided
   deterministically; skip straight to step 6. Otherwise, loop:
   - For each record in `semantic_requests.jsonl` you have not yet
     answered (on a second round, that means the newly-appended records
     carrying `retry: true` / `previous_errors`): read its
     `instructions_file` (`prompts/semantic_compare.md`), follow it, and
     append one JSON object per line to `semantic_responses.jsonl`.
   - Run `python scripts/pipeline.py finalize --run-dir runs/<timestamp> --no-report`
     — **without** `--allow-pending`.
     - Exit `0`: every matching/semantic pair now has a real resolution —
       the two-strike protocol already turns a second bad retry into an
       honest `Cannot Assess`/`llm-output-rejected` finding automatically,
       inside this same call, with no need for `--allow-pending`. Stop
       looping; `final.json` is ready for step 6.
     - Exit `4` (prints `pending matching=…/pending semantic=…`): this is
       this loop's designed continue signal (see the hard-rules note
       above), not a failure. It means at least one pair only has a
       strike-1 rejection queued for retry so far — check the
       newly-appended `retry: true` record in `semantic_requests.jsonl`
       and the new entry in `validation_failures.jsonl` for why. If you
       are under 2 rounds, go back to the top of this step and answer only
       the new retry records. **Do not reach for `--allow-pending` here**
       — doing so before the retry has been given its second chance would
       silently and permanently sweep an answerable pair into a
       `semantic-pass-not-run` finding that falsely claims the semantic
       pass never ran.
     - Any other non-zero exit must be surfaced per the hard rules — do
       not loop past it.
   - If you reach 2 rounds and `finalize --no-report` (still without
     `--allow-pending`) is still refusing, that means something was never
     answered at all (not merely retried and rejected twice) — run it once
     more with `--allow-pending` added (keep `--no-report`) so the
     genuinely-unanswered pair is honestly marked `*-pass-not-run` /
     `human_review_needed: true` instead of being left in limbo. This is
     the only place before step 6 where `--allow-pending` may be used, and
     only as this last resort after both rounds are exhausted.

6. **Dispatch the skeptical validator, then finalize for real.**
   - The `final.json` produced by step 5's last `finalize` call already
     has, for every finding (deterministic or semantic), exactly the
     evidence shape `prompts/validator.md` expects: `finding_id`, `row_id`,
     `rule_id`, `verdict` (the claim being tested), `finding_type`,
     `observation`, `company_row` (`original_company_text` +
     `source_reference` only), and `official_rule` (`rule_id`/`title`/
     `check_text`/`expected_value` — deliberately no `fix_text`/`severity`).
   - For every finding in `final.json` whose `finding_type` is not `null`
     (a semantic-comparison finding — deterministic findings, where
     `finding_type` is `null`, do not go through the skeptic), dispatch the
     skeptical validator **using the Agent tool**, as an isolated subagent
     with no access to this conversation's reasoning. Give that subagent
     ONLY: the contents of `prompts/validator.md`, and the finding's raw
     evidence (`finding_id`, `row_id`, `rule_id`, `verdict`, `finding_type`,
     `observation`, `company_row`, `official_rule`) — **never** the first
     pass's `interpretation`, and never anything from your own earlier
     matching/semantic reasoning. You may batch multiple findings into one
     subagent dispatch, but the subagent itself must be fresh and isolated
     — it forms its own conclusion from the raw evidence, not from what the
     first pass already decided. Its job is to try to DISPROVE the finding
     (misquotes, wrong-record comparisons, meaning-changing paraphrase,
     formatting-only differences misclassified as semantic) and answer
     `{"finding_id": "...", "outcome": "upheld | refuted | undetermined",
     "reason": "..."}`. Append one such JSON object per line to
     `skeptic_responses.jsonl`.
   - Run `python scripts/pipeline.py finalize --run-dir runs/<timestamp> --allow-pending`
     **one final time — this is the only `finalize` call in the whole
     compare-mode flow that omits `--no-report`, and the only one that
     unconditionally carries `--allow-pending`.** By this point step 5 has
     already given every matching/semantic retry its full 2 rounds, so
     `--allow-pending` here cannot prematurely sweep anything answerable —
     it only (a) merges the skeptic outcomes (`disputed`,
     `skeptic.outcome`/`skeptic.reason`) into the findings, (b) recomputes
     `confidence`/`human_review_needed`, and (c) renders `report.html`.
     Because responses are fingerprinted, calling `finalize` again here is
     always safe. A non-zero exit code (e.g. exit 3 if coverage accounting
     doesn't add up) must still be surfaced, not silently retried past.

7. **Present the results.** Report, in this order:
   1. Warnings — everything in `final.json["warnings"]` (extraction
      warnings, rule conflicts, dropped duplicate findings, contradictory
      verdicts, low-coverage red banners). Lead with these.
   2. Coverage — `final.json["coverage"]`: how many company rows were
      matched/ambiguous/unmatched/ignored/unresolved, and how many official
      rules were addressed/unaddressed.
   3. The report path: `runs/<timestamp>/report.html`. It is
      self-contained (no network calls) — open it directly from disk.
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
