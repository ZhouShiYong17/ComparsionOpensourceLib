from pathlib import Path

import common

PKG = Path(__file__).resolve().parent.parent
PROMPTS = ["table_mapping.md", "canonicalize.md", "sweep.md", "matching.md",
           "semantic_compare.md", "validator.md"]


def test_all_prompts_exist_with_strict_preamble():
    for name in PROMPTS:
        text = (PKG / "prompts" / name).read_text(encoding="utf-8")
        assert "STRICT RULES" in text
        assert "ONLY the evidence supplied" in text
        assert "VERBATIM" in text


def test_prompts_state_their_schemas():
    matching = (PKG / "prompts" / "matching.md").read_text(encoding="utf-8")
    for key in ["record_id", "decision", "selections", "ambiguous_rule_ids",
                "rule_id", "row_quote", "rule_quote", "basis"]:
        assert f'"{key}"' in matching
    table_mapping = (PKG / "prompts" / "table_mapping.md").read_text(encoding="utf-8")
    for key in ["table_index", "classification", "irrelevant_reason",
                "column_mapping", "context_grouping"]:
        assert f'"{key}"' in table_mapping
    canonicalize = (PKG / "prompts" / "canonicalize.md").read_text(encoding="utf-8")
    for key in ["chunk_id", "row_index", "disposition", "records",
                "sub_index", "fields", "field_provenance",
                "interpretation_note", "separator_text"]:
        assert f'"{key}"' in canonicalize
    sweep = (PKG / "prompts" / "sweep.md").read_text(encoding="utf-8")
    for key in ["sweep_id", "proposals"]:
        assert f'"{key}"' in sweep
    assert "candidates, not matches" in sweep
    semantic = (PKG / "prompts" / "semantic_compare.md").read_text(encoding="utf-8")
    for key in ["finding_type", "verdict", "row_quote", "rule_quote",
                "interpretation"]:
        assert f'"{key}"' in semantic
    validator = (PKG / "prompts" / "validator.md").read_text(encoding="utf-8")
    assert "DISPROVE" in validator
    assert '"outcome"' in validator


def test_prompt_hashes_land_in_versions():
    v = common.load_versions(PKG)
    assert set(PROMPTS) <= set(v["prompt_hashes"])


def test_skill_md_orchestration_contract():
    text = (PKG / "SKILL.md").read_text(encoding="utf-8")
    assert "name: stig-compare" in text
    for needle in ["pipeline.py start", "pipeline.py resolve",
                   "pipeline.py finalize", "structuring_requests.jsonl",
                   "matching_requests.jsonl", "semantic_requests.jsonl",
                   "skeptic_responses.jsonl", "feedback.py ingest",
                   "evaluate_candidate", "Never auto-approve"]:
        assert needle in text
