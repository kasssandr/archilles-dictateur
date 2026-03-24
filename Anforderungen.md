# Anforderungen:

Entwicklung einer lokalen Windows-Anwendung, die es ermöglicht, systemweit per Hotkey (F12) Sprache aufzunehmen, lokal zu transkribieren (Whisper) und den Text automatisch in das aktuell aktive Textfeld einzufügen, unabhängig von der verwendeten Anwendung (z. B. Claude Code, Antigravity, Browser, IDEs).

- Hintergrunddienst ohne sichtbare UI
- Deutsche Sprache als Default
- Audioaufnahme über Standardmikrofon

---

Tech Stack

1. Python 3.10+ | Basis der Anwendung |
2. faster-whisper | Lokale Transkription |
3. AutoHotkey (AHK) | Globaler Hotkey (F12) |
4. sounddevice | Audioaufnahme |
5. pyperclip | Text in Zwischenablage/Einfügen |
6. CUDA / NVIDIA GPU | Hardware-Beschleunigung |