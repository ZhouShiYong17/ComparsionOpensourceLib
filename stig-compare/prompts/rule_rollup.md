# Brief: rule rollup — joint assessment of one official row across records

You are a subagent in the stig-compare skill. Your dispatch names the run
directory, ONE official row that two or more records matched (its line in
`runs/<ts>/official_rows.jsonl`), those records (lines in
`runs/<ts>/proposed.jsonl`), and their finding shards
(`runs/<ts>/findings/F-*--<official_row_id>.json`). Read everything COMPLETE.

## Strict rules
- Use ONLY what you read from the named files.
- **Your rollup may disagree with per-record verdicts — that disagreement is
  surfaced as a warning in the report; it NEVER overwrites a per-record
  finding.** Do not soften your joint judgment to agree.
- `contributing_record_ids` must echo exactly the record ids in your dispatch
  (any order, no extras, no omissions).
- Write the shard with the Write tool, single-line compact JSON, exact enum
  spellings below.
- Final message: ONLY `{"unit_id": "...", "status": "ok"|"failed",
  "counts": {...}}` (+ `"errors"` when failed). No prose, no cell content.

## Task

The core question: **taken TOGETHER, do these records satisfy this official
requirement?** A requirement split across several rows may be jointly covered
even though each row alone looks partial — or the rows may contradict each
other.

Write `runs/<ts>/rollups/RU-<official_row_id>.json` — a single line:

```
{"rollup_id": "RU-<official_row_id>", "official_row_id": "...",
 "display_id": "..." | null,
 "contributing_record_ids": [...],
 "joint_verdict": "Compliant" | "Deviating" | "Incomplete" | "Ambiguous" | "Cannot Assess",
 "coverage_of_requirement": "fully-covered" | "partially-covered" | "conflicting",
 "reasoning": "<your own words>",
 "confidence": "High" | "Medium" | "Low",
 "human_review": true|false}
```

Counts: `{"records": N}`.
