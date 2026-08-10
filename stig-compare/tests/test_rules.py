import pytest

import rules


def _rule(rid, level, value, category="equivalent-terminology",
          payload=None, status="active"):
    return {"rule_id": rid, "version": 1, "category": category,
            "scope": {"level": level, "value": value}, "status": status,
            "payload": payload or {"a": "enabled", "b": "turned on"},
            "provenance": {"feedback_ids": [], "approved_by": "t",
                           "created": "2026-08-10", "approved": "2026-08-10"}}


_CTX = {"document_type": "docx", "sheet_or_section": "document-body",
        "field": "observed_value_or_evidence"}


def test_load_registry_rejects_duplicate_ids(tmp_path):
    import json
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"registry_version": 1, "rules": [
        _rule("RL-00000001", "global", None),
        _rule("RL-00000001", "global", None)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        rules.load_registry(p)


def test_scope_matching_and_candidate_excluded():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-1", "global", None),
        _rule("RL-2", "field", "some_other_field"),
        _rule("RL-3", "global", None, status="candidate")]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    assert [r["rule_id"] for r in applied] == ["RL-1"]
    assert conflicts == []


def test_narrower_scope_wins():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-g", "global", None, payload={"a": "enabled", "b": "on"}),
        _rule("RL-f", "field", "observed_value_or_evidence",
              payload={"a": "enabled", "b": "active"})]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    # both apply (different payloads at different levels is not a conflict);
    # narrower first so callers can prefer it
    assert [r["rule_id"] for r in applied] == ["RL-f", "RL-g"]
    assert conflicts == []


def test_same_level_conflict_suspends_both():
    reg = {"registry_version": 1, "rules": [
        _rule("RL-a", "global", None, payload={"a": "enabled", "b": "on"}),
        _rule("RL-b", "global", None, payload={"a": "enabled", "b": "off"})]}
    applied, conflicts = rules.applicable_rules(reg, _CTX)
    assert applied == []
    assert conflicts[0]["code"] == "rule-conflict"
    assert set(conflicts[0]["rule_ids"]) == {"RL-a", "RL-b"}


def test_equivalent_by_rule():
    applied = [_rule("RL-1", "global", None)]
    assert rules.equivalent_by_rule(applied, "Turned On", "ENABLED") == "RL-1"
    assert rules.equivalent_by_rule(applied, "enabled", "disabled") is None
