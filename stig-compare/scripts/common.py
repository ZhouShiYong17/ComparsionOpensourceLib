"""Shared primitives: hashing, IDs, JSONL IO, whitespace folding, versions."""
import hashlib
import json
import re
from pathlib import Path

_SEP = "\x1f"
_WS = re.compile(r"\s+")


def short_hash(*parts):
    joined = _SEP.join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]


def row_id(table_index, row_index, raw_text):
    return "R-" + short_hash(table_index, row_index, raw_text)


def record_id(table_index, row_index, sub_index, raw_text):
    return "CR-" + short_hash(table_index, row_index, sub_index, raw_text)


def official_row_id(source_file, locator, cells):
    return "OR-" + short_hash(source_file, locator,
                              _SEP.join(str(c) for c in cells))


def finding_id(rid, official_row_id_, kind):
    return "F-" + short_hash(rid, official_row_id_, kind)


def rollup_id(official_row_id_):
    return "RU-" + short_hash(official_row_id_)


def fold_ws(text):
    return _WS.sub(" ", text or "").strip()


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path, records):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_versions(package_root):
    root = Path(package_root)
    versions = json.loads((root / "VERSIONS.json").read_text(encoding="utf-8"))
    hashes = {}
    prompts = root / "prompts"
    if prompts.is_dir():
        for p in sorted(prompts.glob("*.md")):
            hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    versions["prompt_hashes"] = hashes
    return versions
