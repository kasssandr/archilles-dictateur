"""Transcription through a cloud speech-to-text API.

Optional alternatives to the local faster-whisper model, with the same interface
as `daemon.TranscriptionService.transcribe`, so the rest of the pipeline (filter,
corrections, voice commands) stays the same. Uses only the standard library.

- OpenRouter: https://openrouter.ai/docs/guides/overview/multimodal/stt
- Groq:       https://console.groq.com/docs/speech-to-text
"""

import base64
import io
import json
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

# Some APIs sit behind Cloudflare, which rejects urllib's default User-Agent.
USER_AGENT = "Dictateur/1.0 (+https://github.com/kasssandr/archilles-dictateur)"

# verbose_json reports the language as a code or, like OpenAI's Whisper, as an
# English name. The voice-command sets are keyed by code.
_LANGUAGE_NAMES = {
    "german": "de", "english": "en", "french": "fr",
    "spanish": "es", "italian": "it", "russian": "ru",
}


class CloudTranscriptionError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def permanent(self) -> bool:
        """True for errors that will not go away by retrying: a wrong key (401),
        no credit (402), no access (403)."""
        return self.status in (401, 402, 403)


def encode_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """16-bit mono PCM WAV of float32 samples in [-1, 1]."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def normalize_language(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    return _LANGUAGE_NAMES.get(value, value if len(value) == 2 else "")


class _CloudTranscriber:
    name = "cloud"
    key_variable = "API key"

    def __init__(self, api_key: str, model: str, sample_rate: int = 16000, timeout: float = 30.0):
        if not api_key:
            raise CloudTranscriptionError(f"{self.key_variable} is not set")
        self.api_key = api_key
        self.model = model
        self.sample_rate = sample_rate
        self.timeout = timeout

    def _request(self, audio: np.ndarray, language: str, prompt: str, verbose: bool) -> urllib.request.Request:
        raise NotImplementedError

    def _headers(self, content_type: str) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
            "User-Agent": USER_AGENT,
        }

    def _post(self, request: urllib.request.Request) -> dict:
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def transcribe(self, audio: np.ndarray, language: str = "auto", initial_prompt: str = "") -> tuple[str, str]:
        """(text, language code). The code is empty when the provider did not report one."""
        language = "" if language == "auto" else (language or "")
        try:
            try:
                # verbose_json carries the detected language, which picks the
                # voice-command set. Some providers reject it with a 400.
                result = self._post(self._request(audio, language, initial_prompt, verbose=True))
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                result = self._post(self._request(audio, language, initial_prompt, verbose=False))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise CloudTranscriptionError(f"HTTP {e.code}: {detail}", status=e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise CloudTranscriptionError(str(e)) from e

        text = (result.get("text") or "").strip()
        detected = normalize_language(result.get("language")) or language
        return text, detected


class OpenRouterTranscriber(_CloudTranscriber):
    """OpenRouter's JSON endpoint: base64 audio, routed to a provider of the model."""

    name = "OpenRouter"
    key_variable = "OPENROUTER_API_KEY"
    API_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
    DEFAULT_MODEL = "openai/whisper-large-v3"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(api_key, model, **kwargs)

    def _request(self, audio, language, prompt, verbose):
        body = {
            "model": self.model,
            "input_audio": {
                "data": base64.b64encode(encode_wav(audio, self.sample_rate)).decode("ascii"),
                "format": "wav",
            },
            "temperature": 0,
            # Route only to providers that do not keep the audio for training.
            "provider": {"data_collection": "deny"},
        }
        if verbose:
            body["response_format"] = "verbose_json"
        if language:
            body["language"] = language
        if prompt:
            # There is no top-level prompt field; Whisper providers take it as a
            # provider-specific option. Providers it does not apply to ignore it.
            body["provider"]["options"] = {
                "groq": {"prompt": prompt},
                "openai": {"prompt": prompt},
            }
        return urllib.request.Request(
            self.API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers("application/json") | {"X-Title": "Dictateur"},
            method="POST",
        )


class GroqTranscriber(_CloudTranscriber):
    """Groq's OpenAI-compatible endpoint: multipart upload of the WAV file."""

    name = "Groq"
    key_variable = "GROQ_API_KEY"
    API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    DEFAULT_MODEL = "whisper-large-v3"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(api_key, model, **kwargs)

    def _request(self, audio, language, prompt, verbose):
        fields = {"model": self.model, "temperature": "0"}
        if verbose:
            fields["response_format"] = "verbose_json"
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        boundary = uuid.uuid4().hex
        body = _multipart(fields, ("file", "audio.wav", "audio/wav", encode_wav(audio, self.sample_rate)), boundary)
        return urllib.request.Request(
            self.API_URL,
            data=body,
            headers=self._headers(f"multipart/form-data; boundary={boundary}"),
            method="POST",
        )


def _multipart(fields: dict[str, str], file: tuple[str, str, str, bytes], boundary: str) -> bytes:
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        out.write(str(value).encode("utf-8") + b"\r\n")
    field, filename, content_type, data = file
    out.write(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
    )
    out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue()


BACKENDS: dict[str, type[_CloudTranscriber]] = {
    "openrouter": OpenRouterTranscriber,
    "groq": GroqTranscriber,
}
