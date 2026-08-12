# stig-compare v0.4.0 — Pure-skill, fully LLM-driven redesign

Status: approved 2026-08-12. Supersedes the pipeline/state-machine portions of
`2026-08-12-llm-first-comparison-design.md`; that spec's semantic vocabulary
(verdicts, change tags, claim readings, preference rules) is carried forward
verbatim into the new briefs.

## Mandate

The deliverable is a **skill, not a coded workflow**. The repo ships **zero
Python files** — no scripts/, no tests/, no pre-written parsers, no state
machine. Everything is `SKILL.md` orchestration instructions + subagent briefs
(`prompts/*.md`) + one static HTML report template (`templates/`). The
executing Claude and its subagents ARE the pipeline.

Runtime python is permitted only as a **transient one-shot** (inline command or
throwaway scratchpad script; `python`, never `python3`) when a binary file
(.xlsx/.docx) forces it, or to bulk-convert a large CSV to JSONL verbatim.
Transport only — zero decisions, run-and-discard, never saved into the repo.
If it fails: fall back to Reading the file directly or asking the user for an
export. Writing parser code into the repo is forbidden, always.

## Why (what v0.3.0 got wrong)

v0.3.0 made every semantic decision an LLM pass but kept a 13-module Python
state machine as the engine. Submissions differ in format every run, so the
shipped Python was the recurring failure point: scripts choke on a new shape,
the runtime agent writes MORE ad-hoc Python to patch them, code and tracebacks
flood the context window, and comparison quality collapses. The fix is not a
better parser — it is no shipped parser at all.

## Architecture (summary — SKILL.md is normative)

- Orchestrator = the skill-executing agent. Holds only ids/counts/paths.
  All heavy reading/reasoning happens in subagents (Agent tool).
- Artifacts are JSONL under `runs/<timestamp>/`, one compact single-line object
  per row/record/finding, fetched by id (locate line, Read it) — never
  whole-corpus loads.
- **Subagent I/O rule:** results never transit the orchestrator's context and
  are never concurrently appended to one file. Each subagent Writes its own
  per-unit shard under `runs/<ts>/<stage>/`; the orchestrator merges shards by
  shell concatenation.
- **Ids (deterministic, no hashing):** official `OR-<sheet|csv>-r<rownum>` +
  human `display_id`; records `CR-t<table>-r<row>[-s<sub>]`; findings
  `F-<record_id>--<official_row_id>`; rollups `RU-<official_row_id>`.
  Re-running a unit reproduces its id → shard overwritten in place, which is
  what makes targeted re-evaluation work.
- Stages: intake → transient ingest → official structuring (+ verbatim-text
  index; no gists ever) → submission structuring (triage → interpretation) →
  index scoping → full-row adjudication → one reverse sweep (none/ambiguous ×
  unaddressed) → joint comparison → rollup → validation (independent verdict
  first; in-context verbatim-quote firewall; wrong-match refutation triggers
  one targeted re-round) → coverage (mechanical counting) → sharded report
  fragments assembled into the static template.
- Feedback: verbatim audit shards + `feedback/precedents.jsonl` keyed by
  display_id (fallback official_row_id + official sha); applicability is
  always the comparing LLM's judgment. Re-evaluation re-runs only affected
  units and overwrites same-id shards. Replay/regression mode is retired.

## Locked semantic vocabulary (unchanged from v0.3.0)

- Verdicts: `Compliant | Deviating | Incomplete | Ambiguous | Cannot Assess`;
  orthogonal `human_review`; confidence `High | Medium | Low`.
- Change tags: `omitted | contradicted | weakened | strengthened |
  materially-changed`.
- Claim reading: `comply | deviation | unclear | none` (silence is `none`).
- Triage: `stig_relevant | irrelevant | uncertain` (irrelevant is the only
  excluding decision; prefer uncertain).
- Match decisions: `match` (multi-select, verbatim quotes both sides) |
  `none` | `ambiguous` — none/ambiguous beat a forced match.
- Field alignment: `identical | equivalent | differs | company-missing |
  official-missing`. Claim consistency: `consistent | contradicted | no-claim`.
- Validation outcomes: `upheld | refuted | revised | needs-human`; an uphold
  contradicting the validator's own independent verdict is invalid.
- Two-strike: one re-ask, then a visible status (`llm-output-rejected`,
  `extraction-failed`, `unresolved`) — never a verdict.

## Accepted limitations

- A cell is atomic: comma-splitting a cell is forbidden; decomposition of a
  multi-requirement cell is only ever an LLM decision, with the original cell
  preserved.
- Ambiguous matches get no comparison pass (surfaced in leftovers).
- Oversized joint comparisons are split with forced human review, warned.
- Precedents keyed by display_id travel across official file versions; files
  with no ID column fall back to positional `OR-` keys, which do not travel.
- Scanned/image-only submission content stops at ingest and is counted as
  `extraction-failed`, never silently dropped.
