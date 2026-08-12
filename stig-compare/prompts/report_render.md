# Brief: report rendering — fragments and assembly

Two modes. Both copy evidence VERBATIM from artifacts they Read themselves —
an altered quote in the report is a defect. HTML-escape cell text
(`& < > " '`) but never reword, trim, or "clean" it.

## Mode F — finding/rollup fragments (batch of a few per subagent)

Dispatch names the run directory and a batch of finding/rollup ids. For each,
Read its shard, its validation shard (`runs/<ts>/validations/V-<id>.json`),
and the complete record + official row lines it references. Write ONE file
per finding: `runs/<ts>/report_fragments/<finding_or_rollup_id>.html`.

Fragment structure for a finding (`F-…`):

```
<article class="finding" data-fid="<finding_id>" data-verdict="<verdict>"
         data-confidence="<confidence>" data-review="<true|false>">
  <div class="badges">…</div>          <!-- see badge list -->
  <div class="ids">…</div>             <!-- finding id, record id, display_id/official row id -->
  <div class="evidence two-col">
    <div class="company">…</div>       <!-- COMPLETE company row: header row + all cells + continuation cells + narrative, verbatim -->
    <div class="official">…</div>      <!-- ALL official columns, header: cell, verbatim -->
  </div>
  <blockquote class="hl-company">…</blockquote>   <!-- headline row_quote -->
  <blockquote class="hl-official">…</blockquote>  <!-- headline official_quote -->
  <table class="alignment">…</table>   <!-- field_alignment rows: company_ref | relation | company_quote | official_column | official_quote -->
  <section class="rationale">Match rationale, Semantic differences, Reasoning</section>
  <section class="note">Interpretation note (labeled "not evidence") + record notes</section>
  <section class="validation">outcome, independent verdict, reason, evidence quote</section>
  <div class="fb"><select class="fb-select">…7 options…</select>
       <input class="fb-comment" placeholder="comment"></div>
</article>
```

Badges (emit only those that apply): the verdict; the confidence; `REVISED by
validation — first pass: <verdict>` when the validation outcome is `revised`
(display the revised verdict as the effective one in `data-verdict`);
one badge per `change_analysis` tag; `HUMAN REVIEW NEEDED` (LLM flag OR
validation `needs-human`/`refuted`/`revised`); `DISPUTED — validation
refuted`; `company-declared-deviation` (claim reading was `deviation`);
`claim-contradicted`; `sweep-originated`.

Rollup fragments (`RU-…`): same shape with class `rollup`, showing the
official row complete, the contributing record ids, joint verdict +
coverage-of-requirement badges, reasoning, validation panel, feedback row.
Add a `rollup-differs` warning badge when the joint verdict differs from any
contributing finding's effective verdict.

Feedback select options, exactly:
`(select) | correct | incorrect | wrong match | missed difference |
not meaningful | wrong classification | other` (first option value `""`).

Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
"counts": {"fragments": N}}`. No prose.

## Mode A — assembly (one subagent, runs after all fragments exist)

Dispatch names the run directory. Read the SMALL artifacts only:
`manifest.json`, `coverage.json`, `table_triage` shards, `warnings.jsonl`
(if present), validation counts. NEVER read the fragment files or the big
corpora — fragments are concatenated by shell, not through your context.

1. Build the small sections as HTML strings: Warnings (FIRST, one entry per
   warning; red banner when coverage says too much content was not compared),
   Dashboard (tiles: the five verdicts, Unmatched rows, Unresolved,
   Unaddressed rules; then the company/official coverage tables incl.
   `multi_matched_row_ids`), Table triage (index, location, classification,
   reason, grouping, rows), Leftovers (ambiguous matches, unmatched records,
   unresolved/rejected units, unaddressed official rules — ids and verbatim
   first cells only).
2. Concatenate fragments mechanically (PowerShell):
   `Get-Content runs/<ts>/report_fragments/F-*.html -Raw | Set-Content runs/<ts>/_findings.html`
   and likewise `RU-*.html` → `_rollups.html`.
3. Assemble from the template with literal ordinal replacement (never regex).
   The template's markers are exactly: `<!--TITLE-->` (short run title),
   `<!--META-->` (header lines: files, SHA-256s, started, skill version),
   `<!--WARNINGS-->`, `<!--DASHBOARD-->`, `<!--TRIAGE-->`, `<!--FINDINGS-->`,
   `<!--ROLLUPS-->`, `<!--LEFTOVERS-->`, plus the JS meta slot — replace the
   literal string `/*RUN_META*/{}/*END_RUN_META*/` with the manifest JSON
   object (single line):
   ```powershell
   $t = [IO.File]::ReadAllText('templates/report_template.html')
   $t = $t.Replace('<!--TITLE-->', ...).Replace('<!--META-->', ...)
        .Replace('/*RUN_META*/{}/*END_RUN_META*/', <manifest JSON, one line>)
        .Replace('<!--WARNINGS-->', ...).Replace('<!--DASHBOARD-->', ...)
        .Replace('<!--TRIAGE-->', ...)
        .Replace('<!--FINDINGS-->', [IO.File]::ReadAllText('runs/<ts>/_findings.html'))
        .Replace('<!--ROLLUPS-->', ...).Replace('<!--LEFTOVERS-->', ...)
   [IO.File]::WriteAllText('runs/<ts>/report.html', $t)
   ```
   Write the section HTML strings to small temp files under the run dir and
   `ReadAllText` them into the Replace calls if they are long — do not build
   giant inline PowerShell string literals.
4. Verify: the output contains every fragment's `data-fid` (count them
   mechanically) and no `<!--` placeholder remains.

Final message: ONLY `{"unit_id": "assembly", "status": "ok"|"failed",
"counts": {"findings": N, "rollups": N}}`. No prose.
