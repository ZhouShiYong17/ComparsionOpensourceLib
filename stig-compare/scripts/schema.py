"""Single home for every load-bearing enum and batch/chunk constant.

Every enum here is a vocabulary the LLM chooses from; Python code may route
on these values (copy, count, gate) but must never derive them. The numeric
constants are size arithmetic only — chunking and batching bound request
size, they never filter content by relevance.
"""

# ---- verdicts and finding vocabulary (LLM-chosen) -------------------------

VERDICTS = {"Compliant", "Deviating", "Incomplete", "Ambiguous",
            "Cannot Assess"}
CHANGE_TAGS = {"omitted", "contradicted", "weakened", "strengthened",
               "materially-changed"}
CONFIDENCES = {"High", "Medium", "Low"}
ALIGNMENT_RELATIONS = {"identical", "equivalent", "differs",
                       "company-missing", "official-missing"}
CLAIM_CONSISTENCY = {"consistent", "contradicted", "no-claim"}

# ---- matching (LLM-chosen) ------------------------------------------------

MATCH_DECISIONS = {"match", "none", "ambiguous"}

# ---- validation pass (LLM-chosen) -----------------------------------------

VALIDATION_OUTCOMES = {"upheld", "refuted", "revised", "needs-human"}

# ---- rule rollup (LLM-chosen) ---------------------------------------------

ROLLUP_COVERAGE = {"fully-covered", "partially-covered", "conflicting"}

# ---- extraction / interpretation vocabulary (LLM-chosen) ------------------

CANONICAL_DATA_FIELDS = [
    "stig_description", "stig_objective_or_requirement",
    "stig_command_or_value", "company_approved_setting_or_expected_value",
    "observed_value_or_evidence", "company_compliance_claim",
    "company_severity", "remarks_or_justification"]

MAPPING_TARGETS = set(CANONICAL_DATA_FIELDS) | {"other"}
TABLE_CLASSIFICATIONS = {"stig_relevant", "irrelevant", "uncertain"}
IRRELEVANT_REASONS = {"instructions", "general-info", "toc", "signoff",
                      "other"}
DISPOSITIONS = {"record", "separator", "continuation"}
CLAIM_READINGS = {"comply", "deviation", "unclear", "none"}
COLUMN_ROLES = {"id", "title", "severity", "check", "fix", "expected",
                "other"}

# ---- response kinds (consumed_responses.json bookkeeping) -----------------

RESPONSE_KINDS = ("official_structure", "table_mapping", "interpretation",
                  "scoping", "adjudication", "sweep", "comparison", "rollup",
                  "validation")

# ---- batch / chunk constants (size arithmetic, never semantic) ------------

STRUCTURE_SAMPLE_ROWS = 15       # official-structure pass sample size
TABLE_MAPPING_SAMPLE_ROWS = 15   # company table-mapping pass sample size
INTERPRETATION_CHUNK_ROWS = 40   # rows per interpretation request
SCOPING_RECORD_BATCH = 8         # company records per scoping request
SCOPING_OFFICIAL_CHUNK_BYTES = 60_000   # official corpus chunk budget
SWEEP_RECORD_BATCH = 8           # records per reverse-sweep request
COMPARISON_MAX_BYTES = 120_000   # comparison request split threshold
ROLLUP_MAX_BYTES = 120_000       # rollup request split threshold
