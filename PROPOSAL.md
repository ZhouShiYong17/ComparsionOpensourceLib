# STIG Comparison Using Only Two Files

## 1. Objective

The objective is to compare a company STIG submission against the official STIG file, even when the company submission is a messy Word document and does not contain STIG IDs.

The comparison must work with only two files:

1. The official STIG file, in CSV or JSON format.
2. The company STIG submission, usually in Word table format.

No external search, registry, mapping library, or additional reference file is used.

## 2. Current Problem

Company STIG submissions are difficult to compare directly because:

- App teams submit Word files with inconsistent table structures.
- Different teams use different headings, grouping methods, and wording.
- Many rows do not contain an official STIG ID.
- Some rows describe a requirement but do not clearly show the actual system value.
- Some rows are grouped by severity, system area, or application component, but not by official STIG structure.
- The official STIG has structured fields, while the company Word file is often free-form or semi-structured.

Because of this, a direct row-to-row comparison is not possible.

## 3. Proposed Approach

The proposal is to keep accepting the company Word file as-is, then convert its contents into a simple internal structure before comparison.

This internal structure does not require app teams to change their files or provide STIG IDs. It is created during extraction from the Word document.

The LLM then compares:

- The normalized company structure extracted from the Word file.
- The official STIG file, which contains the official rule ID, title, check text, fix text, expected value, and severity.

The LLM matches by meaning, not by STIG ID.

## 4. Proposed Company STIG Structure

The proposed structure is a flexible extraction model. It is not asking app teams to use one fixed Word format.

The purpose is to take any Word table format and translate it into the same internal structure(json) before comparison.

We do not match by STIG ID, because the company file usually does not have it.

Instead, we match by meaning.

| Level | Field | Meaning |
|---|---|---|
| Context | `context_grouping` | The table name, section heading, severity group, system area, or other grouping used in the Word file |
| Level 1 | `stig_description` | A description of what the control is about, used for comparison with the official STIG. E.g (password policy)|
| Level 2 | `stig_objective_or_requirement` | The requirement or objective the row is trying to satisfy (e.g Enforce password history, maximum password age) |
| Level 3 | `stig_command_or_value` | The command, setting, parameter, validation method, or technical value used to verify the requirement |
| Level 4 | `company_approved_setting_or_expected_value` | The approved setting, expected value, baseline value, or required value stated by the company |

This structure can adapt to different Word formats. If a table is grouped by severity, `context_grouping` may be `High`. If a table is grouped by component, it may be `Database` or `Web Server`. If a table has no clear grouping, the value can be `Unknown`. The important point is that each row is still translated into the same four levels before matching.

Additional fields should also be preserved:

| Field | Meaning |
|---|---|
| `source_reference` | Page, table, and row number from the Word file |
| `original_company_text` | Exact original row text from the Word file |
| `observed_value_or_evidence` | Actual value, evidence, status, or comments if the company file provides them |

This matters because the LLM needs enough content to compare a company row against the official STIG rule text.

The most useful matching signals are:

- How the Word file grouped the row.
- What the row describes.
- What requirement or objective the row is addressing.
- What command, setting, parameter, or value is being checked.
- What approved setting or expected value the company states.
- What actual evidence or observed value is provided, if available.

## 5. End-to-End Workflow

### Step 1: Receive the two files

The input is:

- Official STIG CSV or JSON.
- Company Word submission.

The company Word file is not expected to contain STIG IDs.

### Step 2: Extract rows from the Word file

For each table row, preserve the original text and extract the useful fields.

Example Word table:

| Group | STIG Requirement | Description | Command to Verify | Approved Setting |
|---|---|---|---|---|
| High | Password reuse must be restricted | Database users should not reuse recent passwords | Run `SHOW PARAMETER password_reuse_max` | 9 or more |

Normalized company record:

| Field | Extracted Value |
|---|---|
| `context_grouping` | High |
| `stig_description` | Database users should not reuse recent passwords |
| `stig_objective_or_requirement` | Password reuse must be restricted |
| `stig_command_or_value` | `SHOW PARAMETER password_reuse_max` |
| `company_approved_setting_or_expected_value` | 9 or more |
| `observed_value_or_evidence` | Not provided |
| `source_reference` | Table 1, Row 1 |
| `original_company_text` | Full original row text from Word |

### Step 3: Compare against official STIG

The LLM compares the normalized company record against every official STIG rule.

It looks for alignment between:

| Company Structure | Official STIG Field |
|---|---|
| `context_grouping` | Severity, title, check text, fix text |
| `stig_description` | Rule title, check text, fix text |
| `stig_objective_or_requirement` | Rule title, check text |
| `stig_command_or_value` | Check text, expected value, fix text |
| `company_approved_setting_or_expected_value` | Expected value, check text, fix text |

### Step 4: Produce the comparison result

The LLM outputs a structured result:

| Field | Meaning |
|---|---|
| `matched_stig_id` | Official STIG ID found after matching, or `NONE` |
| `matched_stig_title` | Official STIG title |
| `official_expected_value` | Expected value from official STIG |
| `match_confidence` | High, Medium, Low, or None |
| `compliance_verdict` | Compliant, Non-Compliant, or Cannot Assess |
| `reason` | Short explanation of the match and verdict |
| `human_review_needed` | Yes or No |

## 6. What the LLM Can Do

The LLM can:

- Read both files in the same run.
- Extract structured meaning from messy Word tables.
- Preserve the original company text for auditability.
- Match company rows to official STIG rules using wording, setting names, commands, expected values, and severity.
- Assign the official STIG ID only after a match is found.
- Compare the company value or evidence against the official expected value.
- Identify unmatched official STIG rules.
- Identify company rows that do not match any official STIG rule.
- Flag weak, unclear, or duplicate matches for human review.

## 7. What the LLM Cannot Do

The LLM cannot:

- Search outside the two files.
- Use a hidden registry or external mapping table.
- Know a STIG ID if it is not derived from the official file.
- Prove compliance if the company row does not provide an actual value or evidence.
- Reliably match vague rows such as "password reviewed" or "logging checked."
- Treat severity alone as proof of a match.

If a row is too vague, the correct result is `Cannot Assess`, not a guessed pass.

## 8. Why This Is Feasible

This is feasible because the official STIG file already contains the complete rule set.

The LLM does not need external knowledge. It only needs to compare the company row content against the official STIG fields in the same prompt.

The hierarchy helps because it turns messy Word content into a consistent comparison shape:

- Level 1 captures the description or explanation from the company row.
- Level 2 captures the requirement or objective.
- Level 3 captures the command, setting, or technical value.
- Level 4 captures the company-approved setting or expected value.

This gives the LLM enough information to perform content-based matching and compliance comparison using only the two files.

## 9. Key Management Message

We are not asking app teams to learn STIG IDs or change their process immediately.

Instead, we are standardizing how we extract and interpret their existing Word files.

The official STIG remains the source of truth. The company Word file is normalized into a simple hierarchy, then matched against the official STIG in one LLM run.

This approach is practical, auditable, and honest about uncertainty: strong matches can be used, weak matches go to human review, and missing evidence results in `Cannot Assess`.
