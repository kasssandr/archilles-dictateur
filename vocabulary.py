import logging
import re
from pathlib import Path

MAX_PROMPT_WORDS = 150

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_ARROW_RE = re.compile(r"\s*(?:->|→)\s*")


def parse_vocabulary_file(path: Path, logger: logging.Logger) -> tuple[str, dict[str, str]]:
    """Parse a vocabulary markdown file.

    Returns (prompt, corrections). On missing file, unreadable file, or empty
    file, returns ("", {}) and logs a warning.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Vocabulary file not found: %s", path)
        return "", {}
    except OSError as e:
        logger.error("Cannot read vocabulary file %s: %s", path, e)
        return "", {}

    content = _COMMENT_RE.sub("", content)
    sections = _split_sections(content)

    vocab_raw = sections.get("vokabular", "")
    corr_raw = sections.get("korrekturen", "")

    prompt = _parse_vocabulary(vocab_raw, logger)
    corrections = _parse_corrections(corr_raw, logger)
    return prompt, corrections


def _split_sections(content: str) -> dict[str, str]:
    """Split markdown into lowercase-keyed sections by H2 headers."""
    result: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in content.splitlines():
        header_match = re.match(r"^##\s+(\S+)", line)
        if header_match:
            if current_key is not None:
                result[current_key] = "\n".join(current_lines)
            current_key = header_match.group(1).lower()
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        result[current_key] = "\n".join(current_lines)
    return result


def _parse_vocabulary(raw: str, logger: logging.Logger) -> str:
    tokens: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        for tok in re.split(r"[,\s]+", line):
            tok = tok.strip()
            if tok:
                tokens.append(tok)

    if len(tokens) > MAX_PROMPT_WORDS:
        logger.warning(
            "Vocabulary has %d tokens, truncating to %d (initial_prompt limit).",
            len(tokens),
            MAX_PROMPT_WORDS,
        )
        tokens = tokens[:MAX_PROMPT_WORDS]

    return ", ".join(tokens)


def _parse_corrections(raw: str, logger: logging.Logger) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _ARROW_RE.split(line, maxsplit=1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            logger.warning("Malformed correction line skipped: %r", line)
            continue
        wrong, right = parts[0].strip(), parts[1].strip()
        if not wrong or not right:
            logger.warning("Malformed correction line skipped: %r", line)
            continue
        result[wrong] = right
    return result
