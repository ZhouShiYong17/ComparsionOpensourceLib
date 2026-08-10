"""Rule registry: load, scope matching, precedence, conflicts (spec section 10)."""
import json
from pathlib import Path

CATEGORIES = {"equivalent-terminology", "normalization-exception",
              "matching-key", "ignore-field", "exact-compare-field",
              "severity-override", "semantic-equivalence"}
_LEVELS = ["field", "sheet-or-section", "document-type", "global"]  # narrow->wide


def load_registry(path):
    reg = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for r in reg.get("rules", []):
        rid = r.get("rule_id")
        if rid in seen:
            raise ValueError(f"duplicate rule id: {rid}")
        seen.add(rid)
        if r.get("category") not in CATEGORIES:
            raise ValueError(f"unknown category on rule: {rid}")
        if r.get("scope", {}).get("level") not in _LEVELS:
            raise ValueError(f"unknown scope level on rule: {rid}")
    return reg


def _matches(rule, context):
    level = rule["scope"]["level"]
    if level == "global":
        return True
    value = rule["scope"]["value"]
    key = {"field": "field", "sheet-or-section": "sheet_or_section",
           "document-type": "document_type"}[level]
    return value == context.get(key)


def applicable_rules(registry, context):
    matching = [r for r in registry.get("rules", [])
                if r.get("status") == "active" and _matches(r, context)]
    matching.sort(key=lambda r: _LEVELS.index(r["scope"]["level"]))

    conflicts, suspended = [], set()
    by_bucket = {}
    for r in matching:
        by_bucket.setdefault((r["category"], r["scope"]["level"]), []).append(r)
    for (cat, level), rs in by_bucket.items():
        payloads = [json.dumps(r["payload"], sort_keys=True) for r in rs]
        if len(rs) > 1 and len(set(payloads)) > 1:
            ids = [r["rule_id"] for r in rs]
            conflicts.append({"code": "rule-conflict", "rule_ids": ids,
                              "scope_level": level})
            suspended.update(ids)
    applied = [r for r in matching if r["rule_id"] not in suspended]
    return applied, conflicts


def equivalent_by_rule(applied, a, b):
    pair = {a.strip().lower(), b.strip().lower()}
    for r in applied:
        if r["category"] == "equivalent-terminology":
            p = r["payload"]
            if {p["a"].strip().lower(), p["b"].strip().lower()} == pair:
                return r["rule_id"]
    return None
