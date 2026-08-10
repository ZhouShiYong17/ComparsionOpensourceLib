import normalize


def test_norm_text_folds_case_space_unicode():
    composed = "Café  VALUE"            # Ã© precomposed (U+00E9)
    decomposed = "café value"           # e + U+0301 combining acute
    assert normalize.norm_text(composed) == normalize.norm_text(decomposed)


def test_norm_value_numbers_and_quotes():
    assert normalize.norm_value("`09`") == "9"
    assert normalize.norm_value('"9.0"') == "9"
    assert normalize.norm_value("9 or more") == "9 or more"


def test_add_normalized_is_additive_not_destructive():
    rec = {"a": "  RAW Value ", "b": "keep"}
    out = normalize.add_normalized([rec], ["a"])
    assert out[0]["a"] == "  RAW Value "          # raw untouched
    assert out[0]["normalized"]["a"] == "raw value"
    assert "b" not in out[0]["normalized"]


def test_meaning_preserved_distinct_values_stay_distinct():
    # normalization must never merge meaningfully different values (spec Â§4.4)
    pairs = [("9 or more", "9"), ("enabled", "disabled"),
             ("60 days", "90 days"), ("15 minutes", "15 hours")]
    for a, b in pairs:
        assert normalize.norm_value(a) != normalize.norm_value(b)
