# Vocabulary Integration Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Write tests first, make them fail, then implement to make them pass.

**Goal:** Add a user-maintained vocabulary and corrections dictionary to the Archilles Dictator daemon. The vocabulary file lives in the user's Obsidian vault, is parsed at daemon startup and on every file change, and feeds Whisper's `initial_prompt` plus a post-processing find/replace step.

**Architecture:** A new `VocabularyStore` class (in `vocabulary.py`) owns the file-watching and parsing. A new `apply_corrections` function (in `post_processor.py`) handles the post-processing step. The existing daemon is modified to wire these into the STOP handler, between transcription and sending the result. No protocol changes, no AHK changes.

**Tech Stack additions:** `watchdog` (file-watching)

**Spec:** `docs/superpowers/specs/2026-04-19-vocabulary-phase1-design.md`

**Vocabulary file location:** `D:\Archilles-Lab\Dictator\Vokabular.md` (user's Obsidian vault)

---

## File Changes Overview

```
archilles-dictator/
├── vocabulary.py         # NEW: VocabularyStore (parsing + file-watching)
├── post_processor.py     # NEW: apply_corrections function
├── daemon.py             # MODIFIED: wire VocabularyStore, pass initial_prompt, apply corrections
├── start.bat             # MODIFIED: set ARCHILLES_VOCABULARY_PATH env var
├── requirements.txt      # MODIFIED: add watchdog
└── tests/
    ├── test_vocabulary.py      # NEW
    ├── test_post_processor.py  # NEW
    └── test_daemon.py          # UNCHANGED
```

User-side (outside repo):
```
D:\Archilles-Lab\Dictator\Vokabular.md   # NEW: initial vocabulary file
```

---

## Task 1: Install `watchdog` dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add `watchdog` to requirements.txt**

Append `watchdog` on a new line. Resulting file:

```
faster-whisper
sounddevice
numpy
pytest
watchdog
```

- [ ] **Step 2: Install into existing venv**

Run (from project root, `C:\Users\tomra\archilles-dictator`):
```bash
./venv/Scripts/pip install watchdog
```

Expected: watchdog installs successfully.

- [ ] **Step 3: Verify**

Run:
```bash
./venv/Scripts/python -c "from watchdog.observers import Observer; print('watchdog OK')"
```
Expected: `watchdog OK`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add watchdog dependency for vocabulary file-watching"
```

---

## Task 2: Post-Processor — `apply_corrections`

**Files:**
- Create: `post_processor.py`
- Create: `tests/test_post_processor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_post_processor.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./venv/Scripts/python -m pytest tests/test_post_processor.py -v
```
Expected: ImportError (module `post_processor` not found).

- [ ] **Step 3: Implement `post_processor.py`**

```python
import re


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Replace words in text according to corrections, word-boundary sensitive.

    Longer keys are applied first so that, given overlapping keys, the longest
    match wins. Matching is case-sensitive. Keys are regex-escaped so they are
    treated as literal strings.
    """
    if not text or not corrections:
        return text

    sorted_keys = sorted(corrections.keys(), key=len, reverse=True)
    for wrong in sorted_keys:
        right = corrections[wrong]
        pattern = r"\b" + re.escape(wrong) + r"\b"
        text = re.sub(pattern, right, text)
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./venv/Scripts/python -m pytest tests/test_post_processor.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add post_processor.py tests/test_post_processor.py
git commit -m "feat: add apply_corrections post-processor with word-boundary matching"
```

---

## Task 3: VocabularyStore — parsing (no file-watching yet)

Split into two tasks for clarity: first the pure parsing (synchronous, no watcher), then the watcher on top.

**Files:**
- Create: `vocabulary.py`
- Create: `tests/test_vocabulary.py`

- [ ] **Step 1: Write failing tests for the parser**

Create `tests/test_vocabulary.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./venv/Scripts/python -m pytest tests/test_vocabulary.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the parser in `vocabulary.py`**

Implement only `parse_vocabulary_file` for now. The `VocabularyStore` class comes in Task 4.

```python
import logging
import re
from pathlib import Path

MAX_PROMPT_WORDS = 150

_SECTION_RE = re.compile(r"^##\s+(\S+)", re.MULTILINE)
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
        # Split on commas and whitespace
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./venv/Scripts/python -m pytest tests/test_vocabulary.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add vocabulary.py tests/test_vocabulary.py
git commit -m "feat: add vocabulary markdown parser with section splitting and correction parsing"
```

---

## Task 4: VocabularyStore — file-watching and thread-safe state

**Files:**
- Modify: `vocabulary.py` (add `VocabularyStore` class)
- Modify: `tests/test_vocabulary.py` (add `VocabularyStore` tests)

- [ ] **Step 1: Add failing tests for `VocabularyStore`**

Append to `tests/test_vocabulary.py`:

```python
import time
import logging
from pathlib import Path

from vocabulary import VocabularyStore


def _wait_for(predicate, timeout=3.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./venv/Scripts/python -m pytest tests/test_vocabulary.py -v -k "store"
```
Expected: ImportError on `VocabularyStore`.

- [ ] **Step 3: Implement `VocabularyStore`**

Add to `vocabulary.py`:

```python
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


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
                # Reload on any create/modify event that targets our file
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
```

Note: keep the existing `parse_vocabulary_file` and helpers. Add imports (`threading`, `Optional`, `Observer`, `FileSystemEventHandler`) at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

```bash
./venv/Scripts/python -m pytest tests/test_vocabulary.py -v
```
Expected: all tests pass. The `test_store_reloads_on_file_change` and `test_store_handles_missing_file_then_created` tests may take up to a few seconds each due to the file-watcher debounce — this is normal.

- [ ] **Step 5: Commit**

```bash
git add vocabulary.py tests/test_vocabulary.py
git commit -m "feat: add VocabularyStore with watchdog-based hot-reload"
```

---

## Task 5: Wire VocabularyStore and apply_corrections into the daemon

**Files:**
- Modify: `daemon.py`

- [ ] **Step 1: Extend `DaemonConfig` with vocabulary_path**

In `daemon.py`, change `DaemonConfig`:

```python
@dataclass
class DaemonConfig:
    model_size: str = "small"
    language: str = "de"
    port: int = 9876
    host: str = "localhost"
    sample_rate: int = 16000
    device: str = "cuda"
    compute_type: str = "float16"
    vocabulary_path: Path | None = None
```

- [ ] **Step 2: Extend `TranscriptionService.transcribe` to accept `initial_prompt`**

Change the method:

```python
def transcribe(self, audio: np.ndarray, language: str = "de", initial_prompt: str = "") -> str:
    kwargs = {"language": language}
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    segments, _ = self.model.transcribe(audio, **kwargs)
    return "".join(seg.text for seg in segments).strip()
```

- [ ] **Step 3: Add imports and wire VocabularyStore + apply_corrections into `DaemonServer`**

Top of `daemon.py`:

```python
from vocabulary import VocabularyStore
from post_processor import apply_corrections
```

In `DaemonServer.__init__`, after creating the recorder:

```python
self.vocabulary = VocabularyStore(config.vocabulary_path, self.logger)
```

In `DaemonServer._handle_client`, modify the `STOP` branch. Replace the current block starting at the transcription call:

```python
elif msg == "STOP":
    audio = self.recorder.stop()
    self.logger.info("Recording stopped, %d samples", len(audio))

    if len(audio) == 0:
        send_message(stream, "RESULT:")
        continue

    try:
        prompt = self.vocabulary.get_prompt()
        text = self.transcriber.transcribe(
            audio,
            language=self.config.language,
            initial_prompt=prompt,
        )
        text = apply_corrections(text, self.vocabulary.get_corrections())
        self.logger.info("Transcribed: %s", text)
        send_message(stream, f"RESULT:{text}")
    except Exception as e:
        self.logger.error("Transcription error: %s", e)
        send_message(stream, f"ERROR:TRANSCRIPTION:{e}")
```

In `DaemonServer.shutdown`, add after stopping the recorder:

```python
self.vocabulary.stop()
```

- [ ] **Step 4: Read `ARCHILLES_VOCABULARY_PATH` in `main()`**

At the top of `daemon.py`, add `import os` if not present. Change `main()`:

```python
def main():
    vocab_env = os.environ.get("ARCHILLES_VOCABULARY_PATH")
    vocabulary_path = Path(vocab_env) if vocab_env else None
    config = DaemonConfig(vocabulary_path=vocabulary_path)
    server = DaemonServer(config)

    def signal_handler(sig, frame):
        server.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server.start()
```

- [ ] **Step 5: Run existing daemon tests to confirm no regression**

```bash
./venv/Scripts/python -m pytest tests/test_daemon.py -v
```
Expected: all existing tests still pass. Note: `test_transcription_service_returns_string` calls `service.transcribe(audio)` — if your existing mock expects a strict signature, it should still match because `initial_prompt` has a default value. If tests fail due to the new keyword argument in the call chain, update `test_daemon.py` minimally so the mocked `model.transcribe` accepts arbitrary kwargs (e.g., `mock_instance.transcribe = MagicMock(return_value=(...))` already accepts kwargs). No test *logic* should change.

- [ ] **Step 6: Run the full test suite**

```bash
./venv/Scripts/python -m pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add daemon.py
git commit -m "feat: wire VocabularyStore and apply_corrections into daemon pipeline"
```

If `tests/test_daemon.py` needed adjustment: include it in the same commit.

---

## Task 6: Set `ARCHILLES_VOCABULARY_PATH` in start.bat

**Files:**
- Modify: `start.bat`

- [ ] **Step 1: Add the env var**

Insert this line after the `cd /d "%~dp0"` line and before the `start /B` line:

```batch
set ARCHILLES_VOCABULARY_PATH=D:\Archilles-Lab\Dictator\Vokabular.md
```

Resulting relevant section:

```batch
cd /d "%~dp0"

set ARCHILLES_VOCABULARY_PATH=D:\Archilles-Lab\Dictator\Vokabular.md

REM Start daemon in background (expliziter venv-Pfad)
start /B "" "%~dp0venv\Scripts\python.exe" "%~dp0daemon.py"
```

- [ ] **Step 2: Commit**

```bash
git add start.bat
git commit -m "chore: set ARCHILLES_VOCABULARY_PATH in start.bat"
```

---

## Task 7: Create initial vocabulary file in Obsidian vault

**Files:**
- Create: `D:\Archilles-Lab\Dictator\Vokabular.md` (outside repo — on the user's D: drive)

- [ ] **Step 1: Ensure the directory exists**

Run:
```bash
mkdir -p "/d/Archilles-Lab/Dictator"
```
(Or from PowerShell: `New-Item -ItemType Directory -Force -Path "D:\Archilles-Lab\Dictator"`)

If `D:\Archilles-Lab` does not exist, stop and ask the user — do not create the vault root.

- [ ] **Step 2: Write initial content**

Create `D:\Archilles-Lab\Dictator\Vokabular.md` with:

```markdown
# Archilles Dictator Vokabular

Diese Datei wird automatisch vom Daemon gelesen.
Änderungen werden sofort wirksam (Hot-Reload, kein Neustart nötig).

## Vokabular
<!-- Kommagetrennt oder zeilenweise. Geht als initial_prompt an Whisper. -->
<!-- Grenze: ca. 150 Wörter. Längere Listen werden automatisch gekürzt. -->
Claude, Anthropic, Archilles, Dictator, faster-whisper
Antigravity, Obsidian, Ollama, Gemma
TypeScript, Python, AutoHotkey

## Korrekturen
<!-- Format: Falsch -> Richtig. Eine Regel pro Zeile. Case-sensitive. -->
Cloud -> Claude
Clod -> Claude
Klod -> Claude
Diktator -> Dictator
```

- [ ] **Step 3: Verify the file is readable**

```bash
./venv/Scripts/python -c "from pathlib import Path; print(Path('D:/Archilles-Lab/Dictator/Vokabular.md').read_text(encoding='utf-8')[:200])"
```
Expected: first 200 characters of the file printed.

- [ ] **Step 4: No commit needed** — the file lives outside the repository. Note this in the final summary to the user.

---

## Task 8: End-to-End Manual Verification

No new files. This task is hands-on verification.

- [ ] **Step 1: Stop any running daemon/AHK**

Check Task Manager for `python.exe` and `AutoHotkey64.exe` processes belonging to this project, stop them if present. Or run `stop.bat` if it exists.

- [ ] **Step 2: Start fresh**

Run `start.bat` from the project directory.

- [ ] **Step 3: Check the daemon log**

Open `%APPDATA%/archilles-dictator/daemon.log` and confirm it contains a line like:
```
Vocabulary loaded: N prompt tokens, M corrections
```
where N and M match the initial file (roughly 12 tokens, 4 corrections).

- [ ] **Step 4: Dictation test — vocabulary effect**

Open Notepad, press and hold the hotkey, say clearly in German:
> „Ich arbeite mit Claude und Anthropic."

Release. Verify:
- The word „Claude" appears correctly (not „Cloud", not „Klod").
- The word „Anthropic" appears correctly.

- [ ] **Step 5: Dictation test — correction fallback**

This is harder to trigger deterministically (you want Whisper to output „Cloud" so the correction kicks in). Instead, verify the correction mechanism with a direct test:

```bash
./venv/Scripts/python -c "from post_processor import apply_corrections; print(apply_corrections('Ich nutze Cloud und Klod.', {'Cloud': 'Claude', 'Klod': 'Claude'}))"
```
Expected: `Ich nutze Claude und Claude.`

- [ ] **Step 6: Hot-reload test**

With the daemon running, open `D:\Archilles-Lab\Dictator\Vokabular.md` in Obsidian. Add a new line to the Korrekturen section:
```
Testwort -> Erfolgswort
```
Save. Check the log — you should see a new `Vocabulary loaded: ...` line within 1-2 seconds.

- [ ] **Step 7: Graceful-degradation test**

Stop daemon/AHK. Temporarily rename `D:\Archilles-Lab\Dictator\Vokabular.md` to `Vokabular.bak`. Restart. Check the log — it should contain a WARNING about the missing file but the daemon should still accept dictation (just without vocabulary). Rename back.

- [ ] **Step 8: Report to user**

Summarize:
- All tests passing
- End-to-end dictation works
- Hot-reload works
- Graceful degradation works
- Vocabulary file lives at `D:\Archilles-Lab\Dictator\Vokabular.md`
- User can edit freely in Obsidian; changes take effect within ~1 second

---

## Post-Implementation Checklist

- [ ] All unit tests pass: `./venv/Scripts/python -m pytest tests/ -v`
- [ ] Daemon starts cleanly, log shows vocabulary loaded
- [ ] Dictation correctly transcribes „Claude" (the canonical test case)
- [ ] Hot-reload works (editing the .md file updates behavior without daemon restart)
- [ ] No regressions in existing behavior (dictation without vocabulary still works if env var is unset)
- [ ] All intermediate commits made as listed
- [ ] Final summary reported to the user, including the vocabulary file path

## Out of Scope (Phase 2)

These items are deliberately deferred and must NOT be added in this phase:

- LLM-based post-processing (Ollama/Gemma)
- Learning hotkey that auto-appends corrections
- Clipboard-diff based learning
- Auto-discovery of the Obsidian vault path
- Telemetry on which corrections fire how often
- Morphological variant expansion
