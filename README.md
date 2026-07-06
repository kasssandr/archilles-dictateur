# Dictateur

System-wide, offline push-to-talk dictation for Windows. Hold a hotkey, speak, release — your words appear in whatever text field has focus. Transcription runs locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper); no audio leaves your machine.

Dictateur is the dictation front-end of the **Archilles** toolchain — a small family of local-first language tools. Its sibling, the [Archillator](https://archilles.org/archillator/), cleans, corrects, and translates long-form text. Dictateur handles the input side: getting words from voice into any application (IDE, browser, chat, editor) without switching contexts.

## Features

- **Push-to-talk, globally.** Hold `Ctrl + Left-Win`, speak, release. Transcribed text is pasted into the active window.
- **Fully local.** Audio is recorded, transcribed, and discarded on your machine. No cloud APIs.
- **GPU-accelerated with CPU fallback.** Uses CUDA + `float16` when available; falls back transparently to CPU `int8`.
- **Custom vocabulary, hot-reloaded.** Point the daemon at a Markdown file; it feeds domain terms to Whisper as an `initial_prompt` and applies deterministic find/replace corrections post-transcription. Edit the file in any editor — changes take effect immediately.
- **Works in any app.** Because results are pasted via the clipboard, Dictateur works in VS Code, browsers, Word, Obsidian, Claude Code terminals — anything that accepts paste.
- **No GUI.** A background Python daemon plus an AutoHotkey v2 script. Start and forget.

## Architecture

```
┌──────────────────────┐     TCP 127.0.0.1:9876     ┌────────────────────────────┐
│ hotkey.ahk           │ ─────── START / STOP ────► │ daemon.py                  │
│ (AutoHotkey v2)      │ ◄────── RESULT / ERROR ─── │ (Python, faster-whisper)   │
│                      │                            │                            │
│ Ctrl+LWin → record   │                            │ AudioRecorder              │
│ release  → paste     │                            │ TranscriptionService       │
└──────────────────────┘                            │ VocabularyStore (watchdog) │
                                                    └────────────────────────────┘
```

The protocol is a minimal length-prefixed text framing (`protocol.py`). The daemon serializes requests, so there is never more than one concurrent transcription.

## Requirements

- **Windows 10/11** (tested on Windows 11).
- **Python 3.10+**.
- **[AutoHotkey v2](https://www.autohotkey.com/)** installed at the default location (`%LOCALAPPDATA%\Programs\AutoHotkey\v2\AutoHotkey64.exe`). Adjust `start.bat` if yours lives elsewhere.
- **NVIDIA GPU with CUDA** recommended (any recent consumer card works; the daemon uses the `small` Whisper model in `float16`). Without CUDA, the daemon automatically falls back to CPU at `int8` — slower but functional.
- **A working microphone** reachable through the default Windows audio device.

## Installation

```bat
git clone https://github.com/kasssandr/archilles-dictateur.git
cd archilles-dictateur

python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

On first run, faster-whisper downloads the Whisper `small` model (~500 MB) into its cache.

## Usage

### Start

```bat
start.bat
```

`start.bat` launches the daemon, waits until port `9876` is listening, then starts the AHK script. A brief tooltip (`Dictateur: Verbunden`) confirms the connection.

### Dictate

1. Put the cursor in any text field.
2. Hold `Ctrl + Left-Win` — tooltip shows `🎤 Aufnahme...`
3. Speak.
4. Release — tooltip shows `⌛ Transkribiere...`, and the transcribed text is pasted where the cursor is.

### Stop

```bat
stop.bat
```

### Logs

The daemon logs to `%APPDATA%\archilles-dictateur\daemon.log` (rotated at 1 MB, one backup kept).

## Configuration

`DaemonConfig` in `daemon.py` exposes the tunables; defaults are:

| Field          | Default     | Notes                                        |
| -------------- | ----------- | -------------------------------------------- |
| `model_size`   | `small`     | Any faster-whisper model tag.                |
| `language`     | `de`        | Whisper language code.                       |
| `host` / `port`| `localhost:9876` | TCP endpoint the AHK client connects to.|
| `sample_rate`  | `16000`     | Matches Whisper's expected input.            |
| `device`       | `cuda`      | Auto-falls-back to `cpu` on failure.         |
| `compute_type` | `float16`   | Uses `int8` on CPU fallback.                 |

Three runtime knobs are read from the environment:

```
ARCHILLES_VOCABULARY_PATH=C:\path\to\your\Vokabular.md
ARCHILLES_MODEL_SIZE=large-v3-turbo
ARCHILLES_COMPUTE_TYPE=int8_float16
```

Set them in `start.bat` (see the existing lines) or your shell before launching the daemon. If unset, the vocabulary store remains empty (transcription works without customization) and the model defaults from `DaemonConfig` apply. `ARCHILLES_MODEL_SIZE` / `ARCHILLES_COMPUTE_TYPE` make it easy to trade VRAM for accuracy without editing code — e.g. `large-v3-turbo` with `int8_float16` fits in ~2 GB and transcribes German noticeably better than `small`.

## Custom vocabulary

Point `ARCHILLES_VOCABULARY_PATH` at a Markdown file with two H2 sections:

```markdown
# My Vocabulary

## Vocabulary
<!-- Comma-separated or one per line. Passed to Whisper as initial_prompt. -->
Kubernetes, PostgreSQL, async, middleware
repository, deployment, refactor, endpoint

## Corrections
<!-- Format: wrong -> right (or →). One rule per line. Case-sensitive, word-boundary. -->
cashing -> caching
prompter -> prompt
```

- **Vocabulary** is capped at 150 tokens (Whisper's `initial_prompt` limit); excess entries are logged and truncated.
- **Corrections** are applied after transcription as word-boundary, case-sensitive substitutions; longer keys win on overlap.
- The daemon watches the file via `watchdog` and reloads on save — no restart needed.
- `<!-- HTML comments -->` are stripped before parsing, so you can annotate freely.
- German headers `## Vokabular` and `## Korrekturen` are also recognised as aliases.

## Development

```bat
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m pytest tests/ -v
```

Tests cover the protocol framing, audio recorder / transcription wiring (with mocks), vocabulary parsing and hot-reload, and post-processor edge cases. The test suite does not require CUDA or a microphone.

### Layout

```
daemon.py          TCP server, audio capture, Whisper wrapper
hotkey.ahk         AutoHotkey v2 client (push-to-talk + paste)
protocol.py        Length-prefixed framing
vocabulary.py      Markdown parser + watchdog-backed store
post_processor.py  Word-boundary find/replace
start.bat          Launches daemon + AHK, waits for port 9876
stop.bat           Terminates both processes
tests/             pytest suite
docs/              Design specs and implementation plans
```

## Troubleshooting

- **Tooltip says "Verbindung verloren" or never connects.** The daemon didn't start or crashed. Check `%APPDATA%\archilles-dictateur\daemon.log`.
- **"Port 9876 already in use".** Another daemon is still running. Run `stop.bat`, or find and kill the lingering `python` process.
- **"CUDA not available, falling back to CPU".** The daemon could not load Whisper on GPU. Check `nvidia-smi`, verify your CUDA runtime, and confirm the `nvidia-*` DLLs installed by `pip` are in `venv\Lib\site-packages\nvidia\*\bin`. CPU fallback is fine, just slower.
- **Nothing gets pasted.** The target application may filter `Ctrl+V`. Some terminals require a different paste shortcut; Dictateur currently only sends `Ctrl+V`.

## Known limitations

- Windows only. The AHK client is Windows-specific; porting the client to another OS (e.g., using `pynput` or an X11/Wayland equivalent) is plausible but hasn't been attempted.
- Hotkey is hard-coded to `Ctrl + Left-Win` in `hotkey.ahk`. Change the two `^LWin::` blocks to remap.
- Whisper is called synchronously on STOP. Very long recordings block the daemon until done.
- German is the default language. Change `DaemonConfig.language` or pass a different Whisper model to work in other languages.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — the CTranslate2-based Whisper implementation that does the heavy lifting.
- [AutoHotkey v2](https://www.autohotkey.com/) — the only sane way to bind a global hotkey on Windows.
- [watchdog](https://github.com/gorakhargosh/watchdog) — for the vocabulary hot-reload.
