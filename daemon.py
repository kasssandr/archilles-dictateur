import gc
import logging
import os
import signal
import site
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

from post_processor import apply_corrections, apply_voice_commands
from vocabulary import VocabularyStore

# NVIDIA DLL-Verzeichnisse registrieren (Windows: cublas64_12.dll etc.)
if sys.platform == "win32":
    for _sp in site.getsitepackages():
        _nvidia = os.path.join(_sp, "nvidia")
        if os.path.isdir(_nvidia):
            for _pkg in os.listdir(_nvidia):
                _bin = os.path.join(_nvidia, _pkg, "bin")
                if os.path.isdir(_bin):
                    try:
                        os.add_dll_directory(_bin)
                    except Exception:
                        pass
                    os.environ["PATH"] = _bin + os.pathsep + os.environ["PATH"]

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from protocol import send_message, recv_message

# --- Configuration ---

@dataclass
class DaemonConfig:
    model_size: str = "medium"
    # "auto" lets Whisper detect the spoken language per recording, so English
    # stays English instead of being forced into German. Pin to a code like
    # "de" to force one language (steadier for very short utterances).
    language: str = "auto"
    port: int = 9876
    host: str = "localhost"
    sample_rate: int = 16000
    device: str = "cuda"
    compute_type: str = "int8_float16"
    vocabulary_path: Path | None = None
    # Release the model's VRAM after this much idle time, so other GPU
    # workloads can use it. 0 keeps the model resident for the whole session.
    idle_unload_minutes: float = 5.0


# --- Logging ---

def setup_logging() -> logging.Logger:
    log_dir = Path.home() / "AppData" / "Roaming" / "archilles-dictateur"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    logger = logging.getLogger("archilles")
    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
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
        if self.is_recording:
            return
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
        if not self.is_recording:
            return np.array([], dtype=np.float32)
        
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        
        self.is_recording = False
        if not self._buffer:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._buffer)


# --- Transcription ---

class TranscriptionService:
    def __init__(self, model_size: str = "small", device: str = "cuda", compute_type: str = "float16"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, language: str = "auto", initial_prompt: str = "") -> tuple[str, str]:
        kwargs = {}
        # "auto" (or empty/None) leaves language unset so Whisper detects it
        # per recording. Any other value pins the decoder to that language.
        if language and language != "auto":
            kwargs["language"] = language
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        # vad_filter strips silence; condition_on_previous_text=False prevents
        # the repetition loops Whisper falls into on pauses in the audio.
        segments, info = self.model.transcribe(
            audio,
            vad_filter=True,
            condition_on_previous_text=False,
            **kwargs,
        )
        text = "".join(seg.text for seg in segments).strip()
        # info.language is the detected code in auto mode, or the pinned one.
        # It drives which voice-command set the daemon applies.
        return text, info.language


# --- Socket Server ---

class DaemonServer:
    def __init__(self, config: DaemonConfig):
        self.config = config
        self.logger = setup_logging()
        self.running = False
        self.recorder = AudioRecorder(sample_rate=config.sample_rate)
        self.vocabulary = VocabularyStore(config.vocabulary_path, self.logger)
        self.transcriber = None
        self._server_socket = None
        self._current_conn = None
        # Guards transcriber against being unloaded mid-transcription.
        # Reentrant because transcription takes the lock and then calls _ensure_model.
        self._model_lock = threading.RLock()
        self._last_used = time.monotonic()

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

    def _ensure_model(self):
        with self._model_lock:
            if self.transcriber is None:
                self._load_model()
            self._last_used = time.monotonic()

    def _unload_model(self):
        with self._model_lock:
            if self.transcriber is None:
                return
            self.transcriber = None
            # CTranslate2 frees the GPU allocation when the last reference to the
            # model drops, but only once the object is actually collected.
            gc.collect()
            self.logger.info("Whisper model unloaded after %.0f min idle", self.config.idle_unload_minutes)

    def _idle_watcher(self):
        timeout = self.config.idle_unload_minutes * 60
        while self.running:
            time.sleep(5)
            if self.recorder.is_recording:
                continue
            with self._model_lock:
                idle_for = time.monotonic() - self._last_used
                if self.transcriber is not None and idle_for > timeout:
                    self._unload_model()

    def _handle_client(self, conn: socket.socket):
        self.logger.info("Client connected")
        self._current_conn = conn
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
                        # Reload in the background if the idle watcher unloaded the
                        # model: it becomes ready while the user is still speaking,
                        # so the load never shows up as latency.
                        threading.Thread(target=self._ensure_model, daemon=True).start()
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
                        prompt = self.vocabulary.get_prompt()
                        with self._model_lock:
                            self._ensure_model()
                            text, detected_language = self.transcriber.transcribe(
                                audio,
                                language=self.config.language,
                                initial_prompt=prompt,
                            )
                            self._last_used = time.monotonic()
                        text = apply_corrections(text, self.vocabulary.get_corrections())
                        text = apply_voice_commands(text, detected_language)
                        self.logger.info("Transcribed: %s", text)
                        send_message(stream, f"RESULT:{text}")
                    except Exception as e:
                        self.logger.error("Transcription error: %s", e)
                        send_message(stream, f"ERROR:TRANSCRIPTION:{e}")
        except (ConnectionResetError, BrokenPipeError):
            self.logger.info("Client disconnected")
        except OSError:
            # Occurs when socket is closed during shutdown
            pass
        finally:
            stream.close()
            conn.close()
            self._current_conn = None

    def start(self):
        self.running = True

        if self.config.idle_unload_minutes > 0:
            # Stay out of VRAM until the first dictation actually needs the model.
            threading.Thread(target=self._idle_watcher, daemon=True).start()
            self.logger.info("Idle unloading active: %.1f min", self.config.idle_unload_minutes)
        else:
            self._ensure_model()

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
        self.vocabulary.stop()
        if self._current_conn:
            try:
                self._current_conn.shutdown(socket.SHUT_RDWR)
                self._current_conn.close()
            except OSError:
                pass
        if self._server_socket:
            self._server_socket.close()


def main():
    vocab_env = os.environ.get("DICTATEUR_VOCABULARY_PATH")
    vocabulary_path = Path(vocab_env) if vocab_env else None
    config = DaemonConfig(vocabulary_path=vocabulary_path)
    if model_size := os.environ.get("DICTATEUR_MODEL_SIZE"):
        config.model_size = model_size
    if compute_type := os.environ.get("DICTATEUR_COMPUTE_TYPE"):
        config.compute_type = compute_type
    if language := os.environ.get("DICTATEUR_LANGUAGE"):
        config.language = language
    if idle := os.environ.get("DICTATEUR_IDLE_UNLOAD_MINUTES"):
        try:
            config.idle_unload_minutes = float(idle)
        except ValueError:
            pass
    server = DaemonServer(config)

    def signal_handler(sig, frame):
        server.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server.start()


if __name__ == "__main__":
    main()
