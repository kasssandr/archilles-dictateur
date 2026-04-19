import logging
from pathlib import Path

import pytest

from vocabulary import parse_vocabulary_file


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


def test_vocabulary_mixed_separators(tmp_path: Path, logger):
    md = tmp_path / "vocab.md"
    md.write_text(
        "## Vokabular\n"
        "Claude, Anthropic,Archilles\n"
        "Obsidian Ollama\n",
        encoding="utf-8",
    )
    prompt, corrections = parse_vocabulary_file(md, logger)
    tokens = set(prompt.split(", "))
    assert tokens == {"Claude", "Anthropic", "Archilles", "Obsidian", "Ollama"}


def test_vocabulary_too_long_is_truncated(tmp_path: Path, logger, caplog):
    words = [f"wort{i}" for i in range(300)]
    md = tmp_path / "vocab.md"
    md.write_text("## Vokabular\n" + ", ".join(words) + "\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        prompt, _ = parse_vocabulary_file(md, logger)
    assert len(prompt.split(", ")) <= 150
    assert any("gekürzt" in r.message.lower() or "truncat" in r.message.lower() for r in caplog.records)
