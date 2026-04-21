# Anforderungen

Entwicklung einer lokalen Windows-Anwendung, die es ermöglicht, systemweit per Hotkey Sprache aufzunehmen, lokal zu transkribieren (Whisper) und den Text automatisch in das aktuell aktive Textfeld einzufügen, unabhängig von der verwendeten Anwendung (z. B. Claude Code, Antigravity, Browser, IDEs).

- Hintergrunddienst ohne sichtbare UI
- Deutsche Sprache als Default
- Audioaufnahme über Standardmikrofon
- Push-to-talk: Hotkey halten = Aufnahme, loslassen = Transkription + Einfügen

## Hotkey

Aktuell: **`Strg + linke Windows-Taste`** (Push-to-talk).

Ursprünglich war F12 vorgesehen. In der Praxis zwei Probleme:
- F12 ist einhändig schlecht erreichbar; eine Tastenkombination am unteren Rand der Tastatur funktioniert flüssiger.
- Vor der Umstellung auf den AutoHotkey-v2-Client lief das F12-Binding instabil.

Der Wechsel auf `Strg + linke Windows-Taste` in Kombination mit `hotkey.ahk` hat beides behoben.

## Tech Stack

1. Python 3.10+ — Basis der Anwendung
2. faster-whisper — Lokale Transkription (CUDA `float16`, CPU-Fallback `int8`)
3. AutoHotkey v2 — Globaler Hotkey & Paste
4. sounddevice — Audioaufnahme
5. watchdog — Hot-Reload der Vokabular-Datei
6. CUDA / NVIDIA GPU — Hardware-Beschleunigung (optional, fällt auf CPU zurück)
