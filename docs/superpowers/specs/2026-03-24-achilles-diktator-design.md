# Achilles Diktator — Design Spec

## Zusammenfassung

Lokale Windows-Anwendung für systemweite Sprache-zu-Text-Eingabe. Der Nutzer hält Ctrl+Win gedrückt, spricht, lässt los — der transkribierte Text wird automatisch in das aktive Textfeld eingefügt.

> **Abweichung von Anforderungen.md:** Der Hotkey wurde von F12 auf Ctrl+Win (gedrückt halten) geändert, um das Verhalten von Wispr Flow nachzubilden. Ctrl+Win hat unter Windows keine relevanten OS-Konflikte (im Gegensatz zu Ctrl+Alt+Entf).

## Architektur

Zwei Prozesse kommunizieren über einen lokalen TCP-Socket:

1. **Python-Daemon** — Läuft dauerhaft im Hintergrund, hält das faster-whisper `small`-Modell im GPU-Speicher (CUDA, float16), lauscht auf `localhost:9876`
2. **AHK-Script (v2)** — Erkennt Ctrl+Win (gedrückt halten), sendet Befehle an den Python-Daemon, fügt transkribierten Text via Zwischenablage ein

## Ablauf

```
Ctrl+Win gedrückt  → AHK sendet "START" an Python → Python startet Audioaufnahme (sounddevice)
Ctrl+Win losgelassen → AHK sendet "STOP" an Python → Python stoppt Aufnahme → transkribiert → sendet Text zurück
AHK empfängt Text   → schreibt in Zwischenablage → simuliert Ctrl+V im aktiven Fenster
```

## Komponenten

### 1. Python-Daemon (`daemon.py`)

- **Whisper-Modell:** faster-whisper, Modell `small`, `float16`, `device="cuda"`
- **Sprache:** Deutsch (`language="de"`)
- **Audio:** `sounddevice` mit Standardmikrofon, 16kHz, mono
- **Socket-Server:** TCP auf `localhost:9876`, akzeptiert eine Verbindung gleichzeitig (single-client)
- **Logging:** Logfile unter `%APPDATA%/achilles-diktator/daemon.log` (rotating, max 1 MB)
- **Modell-Laden:** Einmalig beim Start, bleibt im VRAM (~0,5 GB)
- **Graceful Shutdown:** Reagiert auf SIGTERM / KeyboardInterrupt, gibt Audio-Device und VRAM frei

### 2. TCP-Protokoll

Alle Nachrichten sind length-prefixed: `<4 Bytes Big-Endian Länge><Payload>`.

| Richtung | Nachricht | Beschreibung |
|---|---|---|
| AHK → Python | `START` | Aufnahme starten |
| AHK → Python | `STOP` | Aufnahme stoppen, transkribieren |
| Python → AHK | `RESULT:<text>` | Transkribierter Text (kann Newlines enthalten) |
| Python → AHK | `ERROR:<nachricht>` | Fehlermeldung (z.B. Mikrofon nicht verfügbar) |

Verbindungsmodell: AHK öffnet eine **persistente** Verbindung beim Start und reconnected bei Verbindungsabbruch.

### 3. AHK-Script (`hotkey.ahk`)

- **AutoHotkey v2**
- **Hotkey:** Ctrl+Win (gedrückt halten = Aufnahme, loslassen = Stop)
- **Kommunikation:** TCP-Socket-Client zu `localhost:9876` (persistent, auto-reconnect)
- **Text-Einfügen:** Ergebnis in Zwischenablage schreiben, `Ctrl+V` simulieren
- **Fehlerfall:** Wenn Daemon nicht erreichbar, wird der Tastendruck ignoriert (kein Crash)

### 4. Autostart

- **Startscript:** `start.bat` im Projektverzeichnis
  1. Aktiviert Python venv
  2. Startet `daemon.py` (wartet auf "READY"-Meldung im Log)
  3. Startet `hotkey.ahk`
- **Windows-Autostart:** Shortcut zu `start.bat` im Startup-Ordner (`shell:startup`)
- `start.bat` startet beide Prozesse mit `start /B` (ohne Fenster)

## Fehlerbehandlung

| Szenario | Verhalten |
|---|---|
| Daemon nicht gestartet | AHK: Hotkey wird ignoriert, reconnect-Versuch alle 5 Sek. |
| Mikrofon nicht verfügbar | Daemon sendet `ERROR:NO_MIC`, AHK ignoriert |
| CUDA nicht verfügbar | Daemon fällt auf CPU zurück (`device="cpu"`), loggt Warnung |
| Daemon crasht während Aufnahme | AHK erkennt Verbindungsabbruch, verwirft Session |
| Port 9876 belegt | Daemon loggt Fehler und beendet sich |

## Tech Stack

| Komponente | Technologie |
|---|---|
| Basis | Python 3.10+ |
| Transkription | faster-whisper (`small`, float16, CUDA) |
| Hotkey | AutoHotkey v2 |
| Audioaufnahme | sounddevice (16kHz, mono) |
| Text-Einfügen | Zwischenablage + Ctrl+V (via AHK) |
| IPC | TCP-Socket (localhost:9876), length-prefixed |
| GPU | NVIDIA Quadro T1000 (4 GB VRAM) |

## Konfiguration

Alle Werte als Konstanten am Anfang von `daemon.py` und `hotkey.ahk`:

- Whisper-Modell: `small` (wechselbar auf `medium`/`tiny`)
- Sprache: `de` (Deutsch)
- Port: `9876`
- Audio: 16kHz, mono, Standardmikrofon

> Sprachwechsel (z.B. Englisch) ist out-of-scope für v1.

## Einschränkungen

- Überschreibt den aktuellen Inhalt der Zwischenablage beim Einfügen
- Benötigt NVIDIA GPU mit CUDA-Support (CPU-Fallback verfügbar, aber langsamer)
- AutoHotkey v2 muss installiert sein
- VRAM-Budget: ~0,5 GB für Whisper, Rest frei für andere GPU-Aufgaben (Vektor-Embedding)
- Latenz auf Quadro T1000: geschätzt 1-3 Sek. je nach Sprachlänge (bei Bedarf auf `tiny` wechseln)
