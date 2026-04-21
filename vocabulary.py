import logging
import re
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

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

    # Accept English and German section headers interchangeably so the
    # English-language README stays truthful without breaking existing
    # German vocabulary files.
    vocab_raw = sections.get("vocabulary", sections.get("vokabular", ""))
    corr_raw = sections.get("corrections", sections.get("korrekturen", ""))

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
        for tok in line.split(","):
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


class VocabularyStore:
    """Owns the parsed vocabulary state and keeps it in sync with a file.

    Uses watchdog to observe the containing directory for changes. Reloads
    on any modify/create event targeting the configured file. All reads are
    thread-safe and return defensive copies of mutable state.
    """

    def __init__(self, path: Path | None, logger: logging.Logger):
        self._path = path
        self._logger = logger
        self._lock = threading.Lock()
        self._prompt = ""
        self._corrections: dict[str, str] = {}
        self._observer: Observer | None = None

        if path is None:
            logger.info("No vocabulary path configured; store will remain empty.")
            return

        self._reload()
        self._start_watching()

    def get_prompt(self) -> str:
        with self._lock:
            return self._prompt

    def get_corrections(self) -> dict[str, str]:
        with self._lock:
            return dict(self._corrections)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

    def _reload(self) -> None:
        assert self._path is not None
        prompt, corrections = parse_vocabulary_file(self._path, self._logger)
        with self._lock:
            self._prompt = prompt
            self._corrections = corrections
        self._logger.info(
            "Vocabulary loaded: %d prompt tokens, %d corrections",
            len(prompt.split(", ")) if prompt else 0,
            len(corrections),
        )

    def _start_watching(self) -> None:
        assert self._path is not None
        watch_dir = self._path.parent
        if not watch_dir.exists():
            self._logger.warning(
                "Vocabulary directory %s does not exist; watcher not started.",
                watch_dir,
            )
            return

        store = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path).resolve() != store._path.resolve():
                    return
                try:
                    store._reload()
                except Exception as e:
                    store._logger.error("Reload failed: %s", e)

        self._observer = Observer()
        self._observer.schedule(Handler(), str(watch_dir), recursive=False)
        self._observer.start()
