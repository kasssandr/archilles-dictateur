# Achilles Diktator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Windows speech-to-text app where holding Ctrl+Win records speech, transcribes it locally via faster-whisper, and pastes the text into the active window.

**Architecture:** Python daemon holds the Whisper model in GPU memory and listens on a TCP socket. An AutoHotkey v2 script detects Ctrl+Win hold/release and communicates with the daemon via length-prefixed TCP messages. Text is inserted via clipboard + Ctrl+V.

**Tech Stack:** Python 3.12, faster-whisper (small, float16, CUDA), sounddevice, AutoHotkey v2, TCP sockets

**Spec:** `docs/superpowers/specs/2026-03-24-achilles-diktator-design.md`

---

## File Structure

```
archilles_diktator/
├── daemon.py          # Python daemon: socket server, audio recording, transcription
├── protocol.py        # Length-prefixed TCP protocol helpers (send/recv)
├── hotkey.ahk         # AHK v2 script: hotkey detection, socket client, clipboard paste
├── start.bat          # Startup script: launches daemon + AHK
├── requirements.txt   # Python dependencies
├── pyproject.toml     # Project config (pytest settings)
├── .gitignore         # Ignore venv, __pycache__, logs
├── tests/
│   ├── test_protocol.py   # Unit tests for protocol helpers
│   └── test_daemon.py     # Unit tests for daemon logic (transcription, audio buffer)
├── docs/              # (existing)
└── Anforderungen.md   # (existing)
```

---

## Task 1: Project Setup & Dependencies

**Files:**
- Create: `requirements.txt`
- Create: `venv` (virtual environment)

- [ ] **Step 1: Create .gitignore**

```
venv/
__pycache__/
*.pyc
*.log
.pytest_cache/
```

- [ ] **Step 2: Create requirements.txt**

```
faster-whisper
sounddevice
numpy
pytest
```

- [ ] **Step 3: Create pyproject.toml** (pytest config so tests can import from project root)

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

- [ ] **Step 4: Create virtual environment and install dependencies**

Run:
```bash
cd c:/Users/tomra/archilles_diktator
python -m venv venv
./venv/Scripts/activate
pip install -r requirements.txt
```

Expected: All packages install successfully. `faster-whisper` pulls in CTranslate2 with CUDA support.

- [ ] **Step 5: Verify CUDA and sounddevice work**

Run:
```bash
nvidia-smi
python -c "import sounddevice; print(sounddevice.query_devices())"
python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny', device='cuda', compute_type='float16'); print('CUDA OK')"
```

Expected: GPU visible, microphone listed, `CUDA OK` printed.

- [ ] **Step 6: Initialize git repo and commit**

Run:
```bash
git init
git add .gitignore requirements.txt pyproject.toml Anforderungen.md docs/
git commit -m "chore: initial project setup with requirements and design spec"
```

---

## Task 2: TCP Protocol Helpers

**Files:**
- Create: `protocol.py`
- Create: `tests/test_protocol.py`

- [ ] **Step 1: Write failing tests for protocol**

```python
# tests/test_protocol.py
import struct
import io
from protocol import send_message, recv_message


def test_send_message_prepends_length():
    buf = io.BytesIO()
    send_message(buf, "START")
    buf.seek(0)
    length = struct.unpack(">I", buf.read(4))[0]
    payload = buf.read(length).decode("utf-8")
    assert length == 5
    assert payload == "START"


def test_recv_message_reads_length_prefixed():
    buf = io.BytesIO()
    msg = "RESULT:Hallo Welt"
    encoded = msg.encode("utf-8")
    buf.write(struct.pack(">I", len(encoded)))
    buf.write(encoded)
    buf.seek(0)
    result = recv_message(buf)
    assert result == "RESULT:Hallo Welt"


def test_roundtrip_with_newlines():
    buf = io.BytesIO()
    msg = "RESULT:Zeile eins\nZeile zwei\nZeile drei"
    send_message(buf, msg)
    buf.seek(0)
    result = recv_message(buf)
    assert result == msg


def test_recv_message_empty_stream_returns_none():
    buf = io.BytesIO(b"")
    result = recv_message(buf)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_protocol.py -v`
Expected: FAIL (module `protocol` not found)

- [ ] **Step 3: Implement protocol.py**

```python
# protocol.py
import struct


def send_message(stream, message: str) -> None:
    encoded = message.encode("utf-8")
    stream.write(struct.pack(">I", len(encoded)))
    stream.write(encoded)
    if hasattr(stream, "flush"):
        stream.flush()


def recv_message(stream) -> str | None:
    header = stream.read(4)
    if not header or len(header) < 4:
        return None
    length = struct.unpack(">I", header)[0]
    data = stream.read(length)
    if not data or len(data) < length:
        return None
    return data.decode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_protocol.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add protocol.py tests/test_protocol.py
git commit -m "feat: add length-prefixed TCP protocol helpers with tests"
```

---

## Task 3: Python Daemon — Core Logic

**Files:**
- Create: `daemon.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing tests for daemon components**

```python
# tests/test_daemon.py
import numpy as np
from unittest.mock import MagicMock, patch
from daemon import AudioRecorder, TranscriptionService, DaemonConfig


def test_config_defaults():
    cfg = DaemonConfig()
    assert cfg.model_size == "small"
    assert cfg.language == "de"
    assert cfg.port == 9876
    assert cfg.sample_rate == 16000


@patch("daemon.sd.InputStream")
def test_audio_recorder_start_stop(mock_stream_cls):
    mock_stream = MagicMock()
    mock_stream_cls.return_value = mock_stream
    recorder = AudioRecorder(sample_rate=16000)
    recorder.start()
    assert recorder.is_recording
    # Simulate audio callback
    fake_audio = np.random.randn(1024, 1).astype(np.float32)
    recorder._callback(fake_audio, 1024, None, None)
    audio = recorder.stop()
    assert isinstance(audio, np.ndarray)
    assert len(audio) == 1024
    assert not recorder.is_recording
    mock_stream.start.assert_called_once()
    mock_stream.stop.assert_called_once()


def test_audio_recorder_stop_without_start_returns_empty():
    recorder = AudioRecorder(sample_rate=16000)
    audio = recorder.stop()
    assert len(audio) == 0


def test_transcription_service_returns_string():
    with patch("daemon.WhisperModel") as MockModel:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = (
            [MagicMock(text="Hallo Welt")],
            MagicMock(language="de"),
        )
        MockModel.return_value = mock_instance
        service = TranscriptionService(model_size="tiny", device="cpu", compute_type="int8")
        audio = np.zeros(16000, dtype=np.float32)
        result = service.transcribe(audio)
        assert result == "Hallo Welt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: FAIL (module `daemon` not found)

- [ ] **Step 3: Implement daemon.py**

```python
# daemon.py
import logging
import signal
import socket
import sys
import threading
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from protocol import send_message, recv_message

# --- Configuration ---

@dataclass
class DaemonConfig:
    model_size: str = "small"
    language: str = "de"
    port: int = 9876
    host: str = "localhost"
    sample_rate: int = 16000
    device: str = "cuda"
    compute_type: str = "float16"


# --- Logging ---

def setup_logging() -> logging.Logger:
    log_dir = Path.home() / "AppData" / "Roaming" / "achilles-diktator"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    logger = logging.getLogger("achilles")
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=1)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console)

    return logger


# --- Audio Recorder ---

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.is_recording = False
        self._buffer: list[np.ndarray] = []
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        if self.is_recording:
            self._buffer.append(indata[:, 0].copy())

    def start(self):
        self._buffer = []
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self.is_recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._buffer:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._buffer)


# --- Transcription ---

class TranscriptionService:
    def __init__(self, model_size: str = "small", device: str = "cuda", compute_type: str = "float16"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, language: str = "de") -> str:
        segments, _ = self.model.transcribe(audio, language=language)
        return "".join(seg.text for seg in segments).strip()


# --- Socket Server ---

class DaemonServer:
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.logger = setup_logging()
        self.running = False
        self.recorder = AudioRecorder(sample_rate=config.sample_rate)
        self.transcriber = None
        self._server_socket = None

    def _load_model(self):
        try:
            self.transcriber = TranscriptionService(
                model_size=self.config.model_size,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
            self.logger.info("Whisper model '%s' loaded on %s", self.config.model_size, self.config.device)
        except Exception:
            self.logger.warning("CUDA not available, falling back to CPU")
            self.transcriber = TranscriptionService(
                model_size=self.config.model_size,
                device="cpu",
                compute_type="int8",
            )

    def _handle_client(self, conn: socket.socket):
        self.logger.info("Client connected")
        stream = conn.makefile("rwb")
        try:
            while self.running:
                msg = recv_message(stream)
                if msg is None:
                    break
                self.logger.info("Received: %s", msg)

                if msg == "START":
                    try:
                        self.recorder.start()
                        self.logger.info("Recording started")
                    except Exception as e:
                        self.logger.error("Mic error: %s", e)
                        send_message(stream, f"ERROR:NO_MIC:{e}")

                elif msg == "STOP":
                    audio = self.recorder.stop()
                    self.logger.info("Recording stopped, %d samples", len(audio))

                    if len(audio) == 0:
                        send_message(stream, "RESULT:")
                        continue

                    try:
                        text = self.transcriber.transcribe(audio, language=self.config.language)
                        self.logger.info("Transcribed: %s", text)
                        send_message(stream, f"RESULT:{text}")
                    except Exception as e:
                        self.logger.error("Transcription error: %s", e)
                        send_message(stream, f"ERROR:TRANSCRIPTION:{e}")
        except (ConnectionResetError, BrokenPipeError):
            self.logger.info("Client disconnected")
        finally:
            stream.close()
            conn.close()

    def start(self):
        self._load_model()
        self.running = True

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._server_socket.bind((self.config.host, self.config.port))
        except OSError as e:
            self.logger.error("Port %d already in use: %s", self.config.port, e)
            sys.exit(1)

        self._server_socket.listen(1)
        self._server_socket.settimeout(1.0)
        self.logger.info("READY - Listening on %s:%d", self.config.host, self.config.port)

        while self.running:
            try:
                conn, addr = self._server_socket.accept()
                self._handle_client(conn)
            except socket.timeout:
                continue
            except OSError:
                break

    def shutdown(self):
        self.logger.info("Shutting down...")
        self.running = False
        if self.recorder.is_recording:
            self.recorder.stop()
        if self._server_socket:
            self._server_socket.close()


def main():
    config = DaemonConfig()
    server = DaemonServer(config)

    def signal_handler(sig, frame):
        server.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add daemon.py tests/test_daemon.py
git commit -m "feat: add Python daemon with audio recording, transcription, and socket server"
```

---

## Task 4: AutoHotkey v2 Script

**Files:**
- Create: `hotkey.ahk`

> **Note:** AHK scripts are not unit-testable in the traditional sense. This task is tested manually by running the daemon + AHK script together.

- [ ] **Step 1: Install AutoHotkey v2**

Run (from PowerShell):
```powershell
winget install AutoHotkey.AutoHotkey
```

Verify installation:
```bash
where autohotkey
```
Expected: Path like `C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe`

If `winget` not available, download installer manually from https://www.autohotkey.com/ — choose "v2.0" during setup.

- [ ] **Step 2: Write hotkey.ahk**

```autohotkey
; hotkey.ahk — Achilles Diktator AHK v2 Client
; Ctrl+Win hold = record, release = stop + transcribe + paste
#Requires AutoHotkey v2.0
#SingleInstance Force

; --- Configuration ---
global HOST := "127.0.0.1"
global PORT := 9876
global RECONNECT_INTERVAL := 5000  ; ms

; --- State ---
global sock := 0
global isConnected := false
global isRecording := false

; --- TCP Helpers ---

Connect() {
    global sock, isConnected
    try {
        sock := SocketCreate()
        SocketConnect(sock, HOST, PORT)
        isConnected := true
    } catch {
        isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

TryReconnect() {
    if !isConnected
        Connect()
}

SocketCreate() {
    static ws2 := DllCall("LoadLibrary", "Str", "ws2_32", "Ptr")
    static wsaData := Buffer(408)
    static init := DllCall("ws2_32\WSAStartup", "UShort", 0x0202, "Ptr", wsaData)
    s := DllCall("ws2_32\socket", "Int", 2, "Int", 1, "Int", 6, "UInt")
    if s = 0xFFFFFFFF
        throw Error("socket() failed")
    return s
}

SocketConnect(s, host, port) {
    addr := Buffer(16, 0)
    NumPut("UShort", 2, addr, 0)  ; AF_INET
    NumPut("UShort", DllCall("ws2_32\htons", "UShort", port, "UShort"), addr, 2)
    NumPut("UInt", DllCall("ws2_32\inet_addr", "AStr", host, "UInt"), addr, 4)
    result := DllCall("ws2_32\connect", "UInt", s, "Ptr", addr, "Int", 16, "Int")
    if result != 0
        throw Error("connect() failed")
}

SendMsg(s, message) {
    encoded := Buffer(StrPut(message, "UTF-8") - 1)
    StrPut(message, encoded, "UTF-8")
    len := encoded.Size

    ; Length prefix (4 bytes big-endian)
    header := Buffer(4)
    NumPut("UChar", (len >> 24) & 0xFF, header, 0)
    NumPut("UChar", (len >> 16) & 0xFF, header, 1)
    NumPut("UChar", (len >> 8) & 0xFF, header, 2)
    NumPut("UChar", len & 0xFF, header, 3)

    DllCall("ws2_32\send", "UInt", s, "Ptr", header, "Int", 4, "Int", 0)
    DllCall("ws2_32\send", "UInt", s, "Ptr", encoded, "Int", len, "Int", 0)
}

RecvMsg(s) {
    ; Read 4-byte length header
    header := Buffer(4)
    bytesRead := DllCall("ws2_32\recv", "UInt", s, "Ptr", header, "Int", 4, "Int", 0, "Int")
    if bytesRead <= 0 {
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
        return ""
    }

    len := (NumGet(header, 0, "UChar") << 24)
        | (NumGet(header, 1, "UChar") << 16)
        | (NumGet(header, 2, "UChar") << 8)
        | NumGet(header, 3, "UChar")

    if len = 0
        return ""

    data := Buffer(len)
    totalRead := 0
    while totalRead < len {
        n := DllCall("ws2_32\recv", "UInt", s, "Ptr", data.Ptr + totalRead, "Int", len - totalRead, "Int", 0, "Int")
        if n <= 0
            break
        totalRead += n
    }

    return StrGet(data, len, "UTF-8")
}

SocketClose(s) {
    DllCall("ws2_32\closesocket", "UInt", s)
}

; --- Hotkey: Ctrl+Win ---

; Key down: start recording
~LCtrl & LWin:: {
    global isRecording, isConnected, sock
    if isRecording || !isConnected
        return
    isRecording := true
    try {
        SendMsg(sock, "START")
    } catch {
        isRecording := false
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

; Key up: stop recording, receive text, paste
~LCtrl & LWin up:: {
    global isRecording, isConnected, sock
    if !isRecording
        return
    isRecording := false

    try {
        SendMsg(sock, "STOP")
        response := RecvMsg(sock)

        if SubStr(response, 1, 7) = "RESULT:" {
            text := SubStr(response, 8)
            if text != "" {
                A_Clipboard := text
                Sleep(50)
                Send("^v")
            }
        }
    } catch {
        global isConnected := false
        SetTimer(TryReconnect, -RECONNECT_INTERVAL)
    }
}

; --- Startup ---
Connect()
```

- [ ] **Step 3: Manual test**

1. Start daemon: `python daemon.py`
2. Wait for "READY" log message
3. Run `hotkey.ahk` (double-click or `AutoHotkey64.exe hotkey.ahk`)
4. Open Notepad
5. Hold Ctrl+Win, speak a sentence in German, release
6. Text should appear in Notepad after 1-3 seconds

Expected: Spoken text appears in Notepad.

- [ ] **Step 4: Commit**

```bash
git add hotkey.ahk
git commit -m "feat: add AHK v2 hotkey script with TCP client and clipboard paste"
```

---

## Task 5: Startup Script

**Files:**
- Create: `start.bat`

- [ ] **Step 1: Write start.bat**

```batch
@echo off
REM Achilles Diktator — Start Script
REM Starts Python daemon and AHK hotkey script

cd /d "%~dp0"

REM Activate venv
call venv\Scripts\activate.bat

REM Start daemon in background
start /B "" python daemon.py

REM Wait for daemon to be ready (check if port 9876 is listening)
echo Waiting for daemon...
set /a ATTEMPTS=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 30 (
    echo ERROR: Daemon did not start within 30 seconds.
    exit /b 1
)
powershell -Command "Test-NetConnection -ComputerName localhost -Port 9876 -InformationLevel Quiet" | findstr /C:"True" >nul 2>&1
if errorlevel 1 goto wait_loop
echo Daemon ready.

REM Start AHK script (GUI process, no console window)
start "" "hotkey.ahk"

echo Achilles Diktator running.
```

- [ ] **Step 2: Manual test**

Run `start.bat` — both processes should start. Test Ctrl+Win in Notepad.

- [ ] **Step 3: Commit**

```bash
git add start.bat
git commit -m "feat: add startup script for daemon and AHK"
```

---

## Task 6: Windows Autostart

- [ ] **Step 1: Create shortcut in Startup folder**

Run (from PowerShell):
```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AchillesDiktator.lnk")
$Shortcut.TargetPath = "C:\Users\tomra\archilles_diktator\start.bat"
$Shortcut.WorkingDirectory = "C:\Users\tomra\archilles_diktator"
$Shortcut.WindowStyle = 7  # Minimized
$Shortcut.Save()
```

- [ ] **Step 2: Test by logging out and back in**

After login, Ctrl+Win should work immediately.

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "docs: autostart configured via Windows Startup shortcut"
```

---

## Task 7: End-to-End Integration Test

- [ ] **Step 1: Full workflow test**

1. Restart PC or log out/in
2. Open different applications: Notepad, Browser, IDE
3. In each app: hold Ctrl+Win, speak German, release
4. Verify text appears correctly in each app
5. Check `%APPDATA%/achilles-diktator/daemon.log` for clean operation

- [ ] **Step 2: Error scenario tests**

1. Kill daemon → try Ctrl+Win → should be silently ignored
2. Restart daemon → AHK should auto-reconnect within 5 seconds
3. Unplug microphone → try recording → should get no crash

- [ ] **Step 3: Final commit** (if any remaining changes)

```bash
git status
git add daemon.py hotkey.ahk start.bat
git commit -m "chore: project complete — Achilles Diktator v1"
```
