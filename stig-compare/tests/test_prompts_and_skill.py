from pathlib import Path

import common

PKG = Path(__file__).resolve().parent.parent
PROMPTS = ["official_structure.md", "table_mapping.md",
           "row_interpretation.md", "match_scoping.md",
           "match_adjudication.md", "sweep.md", "comparison.md",
           "rule_rollup.md", "validation.md"]
RETIRED = ["canonicalize.md", "matching.md", "semantic_compare.md",
           "validator.md"]


def test_all_prompts_exist_with_strict_preamble():
    for name in PROMPTS:
        text = (PKG / "prompts" / name).read_text(encoding="utf-8")
        assert "STRICT RULES" in text, name
        assert "ONLY the evidence supplied" in text, name
        assert "VERBATIM" in text, name
        assert "retry" in text, name          # echo contract stated


def test_retired_prompts_gone():
    for name in RETIRED:
        assert not (PKG / "prompts" / name).exists(), name


def test_prompts_state_their_schemas():
    structure = (PKG / "prompts" / "official_structure.md").read_text("utf-8")
    for key in ["structure_id", "display_id_column", "column_roles", "notes"]:
        assert f'"{key}"' in structure
    table_mapping = (PKG / "prompts" / "table_mapping.md").read_text("utf-8")
    for key in ["table_index", "classification", "irrelevant_reason",
                "column_mapping", "context_grouping"]:
        assert f'"{key}"' in table_mapping
    interp = (PKG / "prompts" / "row_interpretation.md").read_text("utf-8")
    for key in ["chunk_id", "row_index", "disposition", "records",
                "sub_index", "fields", "field_provenance",
                "company_claim_reading", "interpretation_note",
                "separator_text"]:
        assert f'"{key}"' in interp
    scoping = (PKG / "prompts" / "match_scoping.md").read_text("utf-8")
    for key in ["scoping_id", "nominations", "record_id", "official_row_id"]:
        assert f'"{key}"' in scoping
    assert "NOT deciding matches" in scoping
    adjudication = (PKG / "prompts" / "match_adjudication.md").read_text("utf-8")
    for key in ["record_id", "decision", "selections",
                "ambiguous_official_row_ids", "official_row_id",
                "row_quote", "official_quote", "basis"]:
        assert f'"{key}"' in adjudication
    assert "FINAL" in adjudication
    sweep = (PKG / "prompts" / "sweep.md").read_text("utf-8")
    for key in ["sweep_id", "proposals"]:
        assert f'"{key}"' in sweep
    assert "candidates, not matches" in sweep
    comparison = (PKG / "prompts" / "comparison.md").read_text("utf-8")
    for key in ["comparison_id", "per_rule", "field_alignment",
                "change_analysis", "verdict", "confidence", "human_review",
                "row_quote", "official_quote", "claim_consistency",
                "record_notes", "reasoning"]:
        assert f'"{key}"' in comparison
    for verdict in ["Compliant", "Deviating", "Incomplete", "Ambiguous",
                    "Cannot Assess"]:
        assert verdict in comparison
    for tag in ["omitted", "contradicted", "weakened", "strengthened",
                "materially-changed"]:
        assert tag in comparison
    rollup = (PKG / "prompts" / "rule_rollup.md").read_text("utf-8")
    for key in ["rollup_id", "contributing_record_ids", "joint_verdict",
                "coverage_of_requirement"]:
        assert f'"{key}"' in rollup
    validation = (PKG / "prompts" / "validation.md").read_text("utf-8")
    for key in ["validation_id", "finding_id", "independent_verdict",
                "outcome", "revised_verdict", "reason", "evidence_quote"]:
        assert f'"{key}"' in validation
    assert "Do not merely confirm" in validation or \
        "not to ratify" in validation
    assert "BEFORE" in validation             # independent-first protocol


def test_prompt_hashes_land_in_versions():
    v = common.load_versions(PKG)
    assert set(PROMPTS) <= set(v["prompt_hashes"])
    for k in ("skill_version", "extraction_version", "pipeline_version",
              "report_schema_version"):
        assert v[k] == "0.3.0"
    assert "rule_registry_version" not in v


def test_skill_md_orchestration_contract():
    text = (PKG / "SKILL.md").read_text(encoding="utf-8")
    assert "name: stig-compare" in text
    for needle in ["pipeline.py start", "pipeline.py resolve",
                   "pipeline.py sweep", "pipeline.py rollup",
                   "pipeline.py finalize",
                   "official_structure_requests.jsonl",
                   "table_mapping_requests.jsonl",
                   "interpretation_requests.jsonl",
                   "scoping_requests.jsonl",
                   "adjudication_requests.jsonl",
                   "comparison_requests.jsonl",
                   "validation_requests.jsonl",
                   "validation_responses.jsonl",
                   "feedback.py ingest", "build_replay", "evaluate_replay",
                   "--allow-pending", "sweep_round", "retry: true"]:
        assert needle in text, needle
    # The retired machinery must not be referenced.
    for gone in ["canonicalize_responses.jsonl", "semantic_requests.jsonl",
                 "skeptic_responses.jsonl", "evaluate_candidate",
                 "registry.json"]:
        assert gone not in text, gone


def test_skill_instruction_files_exist():
    text = (PKG / "SKILL.md").read_text(encoding="utf-8")
    for name in PROMPTS:
        assert f"prompts/{name}" in text, name
        assert (PKG / "prompts" / name).exists()
