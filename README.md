# Dictateur

System-wide, offline push-to-talk dictation for Windows. Hold a hotkey, speak, release — your words appear in whatever text field has focus. Transcription runs locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper); no audio leaves your machine.

Dictateur is the dictation front-end of the **Archilles** toolchain — a small family of local-first language tools. Its sibling, the [Archillator](https://archilles.org/archillator/), cleans, corrects, and translates long-form text. Dictateur handles the input side: getting words from voice into any application (IDE, browser, chat, editor) without switching contexts.

## Features

- **Push-to-talk, globally.** Hold `Ctrl + Left-Win`, speak, release. Transcribed text is pasted into the active window.
- **Fully local.** Audio is recorded, transcribed, and discarded on your machine. No cloud APIs.
- **GPU-accelerated with CPU fallback.** Uses CUDA + `int8_float16` when available; falls back transparently to CPU `int8`.
- **Gives the GPU back when idle.** After five minutes without dictation the model releases its VRAM, so a local LLM or another GPU job can use it. The next hotkey press reloads it while you are still speaking, so the reload costs no perceptible latency. Tune with `DICTATEUR_IDLE_UNLOAD_MINUTES`.
- **Custom vocabulary, hot-reloaded.** Point the daemon at a Markdown file; it feeds domain terms to Whisper as an `initial_prompt` and applies deterministic find/replace corrections post-transcription. Edit the file in any editor — changes take effect immediately.
- **Auto-detects the language.** Speak German or English and each recording is transcribed in the language you actually spoke, not translated. Pin one language with `DICTATEUR_LANGUAGE` if you prefer.
- **Spoken punctuation.** Say `Absatz`, `Klammer auf`, `Gedankenstrich`, `Anführungszeichen zu` and the like; the daemon inserts the symbol locally. See [Voice commands](#voice-commands).
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
- **NVIDIA GPU with CUDA** recommended (any recent consumer card works; the daemon uses the `medium` Whisper model in `int8_float16`, which needs roughly 0.75 GB of VRAM). Without CUDA, the daemon automatically falls back to CPU at `int8` — slower but functional.
- **A working microphone** reachable through the default Windows audio device.

## Installation

```bat
git clone https://github.com/kasssandr/archilles-dictateur.git
cd archilles-dictateur

python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

On first run, faster-whisper downloads the Whisper `medium` model (~1.5 GB) into its cache.

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

| Field                 | Default     | Notes                                        |
| --------------------- | ----------- | -------------------------------------------- |
| `model_size`          | `medium`    | Any faster-whisper model tag.                |
| `language`            | `auto`      | `auto` detects the spoken language per recording; a code like `en`, `de`, `fr` or `es` pins it. |
| `host` / `port`       | `localhost:9876` | TCP endpoint the AHK client connects to.|
| `sample_rate`         | `16000`     | Matches Whisper's expected input.            |
| `device`              | `cuda`      | Auto-falls-back to `cpu` on failure.         |
| `compute_type`        | `int8_float16` | Uses `int8` on CPU fallback.              |
| `idle_unload_minutes` | `5.0`       | Release VRAM after this idle time; `0` keeps the model resident. |

Five runtime knobs are read from the environment:

```
DICTATEUR_VOCABULARY_PATH=C:\path\to\your\Vokabular.md
DICTATEUR_MODEL_SIZE=large-v3-turbo
DICTATEUR_COMPUTE_TYPE=int8_float16
DICTATEUR_IDLE_UNLOAD_MINUTES=10
DICTATEUR_LANGUAGE=de
```

Set them in `start.bat` (see the existing lines) or your shell before launching the daemon. If unset, the vocabulary store remains empty (transcription works without customization) and the model defaults from `DaemonConfig` apply.

`DICTATEUR_MODEL_SIZE` / `DICTATEUR_COMPUTE_TYPE` trade VRAM for accuracy without editing code — `large-v3-turbo` with `int8_float16` fits in ~2 GB and transcribes German better still than `medium`, if you have the headroom.

`DICTATEUR_LANGUAGE` defaults to `auto`: Whisper detects the language of each recording, so an English sentence is transcribed as English and a German one as German. Detection runs per recording, not per word, so dictate whole sentences — very short utterances can be misdetected. Set it to a fixed code like `de` if you only ever dictate in one language and want the steadier behaviour.

### Idle unloading

The daemon starts without touching the GPU, loads the model on the first dictation, and unloads it again after `idle_unload_minutes` without use. This matters on small cards: on a 4 GB GPU, a resident Whisper model is a quarter of everything you have, and a local LLM will not fit alongside it.

The reload is hidden rather than merely fast: the model starts loading the moment you press the hotkey, in parallel with you speaking, so it is usually ready by the time you release. Loading `medium` takes about 5 seconds, so a dictation that runs longer than that hides the reload completely. Dictate a two-word sentence right after a long pause and you will wait for the remainder — once, until the model unloads again.

If that trade annoys you, raise `DICTATEUR_IDLE_UNLOAD_MINUTES` (fewer unloads, VRAM held longer) or set it to `0`.

Set `DICTATEUR_IDLE_UNLOAD_MINUTES=0` to disable unloading and keep the model resident for the whole session — the old behaviour, and the right choice when the GPU is yours alone.

## Custom vocabulary

Point `DICTATEUR_VOCABULARY_PATH` at a Markdown file with two H2 sections:

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

## Voice commands

Whisper already sets commas and sentence periods from prosody. For punctuation and
formatting it cannot infer, speak the command out loud and the daemon substitutes the
symbol locally — no extra model, no latency:

| Say (German)                              | Inserts        |
| ----------------------------------------- | -------------- |
| `Absatz`                                  | blank line (¶) |
| `neue Zeile`                              | line break     |
| `Komma` · `Doppelpunkt` · `Semikolon`     | `,` `:` `;`    |
| `Fragezeichen` · `Ausrufezeichen`         | `?` `!`        |
| `Klammer auf` … `Klammer zu`              | `(` … `)`      |
| `Anführungszeichen auf` … `Anführungszeichen zu` | `„` … `“` |
| `Gedankenstrich`                          | `–` (spaced)   |
| `Bindestrich` · `Schrägstrich`            | `-` `/`        |

Matching is case-insensitive and word-boundary sensitive, so `Absatz` inside
`Absatzweise` is left alone. Detection is per word: speak the command as a distinct
word. Two caveats:

- **Collisions.** If you actually mean the word (\"der wunde Punkt\"), it still gets
  replaced. That is why very common words are excluded — notably **`Punkt`**: Whisper
  already ends sentences with periods, and the bare word appears too often in normal
  speech. Add it yourself in `post_processor.py` if you want it.
- Whisper occasionally mishears a command on very short, mumbled utterances — the same
  trade-off as language auto-detection. Speak whole, clear sentences.

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
post_processor.py  Word-boundary find/replace + spoken punctuation commands
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
- Language is auto-detected per recording by default. Set `DICTATEUR_LANGUAGE` (or `DaemonConfig.language`) to a fixed code like `de` to pin one language.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — the CTranslate2-based Whisper implementation that does the heavy lifting.
- [AutoHotkey v2](https://www.autohotkey.com/) — the only sane way to bind a global hotkey on Windows.
- [watchdog](https://github.com/gorakhargosh/watchdog) — for the vocabulary hot-reload.
