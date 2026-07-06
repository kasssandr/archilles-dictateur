# Vokabular-Integration Phase 1 — Design Spec

## Zusammenfassung

Erweiterung des Archilles Dictateur um ein manuell gepflegtes Fachbegriffs-/Korrekturen-Wörterbuch. Die Datei liegt im Obsidian-Vault des Nutzers (`D:\Archilles-Lab\Dictateur\Vokabular.md`) und wird vom Daemon automatisch beim Start und bei jeder Dateiänderung eingelesen. Zweck: Whisper erkennt Fachbegriffe wie „Claude", „Anthropic" oder „Merovinger" zuverlässiger, und systematische Fehltranskriptionen werden im Nachgang automatisch korrigiert.

Phase 1 ist bewusst minimal: keine Automatik, kein LLM, kein Lern-Hotkey. Die Vokabular-Datei wird manuell in Obsidian gepflegt. Phase 2 (LLM-Polish via Ollama) wird separat designt und ergänzt die Pipeline, ohne Phase 1 abzulösen.

## Motivation und Abgrenzung

**Problem:** Whisper fehlt jede Form persistenten Nutzer-Vokabulars. Wörter wie „Claude" werden konsequent als „Cloud" transkribiert, Eigennamen bleiben außerhalb des Modell-Wissens, und es gibt keinen Mechanismus, aus wiederholten Korrekturen zu lernen.

**Was Phase 1 löst:**
- Fachbegriffe / Eigennamen, die Whisper bei Kenntnis des Kontexts erkennen *könnte* (via `initial_prompt`).
- Deterministische Falsch-/Richtig-Mappings für Wörter, die Whisper dennoch konsistent falsch liefert (via Post-Processing).

**Was Phase 1 bewusst nicht löst:**
- Morphologische Varianten unbekannter Begriffe (z.B. „Meroweg" als Ableitung von „Merovinger") — hierfür ist Phase 2 vorgesehen.
- Grammatikalische/stilistische Korrekturen, Kontextverständnis — Phase 2.
- Automatisches Lernen aus Nutzer-Korrekturen — explizit out-of-scope.

## Architektur

```
┌────────────────────────────┐
│ Obsidian Vault             │
│ D:\Archilles-Lab\Dictateur\ │  ← Nutzer editiert manuell
│  Vokabular.md              │
└────────────┬───────────────┘
             │ (watchdog File-Watch)
             ▼
┌─────────────────────────────────────────────┐
│ Daemon (Python)                             │
│                                             │
│  VocabularyStore  (neu)                     │
│   ├─ lädt und parst die Markdown-Datei      │
│   ├─ watchdog-Observer (eigener Thread)     │
│   ├─ Lock-geschützter aktueller Zustand     │
│   └─ get_prompt(), get_corrections()        │
│                                             │
│  TranscriptionService  (angepasst)          │
│   └─ transcribe(audio, initial_prompt=...)  │
│                                             │
│  apply_corrections  (neu, frei in module)   │
│   └─ word-boundary Find-Replace             │
│                                             │
│  DaemonServer  (angepasst)                  │
│   └─ STOP-Handler:                          │
│       prompt = store.get_prompt()           │
│       text = transcribe(audio, prompt)      │
│       text = apply_corrections(text, corr)  │
│       send RESULT:text                      │
└─────────────────────────────────────────────┘
```

Keine Änderungen am TCP-Protokoll, keine Änderungen am AHK-Client.

## Komponenten

### 1. Vokabular-Datei (`D:\Archilles-Lab\Dictateur\Vokabular.md`)

Markdown-Datei mit zwei Abschnitten. Wird vom Nutzer in Obsidian gepflegt.

**Format:**

```markdown
# Archilles Dictateur Vokabular

Diese Datei wird automatisch vom Daemon gelesen.
Änderungen werden sofort wirksam (Hot-Reload).

## Vokabular
<!-- Kommagetrennt oder zeilenweise. Geht als initial_prompt an Whisper. -->
Claude, Anthropic, Archilles, Dictateur, faster-whisper
Antigravity, Obsidian, Merovinger, merowingisch, Meroweg
TypeScript, Python, Ollama, Gemma

## Korrekturen
<!-- Format: Falsch -> Richtig. Eine Regel pro Zeile. Case-sensitive. -->
Cloud -> Claude
Clod -> Claude
Klod -> Claude
Diktator -> Dictateur
```

**Parsing-Regeln:**
- Nur Inhalt zwischen `## Vokabular` / `## Korrekturen` und dem nächsten `##`-Header (oder Dateiende) wird gelesen.
- HTML-Kommentare (`<!-- ... -->`) und Leerzeilen werden ignoriert.
- Vokabular-Abschnitt: alle Zeilen werden an `,` und Whitespace gesplittet; leere Tokens verworfen.
- Korrekturen-Abschnitt: jede nicht-leere Zeile muss dem Muster `Falsch -> Richtig` oder `Falsch → Richtig` entsprechen. Zeilen, die das Muster nicht erfüllen, werden mit einer Warnung geloggt und übersprungen.
- Header-Suche ist case-insensitive (`## Vokabular` = `## VOKABULAR` = `## vokabular`).

### 2. `VocabularyStore` (neu, in `vocabulary.py`)

Verantwortlich für Laden, Parsen und Aktualisieren des Wörterbuch-Zustands.

**Öffentliches Interface:**
```python
class VocabularyStore:
    def __init__(self, path: Path | None, logger: logging.Logger):
        """Startet File-Watching; lädt initial. Bei path=None: Store bleibt leer."""

    def get_prompt(self) -> str:
        """Gibt den kombinierten Vokabular-String für initial_prompt zurück."""

    def get_corrections(self) -> dict[str, str]:
        """Gibt eine Kopie der aktuellen Korrekturen-Map zurück."""

    def stop(self) -> None:
        """Beendet den File-Watcher-Thread sauber (für Shutdown)."""
```

**Implementierungs-Details:**
- Nutzt `watchdog.observers.Observer` mit einem `FileSystemEventHandler`, der auf `on_modified` hört.
- Ein `threading.Lock` schützt die Felder `_prompt` und `_corrections`. Reader kopieren beim Zugriff.
- Parsing und Neuladen passieren im Observer-Thread; Fehler (Datei nicht lesbar, Parse-Fehler) werden geloggt, nicht geworfen. Letzter bekannter Zustand bleibt aktiv.
- Bei `path is None` oder nicht existierender Datei: Logger-Warnung, Store liefert `""` bzw. `{}`.

**Format des `initial_prompt`:**
Die Vokabular-Tokens werden zu einem einzigen Kommagetrennten String konkateniert. Whisper erwartet Freitext, aber eine kommaseparierte Liste funktioniert empirisch gut und ist platzsparend.

Wenn der resultierende String mehr als ~200 Tokens (grob: 150 Wörter) umfasst, wird er am Wort-Ende gekürzt und eine Warnung geloggt. Token-Schätzung: heuristisch über `len(prompt.split()) > 150` — exakte Tokenisierung ist nicht nötig.

### 3. `apply_corrections` (neu, in `post_processor.py`)

Freie Funktion, keine Klasse. Nimmt Text und Mapping, liefert korrigierten Text.

```python
def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Ersetzt Wörter in text gemäß corrections, word-boundary-sensitiv."""
```

**Regeln:**
- Word-Boundary-sensitiv: `re.sub(r'\b' + re.escape(wrong) + r'\b', right, text)`. Verhindert Treffer *innerhalb* von Wörtern.
- Case-sensitive. Wer „cloud" und „Cloud" unterschiedlich behandeln will, pflegt beide Einträge.
- Reihenfolge: längere Keys zuerst, damit Präfix-Konflikte (z.B. „Cloud" vor „Clo") deterministisch aufgelöst werden.

### 4. Änderungen an `daemon.py`

**`DaemonConfig`** — neues Feld:
```python
vocabulary_path: Path | None = None
```
Wird in `main()` aus `os.environ.get("ARCHILLES_VOCABULARY_PATH")` gesetzt (None, wenn nicht gesetzt).

**`DaemonServer`** — hält `self.vocabulary = VocabularyStore(config.vocabulary_path, self.logger)`.

**`DaemonServer._handle_client`** im `STOP`-Zweig:
```python
audio = self.recorder.stop()
if len(audio) == 0:
    send_message(stream, "RESULT:")
    continue

prompt = self.vocabulary.get_prompt()
text = self.transcriber.transcribe(audio, language=self.config.language, initial_prompt=prompt)
text = apply_corrections(text, self.vocabulary.get_corrections())
send_message(stream, f"RESULT:{text}")
```

**`TranscriptionService.transcribe`** bekommt optionalen `initial_prompt` Parameter, den es an `self.model.transcribe(...)` durchreicht. Wenn leerer String: nicht gesetzt.

**`DaemonServer.shutdown`** ruft zusätzlich `self.vocabulary.stop()` auf.

### 5. Änderungen an `start.bat`

Die ENV-Variable wird explizit gesetzt:
```batch
set ARCHILLES_VOCABULARY_PATH=D:\Archilles-Lab\Dictateur\Vokabular.md
```

Platziert vor dem `start /B ... python.exe ...` Aufruf.

### 6. Initiale Vokabular-Datei

Eine minimale erste Version der Datei wird im Zuge der Umsetzung angelegt (unter `D:\Archilles-Lab\Dictateur\Vokabular.md`), damit der Daemon beim ersten Start nicht eine fehlende Datei sieht. Inhalt: die Begriffe, die aus bisheriger Erfahrung problematisch sind (Claude, Anthropic, Archilles, Dictateur, Antigravity, Obsidian) und die aus dieser Session bekannten Korrekturen (Cloud→Claude, Klod→Claude).

## Tests

Neue Test-Dateien:

- `tests/test_vocabulary.py`
  - Parsing: Leerzeilen, Kommentare, verschiedene Trenner, fehlende Abschnitte
  - Fehler-Robustheit: Datei nicht vorhanden, leere Datei, kaputte Zeilen
  - File-Watching: Änderung der Datei → Store-Zustand aktualisiert sich (mit kurzem Poll + Timeout)
  - Shutdown: `stop()` beendet Observer sauber
- `tests/test_post_processor.py`
  - Word-Boundary: `Cloud→Claude` ersetzt „Cloud", aber nicht „Clouds" oder „Clouding"
  - Reihenfolge: längere Keys gewinnen gegen kürzere
  - Leere Maps / leerer Text → Identität
  - Unicode: Umlaute, „→" als Pfeil-Variante

Bestehende `tests/test_daemon.py` bleibt. Keine Integration-Tests gegen echtes Whisper nötig.

## Konfiguration

- **`ARCHILLES_VOCABULARY_PATH`** (ENV): Absolutpfad zur Markdown-Datei. Default: nicht gesetzt → Store bleibt leer, Daemon funktioniert wie bisher (graceful degradation).
- Kein Auto-Discovery des Obsidian-Pfads — explizit in `start.bat`.

## Fehlerbehandlung

| Szenario | Verhalten |
|---|---|
| `ARCHILLES_VOCABULARY_PATH` nicht gesetzt | Store leer, Daemon läuft unverändert, INFO-Log |
| Pfad gesetzt, aber Datei existiert nicht | Store leer, WARNING-Log, File-Watcher wartet auf Datei-Erstellung |
| Datei unlesbar (Permissions) | Store leer, ERROR-Log, Retry beim nächsten Änderungs-Event |
| Parsing-Fehler einer Zeile | Zeile übersprungen, WARNING-Log mit Zeilennummer |
| Vokabular > ~200 Tokens | Am Wort-Ende gekürzt, WARNING-Log |
| Whisper ignoriert den Prompt | Keine Fehlermeldung — Fallback auf leere Transkription ist ok |
| `watchdog` nicht installiert | Import-Error beim Daemon-Start → klare Fehlermeldung, Prozess beendet sich |

## Abhängigkeiten

Neu in `requirements.txt`:
- `watchdog` (File-Watching, weit verbreitet, ~5 Transitiv-Deps)

Keine weiteren neuen Deps. Kein LLM/Ollama in Phase 1.

## Phase-2-Kompatibilität

Das Design ist so aufgebaut, dass der LLM-Polish-Schritt in Phase 2 als *eine weitere Zeile* zwischen `apply_corrections` und `send_message` eingehängt wird:

```python
# Phase 1:
text = self.transcriber.transcribe(audio, ..., initial_prompt=prompt)
text = apply_corrections(text, self.vocabulary.get_corrections())
# Phase 2 (später):
text = llm_polish(text, vocabulary=self.vocabulary.get_full_vocabulary())
send_message(stream, f"RESULT:{text}")
```

Die `VocabularyStore` bleibt die zentrale Informationsquelle — nur das Format, in dem das Vokabular ans LLM geht, wird in Phase 2 definiert.

## Einschränkungen

- Morphologische Varianten müssen in Phase 1 einzeln eingetragen werden, wenn sie Whisper falsch hört. Phase 2 hebt diese Einschränkung auf.
- Kein Feedback-Loop: Wenn eine Korrektur nicht greift, muss der Nutzer die Datei erweitern. Es gibt keinen Hinweis im Log, *welche* Korrekturen wie oft gegriffen haben (hierfür wäre Telemetry nötig — out-of-scope).
- Case-sensitive Korrekturen können bei Satzanfängen unschön sein (z.B. „Cloud" am Satzanfang vs. „cloud" mitten im Satz). Workaround: beide Formen eintragen. Phase 2 löst das durch LLM-Kontext.
- Der File-Watcher hat einen kleinen Delay (meist <500ms). In der Praxis ist das unproblematisch, weil der nächste Diktat-Vorgang ohnehin mehrere Sekunden später kommt.
