from post_processor import apply_corrections, apply_voice_commands


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


# --- Voice commands ---

def test_voice_empty_text_returns_empty():
    assert apply_voice_commands("") == ""


def test_voice_no_command_returns_text_unchanged():
    assert apply_voice_commands("Ein ganz normaler Satz.") == "Ein ganz normaler Satz."


def test_voice_absatz_becomes_blank_line_and_collapses_spaces():
    assert apply_voice_commands("Satz eins Absatz Satz zwei") == "Satz eins\n\nSatz zwei"


def test_voice_neue_zeile_becomes_single_newline():
    assert apply_voice_commands("Zeile eins neue Zeile Zeile zwei") == "Zeile eins\nZeile zwei"


def test_voice_komma_attaches_to_preceding_word():
    assert apply_voice_commands("Hallo Komma Welt") == "Hallo, Welt"


def test_voice_fragezeichen_and_ausrufezeichen_attach_left():
    assert apply_voice_commands("Wirklich Fragezeichen") == "Wirklich?"
    assert apply_voice_commands("Achtung Ausrufezeichen") == "Achtung!"


def test_voice_doppelpunkt_and_semikolon():
    assert apply_voice_commands("Beispiel Doppelpunkt Text") == "Beispiel: Text"
    assert apply_voice_commands("eins Semikolon zwei") == "eins; zwei"


def test_voice_klammern_hug_their_content():
    text = "Text Klammer auf Inhalt Klammer zu Ende"
    assert apply_voice_commands(text) == "Text (Inhalt) Ende"


def test_voice_anfuehrungszeichen_hug_their_content():
    text = "Er sagte Anführungszeichen auf Hallo Welt Anführungszeichen zu"
    assert apply_voice_commands(text) == "Er sagte „Hallo Welt“"


def test_voice_gedankenstrich_keeps_surrounding_spaces():
    assert apply_voice_commands("Wort Gedankenstrich Wort") == "Wort – Wort"


def test_voice_bindestrich_joins_tightly():
    assert apply_voice_commands("E Bindestrich Mail") == "E-Mail"


def test_voice_is_case_insensitive():
    assert apply_voice_commands("Satz eins absatz Satz zwei") == "Satz eins\n\nSatz zwei"


def test_voice_word_boundary_prevents_substring_match():
    # "Absatz" inside "Absatzweise" must not trigger a line break.
    assert apply_voice_commands("Absatzweise vorgehen") == "Absatzweise vorgehen"


def test_voice_combined_example():
    text = (
        "Er sagte Anführungszeichen auf Hallo Welt Anführungszeichen zu "
        "Absatz Und dann Komma dachte er"
    )
    expected = "Er sagte „Hallo Welt“\n\nUnd dann, dachte er"
    assert apply_voice_commands(text) == expected


# --- Voice commands: language selection ---

def test_voice_default_language_is_german():
    assert apply_voice_commands("Hallo Absatz Welt") == "Hallo\n\nWelt"


def test_voice_english_new_paragraph():
    assert apply_voice_commands("Line one new paragraph Line two", "en") == "Line one\n\nLine two"


def test_voice_english_comma_and_marks():
    assert apply_voice_commands("Hello comma world", "en") == "Hello, world"
    assert apply_voice_commands("Really question mark", "en") == "Really?"


def test_voice_english_parens_hug_content():
    assert apply_voice_commands("Text open paren inside close paren end", "en") == "Text (inside) end"


def test_voice_english_quote_unquote():
    assert apply_voice_commands("He said quote hello unquote", "en") == "He said “hello”"


def test_voice_english_dash_and_hyphen():
    assert apply_voice_commands("A dash B", "en") == "A – B"
    assert apply_voice_commands("sign hyphen off", "en") == "sign-off"


def test_voice_language_picks_the_matching_set():
    # A German command word is inert when the English set is selected.
    assert apply_voice_commands("Hallo Absatz Welt", "en") == "Hallo Absatz Welt"
    # ...and vice versa.
    assert apply_voice_commands("Line one new paragraph two", "de") == "Line one new paragraph two"


def test_voice_language_code_is_normalised():
    # Region suffixes and casing must not defeat the lookup.
    assert apply_voice_commands("Hello comma world", "EN") == "Hello, world"
    assert apply_voice_commands("Hello comma world", "en-US") == "Hello, world"


def test_voice_unknown_language_falls_back_to_german():
    assert apply_voice_commands("Hallo Absatz Welt", "no") == "Hallo\n\nWelt"


def test_voice_open_mark_swallows_whispers_pause_comma():
    # Whisper often inserts a comma at the pause after the spoken command; the
    # opening mark must still hug the content, not leave ", " behind it.
    text = "Er sagte Anführungszeichen auf, sogenannte Wörter Anführungszeichen zu"
    assert apply_voice_commands(text) == "Er sagte „sogenannte Wörter“"
    # Same for opening parens.
    assert apply_voice_commands("Text Klammer auf, Inhalt Klammer zu", "de") == "Text (Inhalt)"


def test_voice_spanish_set():
    text = "Dijo abrir comillas hola mundo cerrar comillas nuevo párrafo Fin coma listo"
    assert apply_voice_commands(text, "es") == "Dijo «hola mundo»\n\nFin, listo"


def test_voice_italian_set():
    text = "Ha detto apri virgolette ciao mondo chiudi virgolette nuovo paragrafo Fine virgola ok"
    assert apply_voice_commands(text, "it") == "Ha detto «ciao mondo»\n\nFine, ok"


def test_voice_russian_set():
    text = "Он сказал открыть кавычки привет мир закрыть кавычки новый абзац Конец запятая всё"
    assert apply_voice_commands(text, "ru") == "Он сказал «привет мир»\n\nКонец, всё"
