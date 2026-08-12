---
name: stig-compare
description: Compare a company STIG submission (any format — Excel, Word, CSV,
  mixed narrative/tables) against an official STIG file (CSV/JSON/Excel) and
  generate a self-contained HTML comparison report. Fully LLM-driven — the
  executing agent and its subagents read, structure, match, compare, validate,
  and render; no shipped code. Use when the user wants to check a STIG
  submission, compare STIG files, mentions STIG compliance review, wants to
  submit feedback on a comparison report, or wants a past result re-evaluated
  after feedback.
---

# stig-compare (v0.4.0)

You (the executing agent) and your subagents ARE the pipeline. This skill is
instructions only: subagent briefs in `prompts/`, one HTML template in
`templates/`. There is no script to run and no parser to maintain.

Three modes: **Compare**, **Feedback**, **Re-evaluate**.

## Hard rules (every mode, no exceptions)

1. **Never write code into the repo, and never write a parser at all.** When a
   binary file (.xlsx/.docx) or a bulk CSV→JSONL conversion forces it, a
   transient python one-shot is allowed (inline `python -c` or a throwaway
   script in the session scratchpad — transport only, zero decisions, deleted
   context the moment it ran). Always `python`, never `python3`. If it fails:
   fall back to Reading the file directly, or ask the user for a CSV/text
   export. Never "fix" ingestion by writing more code.
2. **A cell is atomic.** A comma or newline inside a cell is content, never a
   split point. Decomposing a multi-requirement cell is only ever an LLM
   decision made in a semantic pass, and the original cell stays preserved.
3. **Stage results never transit your context.** Subagents Write their own
   shards and return only `{unit_id, status, counts}`. You merge shards by
   shell concatenation. You never re-type, summarize, or relay row content.
4. **Never two writers, one file.** Every shard path contains its unit id;
   parallel subagents never share an output file.
5. **Two-strike rule.** A malformed/incomplete subagent result gets exactly
   one re-dispatch with the errors named. A second failure settles the unit as
   a visible status in `runs/<ts>/statuses.jsonl`
   (`llm-output-rejected` | `extraction-failed` | `unresolved`) — a status is
   never a verdict, and you never patch or invent the answer yourself.
6. **Report only what the artifacts contain.** No global confidence
   statements; findings speak through their own verdict/confidence/validation
   fields. Surface every warning; never proceed silently past a count
   mismatch or failed merge.
7. To dispatch a unit: tell the subagent to first Read its brief (absolute
   path of the named `prompts/*.md` file) and follow it, then give a
   `## Dispatch` block with the unit's specifics (run dir, unit id, absolute
   file paths, line ranges, mode flags, extra data pasted verbatim). Run
   independent units in parallel, a handful of subagents at a time.

8. **Batch dispatches to keep their number sane.** One subagent may carry
   several units as long as it writes ONE SHARD PER UNIT (rule 4 still holds).
   Batch 4–6 records per subagent for adjudication, per-record comparison,
   validation, and report fragments. Keep a unit alone when it is genuinely
   large: a record matching several official rows must be compared in its own
   subagent so the rules are judged jointly. Rough scale for a 200-rule STIG
   and a 40-row submission: ~2 ingest, ~6 structure/index, ~3 triage, ~1–2
   interpretation, ~5 scoping, ~8 adjudication, ~2–4 sweep, ~10 comparison,
   ~8 validation, ~8 fragments — on the order of 50–60 dispatches, not 120.

9. **Find lines by formula first, Grep second.** Ids encode position:
   `OR-<section>-r<N>` is line `N-1` of `official_rows.jsonl` when the ingest
   skipped no rows, and `proposed.jsonl` is in table/row order. Verify the
   formula once (Grep one id, check the line number), then compute the rest.
   If ingest reported skipped blank rows, Grep the ids once with `-n` and keep
   the compact id→line map instead.

## Id scheme (deterministic — re-running a unit overwrites its shard)

- Official row: `OR-<sheet-slug|csv|json>-r<row_number>` (+ human `display_id`
  from the ID column when one exists).
- Record: `CR-t<table_index>-r<row_index>[-s<sub>]`.
- Finding: `F-<record_id>--<official_row_id>`. Rollup: `RU-<official_row_id>`.
- Validation: `V-<finding_or_rollup_id>`.

## The two structures

Everything downstream of ingest reads one of two intermediate structures, both
built by agents reading the documents:

- **Official Structure** (step 2) — the faithful structured representation of
  the official STIG: every rule row complete and verbatim, plus what each
  column means, plus a verbatim index for scoping.
- **Proposed Structure** (steps 3–4) — the normalized view of the company
  submission: one line per proposed record, whatever shape the source had.

Both obey the same law: **they add meaning on top of the original, never in
place of it.** Each record and each rule row carries its complete verbatim
source content and provenance (file, sheet/section, row, cell), so a structure
can never quietly destroy information, and any agent that doubts an
interpretation can read the original text in the same line. They exist to help
agents reason — never as a rigid schema the next submission must fit.

This is enforced, not trusted: the **preservation gate** (step 4b) diffs every
record's cells against the ingest dump byte for byte and names any row that was
altered, invented, or lost. The run does not proceed to matching until it
passes.

## Compare mode

### 0 · Intake
Exactly two paths: official (`.csv`/`.json`/`.xlsx`) and submission (any
format). Don't guess locations — ask if missing. Create `runs/<timestamp>/`
(e.g. `runs/2026-08-12T143205/`) under the package root. Write
`manifest.json`: both paths, SHA-256 (`Get-FileHash`), start time,
skill_version from `VERSIONS.json`.

### 1 · Ingest (subagent; transport, zero decisions)
Dispatch one ingest subagent per input file (no brief file — give it these
instructions verbatim, plus paths and the id scheme):

> Convert the file losslessly to run artifacts. Official →
> `official_rows.jsonl`: one compact single-line JSON object per data row
> `{"official_row_id","sheet_or_section","row_number","headers","cells",
> "provenance":{"source_file"}}` — cells verbatim, positional, blank rows
> skipped, no interpretation, no header mapping. Submission →
> `submission_dump.json`: `{"tables":[{"table_index","sheet_or_section",
> "preceding_narrative","header_row","rows":[{"row_index","cells","merged"}]}],
> "narratives":[...]}` — every table, paragraph and cell verbatim.
> For `.xlsx`/`.docx` use a transient python one-shot (openpyxl /
> python-docx); for `.csv` a transient python csv→JSONL one-shot (the csv
> module keeps quoted cells whole); for `.json`/text you may Read and convert
> directly. Never save code anywhere. A cell is atomic. On any failure:
> report `{"status":"failed","errors":["<ExceptionTypeName>"]}` — the
> exception TYPE only, never document content — and stop. Return only
> `{"unit_id","status","counts":{"rows"|"tables":N}}`.

On failure: fall back once (agent Reads the raw file and writes the artifact
directly, if the format is readable text); otherwise ask the user for an
export. Record irrecoverable content as `extraction-failed` in
`statuses.jsonl` — it is counted, never dropped silently.

### 2 · Official Structure (brief: `prompts/official_structure.md`)
Builds the **Official Structure** — the faithful structured representation of
the official STIG: `official_rows.jsonl` (every row complete and verbatim) plus
`official_structure.json` (what each column means) plus `index.jsonl` (the
verbatim title + requirement text of every rule, for scoping). It adds
meaning ON TOP of the rows; it never replaces, reduces, or reorders them.

Count lines per sheet (`Get-Content official_rows.jsonl | Measure-Object -Line`
plus Grep on sheet slugs). Dispatch Mode A per sheet, then Mode B per ≤40-row
chunk (pass each chunk its sheet's Mode-A shard content). Merge:
`Get-Content runs/<ts>/index/*.jsonl | Set-Content runs/<ts>/index.jsonl`.
Check: index line count = official row count; mismatch → find the gap,
re-dispatch that chunk (two-strike).

### 3 · Submission triage (brief: `prompts/submission_triage.md`)
First half of building the Proposed Structure: decide what in this submission
is STIG-relevant at all, and what each column means. One unit per table in
`submission_dump.json` (or per section when ingest fell back to raw text).
Merge triage shards → `runs/<ts>/table_triage.jsonl`. `irrelevant` tables are
excluded from interpretation (their row counts go to coverage as
`ignored_irrelevant_table`); `stig_relevant` and `uncertain` proceed.

### 4 · Proposed Structure (brief: `prompts/row_interpretation.md`)
Builds the **Proposed Structure** — `proposed.jsonl`, the normalized view of
the company submission that every later pass reads. One line per proposed
record, whatever shape the source document had.

Its purpose is to help you REASON, not to become a second source of truth:
each record carries the COMPLETE verbatim row (cells, continuation cells,
header row, narrative, provenance) alongside the interpreted fields, so
normalization can never destroy information. A field the interpreter could not
fill is simply absent; the evidence is still in the record. Anything a later
agent doubts can be traced back to the original file, sheet, row, and cell.

One unit per ≤40-row chunk of each surviving table (pass the table's triage
shard content). Merge: `accounting/*.jsonl` → `accounting.jsonl`,
`proposed/*.jsonl` → `proposed.jsonl`, `triage/*.json` → `table_triage.jsonl`.

### 4b · Preservation gate (mandatory — never skip, never work around)
Counting rows proves nothing about their content. Run this byte-equality check
before any matching begins. It compares every record's cells against the dump
they came from, and proves every dumped row is either recorded, legitimately
excluded, or named. It reads bytes and makes no judgments.

```powershell
$run = "runs/<ts>"
$dump = Get-Content "$run\submission_dump.json" -Raw | ConvertFrom-Json
$src = @{}
foreach ($t in $dump.tables) { foreach ($r in $t.rows) { $src["$($t.table_index)|$($r.row_index)"] = ($r.cells -join [char]31) } }
$triage = @{}
foreach ($l in Get-Content "$run\table_triage.jsonl") { if ($l.Trim()) { $o = $l | ConvertFrom-Json; $triage["$($o.table_index)"] = $o.classification } }
$excluded = @{}
foreach ($l in Get-Content "$run\accounting.jsonl") { if ($l.Trim()) { $o = $l | ConvertFrom-Json
  if ($o.disposition -ne "record") { $excluded["$($o.table_index)|$($o.row_index)"] = $o.disposition } } }
$seen = @{}; $n=0; $altered=0
foreach ($l in Get-Content "$run\proposed.jsonl") { if (-not $l.Trim()) { continue }
  $rec = $l | ConvertFrom-Json; $n++
  $k = "$($rec.table_index)|$($rec.row_index)"; $seen[$k] = $true
  if (-not $src.ContainsKey($k)) { Write-Output "NO-SOURCE $($rec.record_id)"; $altered++; continue }
  if (($rec.cells -join [char]31) -ne $src[$k]) { Write-Output "ALTERED   $($rec.record_id)"; $altered++ } }
$lost = @(); $ignored = 0; $untriaged = @()
foreach ($k in $src.Keys) { $ti = $k.Split('|')[0]
  if (-not $triage.ContainsKey($ti)) { $untriaged += $k; continue }
  if ($triage[$ti] -eq 'irrelevant') { $ignored++; continue }
  if ($seen.ContainsKey($k) -or $excluded.ContainsKey($k)) { continue }
  $lost += $k }
foreach ($k in ($untriaged | ForEach-Object { $_.Split('|')[0] } | Sort-Object -Unique)) { Write-Output "NOT-TRIAGED table $k" }
foreach ($k in $lost) { Write-Output "LOST source row $k" }
Write-Output "preservation: records=$n altered=$altered lost=$($lost.Count) ignored_irrelevant=$ignored untriaged_rows=$($untriaged.Count)"
```

Required outcome: `altered=0`, `lost=0`, `untriaged_rows=0`. Anything else:

- `ALTERED` / `NO-SOURCE` — the interpreter rewrote or invented a row. Re-run
  that chunk (two-strike). NEVER hand-patch the record yourself.
- `LOST` — a row in a relevant table produced no record and no
  separator/continuation disposition. Re-run its chunk; if it fails twice,
  record it as `extraction-failed` in `statuses.jsonl` so coverage counts it.
- `NOT-TRIAGED` — a table was never triaged. Go triage it; an untriaged table
  is invisible content, not excluded content.

Do the same for the official side: `index.jsonl` line count must equal
`official_rows.jsonl` line count, and every `official_row_id` in the index must
exist in the rows file. The index is a lookup aid — the complete rows are what
adjudication and comparison read.

### 5 · Match scoping (brief: `prompts/match_scoping.md`)
Batches of ~8 records (line ranges of `proposed.jsonl`) × the full
`index.jsonl`. Merge → `nominations.jsonl`. Every record must appear (as a
nomination or a `no-candidates` line) — count and verify.

### 6 · Adjudication (brief: `prompts/match_adjudication.md`)
One unit per record with ≥1 nomination: pass its `proposed.jsonl` line number
and its nominated rows' `official_rows.jsonl` line numbers (locate lines by
Grep on the ids; keep only line numbers in context). `sweep_round: false`.
Merge shards → `matches.jsonl`.

### 7 · Reverse sweep, once (brief: `prompts/sweep.md`)
Eligible records: adjudicated `none` or `ambiguous`, plus `no-candidates`
records. Addressed ids: Grep `-o` `"official_row_id":"[^"]*"` over
`matches.jsonl` selections → unique list. Slice `official_rows.jsonl` into
line ranges of roughly ≤60KB (file bytes ÷ line count → lines per slice).
Dispatch one sweep unit per slice; merge proposals. Then re-run step 6 for
each record that gained proposals, with `sweep_round: true` — same shard
paths, overwriting `none` decisions. The sweep never repeats.

### 8 · Comparison (brief: `prompts/comparison.md`)
One unit per record whose decision is `match`. Pass: record line number,
match shard path, every matched row's line number, and any precedent lines —
for each matched row, Grep `feedback/precedents.jsonl` (package root) for its
`display_id` (fallback: `official_row_id`) and paste matching lines verbatim.
If a unit's combined rows exceed ~120KB, split it into parts, warn in
`statuses.jsonl`, and force `human_review` on its findings. Merge findings
shards → `findings.jsonl`.

### 9 · Rollup (brief: `prompts/rule_rollup.md`)
Official rows with ≥2 matching records (count over `matches.jsonl`
selections). One unit each. Merge → `rollups.jsonl`. A joint verdict that
differs from a contributing finding is a warning line in `statuses.jsonl`,
never an overwrite.

### 10 · Validation (brief: `prompts/validation.md`)
EVERY finding and rollup, in batches of ~5 per isolated subagent. The
validator re-derives its own verdict from the evidence before reading the
claim, and checks every quote in-context against the decoded cells. An
`upheld` whose `independent_verdict` differs from the claimed verdict is
invalid — re-dispatch once (two-strike). A `refuted` with
`"wrong_match": true` sends that record through ONE targeted re-round: fresh
scoping against still-unaddressed rows, then adjudication and (if matched)
comparison + validation for the new pair; the old finding keeps its
`refuted` validation and shows as disputed. Merge → `validations.jsonl`.

### 11 · Coverage (mechanical counting — you, with shell tools)
Count with Grep count-mode patterns over the merged artifacts (shards are
compact JSON — no spaces: `"decision":"match"`), `Measure-Object -Line`, and
`Sort-Object -Unique` for distinct ids. Buckets MUST sum; a mismatch means a
lost unit — find it before proceeding. Write `coverage.json`:

- company records: `matched` / `ambiguous` / `unmatched` / `unresolved`
  (two-strike statuses); company rows additionally:
  `separator` / `continuation` / `ignored_irrelevant_table` /
  `extraction_failed`. Identity: every record in exactly one bucket; every
  dumped row accounted.
- official rows: `addressed` (distinct ids in match selections) /
  `unaddressed` / `multi_matched_row_ids`.
- Red-banner flag when `extraction_failed + unresolved` is a material share
  of the submission.

### 12 · Report (brief: `prompts/report_render.md`)
Mode F units: batches of ~5 findings/rollups → fragments. Mode A unit: one
assembler subagent builds the small sections from `coverage.json` /
`manifest.json` / `table_triage.jsonl` / `statuses.jsonl`, concatenates
fragments by shell, fills `templates/report_template.html` by literal
`.Replace`, writes `runs/<ts>/report.html`, and verifies no placeholder
remains and every fragment's `data-fid` is present.

### 13 · Present
In this order: (1) warnings and statuses — lead with them; (2) coverage
numbers, calling out `uncertain` tables and anything unresolved or
extraction-failed; (3) the report path `runs/<ts>/report.html` (self-contained,
opens from disk); (4) the feedback offer: mark findings in the report, click
"Export feedback", hand back the downloaded `feedback.json`. Never lead with
or add a confidence statement about the comparison as a whole.

## Feedback mode

Input: a `feedback.json` (from the report's Export button) and the run
directory it came from. For each item:
1. Locate the finding/rollup shard by `finding_id` in that run. Unknown id →
   surface it to the user; never drop it silently.
2. Write `feedback/FB-<timestamp>-<n>.json` (package root): the item verbatim
   + the complete finding shard as `snapshot` + the run's manifest core.
3. Append one line to `feedback/precedents.jsonl`:
   `{"feedback_id","display_id","official_row_id","official_sha256",
   "classification","comment","prior_verdict"}` (values from the snapshot;
   comment VERBATIM — reviewer text is never parsed, summarized, or edited).
Report counts: stored / precedents / errors. Future comparisons of the same
official rows receive these lines verbatim; the comparing LLM judges
applicability (`precedents_applied`).

## Re-evaluate mode

The user says a result is wrong ("this row was matched incorrectly", "this
column means X", "these two requirements belong together"). No new run:
1. Identify the affected unit ids (records, findings, rollups) from what the
   user names — ask only if genuinely ambiguous.
2. Re-dispatch ONLY the affected stage subagents with the user's feedback
   quoted VERBATIM in the dispatch block ("Reviewer feedback on this exact
   unit — weigh it as strong context"). Same unit ids → same shard paths →
   overwrite in place.
3. Cascade only where the answer changed: new match → comparison →
   validation → fragment; changed column meaning → re-interpret that table's
   chunks, then only its records' downstream stages.
4. Re-merge the touched stage files, recompute `coverage.json`, re-render the
   touched fragments, re-run assembly. Present what changed, verbatim before
   → after, and store the feedback as a precedent (Feedback mode steps 2–3).

## Cost and batch guidance

~15 sample rows for structure/triage; ≤40-row chunks; ~8-record scoping
batches; ~60KB sweep slices; one comparison unit per matched record (~120KB
cap); ~5-finding validation and fragment batches. For a 300-rule STIG and a
100-row submission expect roughly: 1–2 ingest + ~8 structure/index + a few
triage + ~5 interpretation + ~13 scoping + ~40–60 adjudication/comparison +
sweep slices + ~25 validation + ~15 fragment subagents. Subagent contexts are
disposable — yours is the scarce resource; if a step tempts you to load a
corpus into your own context, dispatch a subagent instead.
