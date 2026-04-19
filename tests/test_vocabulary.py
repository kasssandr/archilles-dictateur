import logging
import time
from pathlib import Path

import pytest

from vocabulary import VocabularyStore, parse_vocabulary_file


def _wait_for(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def logger():
    return logging.getLogger("test")


def test_parses_both_sections(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "# Title\n\n"
        "## Vokabular\n"
        "Claude, Anthropic\n"
        "Archilles\n\n"
        "## Korrekturen\n"
        "Cloud -> Claude\n"
        "Klod -> Claude\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert set(prompt.split(", ")) == {"Claude", "Anthropic", "Archilles"}
    assert corrections == {"Cloud": "Claude", "Klod": "Claude"}


def test_missing_file_returns_empty(tmp_path: Path, logger):
    prompt, corrections = parse_vocabulary_file(tmp_path / "nope.md", logger)
    assert prompt == ""
    assert corrections == {}


def test_empty_file_returns_empty(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text("", encoding="utf-8")
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert prompt == ""
    assert corrections == {}


def test_ignores_comments_and_blank_lines(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Vokabular\n"
        "<!-- ein Kommentar -->\n"
        "\n"
        "Claude\n"
        "\n"
        "## Korrekturen\n"
        "<!-- noch ein Kommentar -->\n"
        "Cloud -> Claude\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert prompt == "Claude"
    assert corrections == {"Cloud": "Claude"}


def test_header_case_insensitive(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## VOKABULAR\n"
        "Claude\n"
        "## korrekturen\n"
        "Cloud -> Claude\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert prompt == "Claude"
    assert corrections == {"Cloud": "Claude"}


def test_arrow_unicode_variant(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Korrekturen\n"
        "Cloud → Claude\n"
        "Klod -> Claude\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert corrections == {"Cloud": "Claude", "Klod": "Claude"}


def test_malformed_correction_line_is_skipped(tmp_path: Path, logger, caplog):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Korrekturen\n"
        "Cloud -> Claude\n"
        "kaputte Zeile ohne Pfeil\n"
        "Klod -> Claude\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        prompt, corrections = parse_vocabulary_file(md, logger)
    assert corrections == {"Cloud": "Claude", "Klod": "Claude"}
    assert any("kaputte Zeile" in r.message for r in caplog.records)


def test_missing_vocabulary_section_ok(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text("## Korrekturen\nCloud -> Claude\n", encoding="utf-8")
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert prompt == ""
    assert corrections == {"Cloud": "Claude"}


def test_missing_corrections_section_ok(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text("## Vokabular\nClaude\n", encoding="utf-8")
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert prompt == "Claude"
    assert corrections == {}


def test_vocabulary_comma_separates_entries(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Vokabular\n"
        "Claude, Anthropic,Archilles\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    assert set(prompt.split(", ")) == {"Claude", "Anthropic", "Archilles"}


def test_vocabulary_preserves_phrases(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Vokabular\n"
        "Claude Code, fasse Kapitel zusammen\n"
        "Archilles Dictator\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    tokens = prompt.split(", ")
    assert "Claude Code" in tokens
    assert "fasse Kapitel zusammen" in tokens
    assert "Archilles Dictator" in tokens


def test_vocabulary_too_long_is_truncated(tmp_path: Path, logger, caplog):
    words = [f"wort{i}" for i in range(300)]
    md = tmp_path / "vocab.md"
    md.write_text("## Vokabular\n" + ", ".join(words) + "\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        prompt, _ = parse_vocabulary_file(md, logger)
    assert len(prompt.split(", ")) <= 150
    assert any("gekürzt" in r.message.lower() or "truncat" in r.message.lower() for r in caplog.records)


# --- VocabularyStore tests ---


def test_store_none_path_yields_empty():
    store = VocabularyStore(None, logging.getLogger("test"))
    try:
        assert store.get_prompt() == ""
        assert store.get_corrections() == {}
    finally:
        store.stop()


def test_store_loads_initial_content(tmp_path: Path):
    md = tmp_path / "vocab.md"
    md.write_text("## Vokabular\nClaude\n## Korrekturen\nCloud -> Claude\n", encoding="utf-8")
    store = VocabularyStore(md, logging.getLogger("test"))
    try:
        assert store.get_prompt() == "Claude"
        assert store.get_corrections() == {"Cloud": "Claude"}
    finally:
        store.stop()


def test_store_reloads_on_file_change(tmp_path: Path):
    md = tmp_path / "vocab.md"
    md.write_text("## Vokabular\nClaude\n", encoding="utf-8")
    store = VocabularyStore(md, logging.getLogger("test"))
    try:
        assert store.get_prompt() == "Claude"
        md.write_text("## Vokabular\nAnthropic, Ollama\n", encoding="utf-8")
        assert _wait_for(lambda: set(store.get_prompt().split(", ")) == {"Anthropic", "Ollama"}), \
            f"Store did not reload; got {store.get_prompt()!r}"
    finally:
        store.stop()


def test_store_handles_missing_file_then_created(tmp_path: Path):
    md = tmp_path / "vocab.md"
    # Note: file doesn't exist yet
    store = VocabularyStore(md, logging.getLogger("test"))
    try:
        assert store.get_prompt() == ""
        md.write_text("## Vokabular\nClaude\n", encoding="utf-8")
        assert _wait_for(lambda: store.get_prompt() == "Claude"), \
            f"Store did not pick up created file; got {store.get_prompt()!r}"
    finally:
        store.stop()


def test_store_get_corrections_returns_copy(tmp_path: Path):
    md = tmp_path / "vocab.md"
    md.write_text("## Korrekturen\nCloud -> Claude\n", encoding="utf-8")
    store = VocabularyStore(md, logging.getLogger("test"))
    try:
        corrections = store.get_corrections()
        corrections["MUTATED"] = "NOPE"
        # Internal state must be unaffected
        assert store.get_corrections() == {"Cloud": "Claude"}
    finally:
        store.stop()
