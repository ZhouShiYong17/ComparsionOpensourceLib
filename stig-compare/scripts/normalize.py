"""Additive normalization. Raw values are never mutated (spec section 4.4)."""
import re
import unicodedata

import common

_NUM = re.compile(r"^\d+(\.\d+)?$")
_WRAP = "`'\""


def norm_text(s):
    s = unicodedata.normalize("NFC", s or "")
    return common.fold_ws(s).lower()


def norm_value(s):
    s = norm_text(s).strip(_WRAP).strip()
    if _NUM.match(s):
        f = float(s)
        s = str(int(f)) if f == int(f) else str(f)
    return s


def add_normalized(records, fields):
    for rec in records:
        rec["normalized"] = {f: norm_value(rec.get(f, "")) for f in fields}
    return records
