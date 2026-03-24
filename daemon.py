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
    log_dir = Path.home() / "AppData" / "Roaming" / "archilles-diktator"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    logger = logging.getLogger("archilles")
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
