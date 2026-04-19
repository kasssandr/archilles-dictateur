from post_processor import apply_corrections


def test_empty_text_returns_empty():
    assert apply_corrections("", {"Cloud": "Claude"}) == ""


def test_empty_corrections_returns_text_unchanged():
    assert apply_corrections("Hallo Welt", {}) == "Hallo Welt"


def test_simple_replacement():
    assert apply_corrections("Ich nutze Cloud.", {"Cloud": "Claude"}) == "Ich nutze Claude."


def test_word_boundary_prevents_substring_match():
    # "Cloud" should not match inside "Clouds" or "Clouding"
    assert apply_corrections("Clouds ziehen auf.", {"Cloud": "Claude"}) == "Clouds ziehen auf."
    assert apply_corrections("Cloud-Computing", {"Cloud": "Claude"}) == "Claude-Computing"


def test_multiple_corrections_applied():
    text = "Cloud und Klod sind Claude."
    corrections = {"Cloud": "Claude", "Klod": "Claude"}
    assert apply_corrections(text, corrections) == "Claude und Claude sind Claude."


def test_longer_keys_applied_first():
    # If "Clou" and "Cloud" both map, "Cloud" must win for the full word "Cloud"
    text = "Cloud"
    corrections = {"Clou": "X", "Cloud": "Claude"}
    assert apply_corrections(text, corrections) == "Claude"


def test_case_sensitive():
    assert apply_corrections("cloud Cloud CLOUD", {"Cloud": "Claude"}) == "cloud Claude CLOUD"


def test_unicode_umlauts_preserved():
    text = "Ich grüße dich, Cloud."
    assert apply_corrections(text, {"Cloud": "Claude"}) == "Ich grüße dich, Claude."


def test_replacement_with_umlauts():
    assert apply_corrections("Übung", {"Übung": "Prüfung"}) == "Prüfung"


def test_special_regex_characters_in_key_are_escaped():
    # A key with regex metacharacters should still be treated literally
    assert apply_corrections("C.D", {"C.D": "CD"}) == "CD"
    # And should not match "CXD"
    assert apply_corrections("CXD", {"C.D": "CD"}) == "CXD"
