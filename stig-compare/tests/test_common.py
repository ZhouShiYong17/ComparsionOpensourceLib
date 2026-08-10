import json
from pathlib import Path

import common


def test_short_hash_stable_and_short():
    a = common.short_hash("x", "y")
    assert a == common.short_hash("x", "y")
    assert len(a) == 8
    assert a != common.short_hash("xy")          # separator prevents collisions
    assert a != common.short_hash("x", "z")


def test_row_id_and_finding_id_prefixes():
    rid = common.row_id(1, 2, "raw text")
    assert rid.startswith("R-") and len(rid) == 10
    assert rid == common.row_id(1, 2, "raw text")   # stable across calls
    fid = common.finding_id(rid, "V-1001", "match")
    assert fid.startswith("F-") and len(fid) == 10


def test_fold_ws():
    assert common.fold_ws("  a\t b\n\nc  ") == "a b c"


def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "x.jsonl"
    records = [{"a": 1}, {"b": "café"}]
    common.write_jsonl(p, records)
    assert common.read_jsonl(p) == records


def test_file_sha256(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert common.file_sha256(p) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_load_versions_includes_prompt_hashes(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "matching.md").write_text("PROMPT", encoding="utf-8")
    (tmp_path / "VERSIONS.json").write_text(
        json.dumps({"skill_version": "0.1.0"}), encoding="utf-8"
    )
    v = common.load_versions(tmp_path)
    assert v["skill_version"] == "0.1.0"
    assert "matching.md" in v["prompt_hashes"]
    assert len(v["prompt_hashes"]["matching.md"]) == 64
