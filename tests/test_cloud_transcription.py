import base64
import io
import json
import urllib.error
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cloud_transcription import (
    BACKENDS,
    CloudTranscriptionError,
    GeminiTranscriber,
    GroqTranscriber,
    OpenAITranscriber,
    OpenRouterTranscriber,
    encode_wav,
    normalize_language,
)

AUDIO = np.zeros(16000, dtype=np.float32)


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


def _sent_body(mock_urlopen, call=0) -> dict:
    request = mock_urlopen.call_args_list[call].args[0]
    return json.loads(request.data.decode("utf-8"))


def test_encode_wav_is_16k_mono_pcm16():
    data = encode_wav(np.array([0.0, 0.5, -1.0, 2.0], dtype=np.float32), 16000)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 4)
        samples = np.frombuffer(w.readframes(4), dtype="<i2")
    assert samples.tolist() == [0, 16383, -32767, 32767]  # 2.0 is clipped


@pytest.mark.parametrize("value, expected", [
    ("de", "de"), ("German", "de"), ("english", "en"), ("klingon", ""), (None, ""),
])
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


def test_missing_key_raises():
    with pytest.raises(CloudTranscriptionError):
        OpenRouterTranscriber(api_key="")


@patch("cloud_transcription.urllib.request.urlopen")
def test_request_carries_audio_model_and_privacy_routing(mock_urlopen):
    mock_urlopen.return_value = _response({"text": " Hallo Welt ", "language": "german"})
    t = OpenRouterTranscriber(api_key="k", model="openai/whisper-large-v3")
    assert t.transcribe(AUDIO) == ("Hallo Welt", "de")

    request = mock_urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer k"
    body = _sent_body(mock_urlopen)
    assert body["model"] == "openai/whisper-large-v3"
    assert body["input_audio"]["format"] == "wav"
    assert base64.b64decode(body["input_audio"]["data"])[:4] == b"RIFF"
    assert body["provider"]["data_collection"] == "deny"
    assert body["response_format"] == "verbose_json"
    assert "language" not in body, "auto must let the provider detect the language"


@patch("cloud_transcription.urllib.request.urlopen")
def test_pinned_language_and_prompt_are_sent(mock_urlopen):
    mock_urlopen.return_value = _response({"text": "x"})
    t = OpenRouterTranscriber(api_key="k")
    _, lang = t.transcribe(AUDIO, language="de", initial_prompt="Kubernetes")
    body = _sent_body(mock_urlopen)
    assert body["language"] == "de"
    assert body["provider"]["options"]["groq"]["prompt"] == "Kubernetes"
    assert lang == "de", "a pinned language stands in when none is reported"


@patch("cloud_transcription.urllib.request.urlopen")
def test_400_retries_without_verbose_json(mock_urlopen):
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"verbose_json unsupported"))
    mock_urlopen.side_effect = [err, _response({"text": "ok"})]
    assert OpenRouterTranscriber(api_key="k").transcribe(AUDIO) == ("ok", "")
    assert "response_format" not in _sent_body(mock_urlopen, call=1)


@patch("cloud_transcription.urllib.request.urlopen")
def test_http_error_becomes_cloud_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError("u", 429, "quota", {}, io.BytesIO(b"rate limited"))
    with pytest.raises(CloudTranscriptionError, match="429"):
        OpenRouterTranscriber(api_key="k").transcribe(AUDIO)


@patch("cloud_transcription.urllib.request.urlopen")
def test_network_error_becomes_cloud_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("offline")
    with pytest.raises(CloudTranscriptionError):
        OpenRouterTranscriber(api_key="k").transcribe(AUDIO)


@pytest.mark.parametrize("status, permanent", [(401, True), (402, True), (403, True), (404, True),
                                                (429, False), (500, False), (None, False)])
def test_permanent_errors(status, permanent):
    assert CloudTranscriptionError("x", status=status).permanent is permanent


@patch("cloud_transcription.urllib.request.urlopen")
def test_http_error_carries_status(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.HTTPError("u", 402, "pay", {}, io.BytesIO(b"no credit"))
    with pytest.raises(CloudTranscriptionError) as info:
        OpenRouterTranscriber(api_key="k").transcribe(AUDIO)
    assert info.value.status == 402 and info.value.permanent


@patch("cloud_transcription.urllib.request.urlopen")
def test_groq_sends_multipart_with_wav_and_fields(mock_urlopen):
    mock_urlopen.return_value = _response({"text": " Hallo ", "language": "German"})
    t = GroqTranscriber(api_key="gk")
    assert t.transcribe(AUDIO, language="de", initial_prompt="Kubernetes") == ("Hallo", "de")

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.get_header("Authorization") == "Bearer gk"
    assert request.get_header("User-agent").startswith("Dictateur/")
    content_type = request.get_header("Content-type")
    assert content_type.startswith("multipart/form-data; boundary=")
    body = request.data
    for part in (b'name="model"\r\n\r\nwhisper-large-v3\r\n',
                 b'name="language"\r\n\r\nde\r\n',
                 b'name="prompt"\r\n\r\nKubernetes\r\n',
                 b'name="response_format"\r\n\r\nverbose_json\r\n',
                 b'filename="audio.wav"'):
        assert part in body
    boundary = content_type.split("boundary=")[1].encode()
    assert body.rstrip().endswith(b"--" + boundary + b"--")


@patch("cloud_transcription.urllib.request.urlopen")
def test_groq_auto_language_is_not_sent(mock_urlopen):
    mock_urlopen.return_value = _response({"text": "hi", "language": "english"})
    assert GroqTranscriber(api_key="gk").transcribe(AUDIO) == ("hi", "en")
    assert b'name="language"' not in mock_urlopen.call_args.args[0].data


def test_groq_missing_key_names_variable():
    with pytest.raises(CloudTranscriptionError, match="GROQ_API_KEY"):
        GroqTranscriber(api_key="")


@pytest.mark.parametrize("backend, key_variable", [
    ("groq", "GROQ_API_KEY"), ("openai", "OPENAI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"), ("gemini", "GEMINI_API_KEY"),
])
def test_backend_key_variable_matches_daemon_convention(backend, key_variable):
    # daemon.main() reads f"{backend.upper()}_API_KEY"
    assert BACKENDS[backend].key_variable == key_variable == f"{backend.upper()}_API_KEY"


# --- OpenAI ---

@patch("cloud_transcription.urllib.request.urlopen")
def test_openai_uses_its_endpoint_and_whisper(mock_urlopen):
    mock_urlopen.return_value = _response({"text": "Hello", "language": "english"})
    assert OpenAITranscriber(api_key="ok").transcribe(AUDIO) == ("Hello", "en")
    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/audio/transcriptions"
    assert b"whisper-1" in request.data


@patch("cloud_transcription.urllib.request.urlopen")
def test_openai_reads_languages_list(mock_urlopen):
    # gpt-transcribe rejects verbose_json and reports "languages" instead.
    err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"verbose_json not supported"))
    mock_urlopen.side_effect = [err, _response({"text": "Hallo", "languages": [{"code": "de"}]})]
    t = OpenAITranscriber(api_key="ok", model="gpt-transcribe")
    assert t.transcribe(AUDIO) == ("Hallo", "de")


# --- Gemini ---

def _gemini_response(payload: dict) -> MagicMock:
    return _response({"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


@patch("cloud_transcription.urllib.request.urlopen")
def test_gemini_request_shape(mock_urlopen):
    mock_urlopen.return_value = _gemini_response({"text": " Hallo Welt ", "language": "de"})
    t = GeminiTranscriber(api_key="gk")
    assert t.transcribe(AUDIO, initial_prompt="Kubernetes") == ("Hallo Welt", "de")

    request = mock_urlopen.call_args.args[0]
    assert request.full_url.endswith("/models/gemini-3.6-flash:generateContent")
    assert request.get_header("X-goog-api-key") == "gk"
    assert request.get_header("Authorization") is None
    body = json.loads(request.data)
    parts = body["contents"][0]["parts"]
    assert "verbatim" in parts[0]["text"] and "never answer" in parts[0]["text"]
    assert "Kubernetes" in parts[0]["text"]
    assert parts[1]["inline_data"]["mime_type"] == "audio/wav"
    assert base64.b64decode(parts[1]["inline_data"]["data"])[:4] == b"RIFF"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0


@patch("cloud_transcription.urllib.request.urlopen")
def test_gemini_pinned_language_goes_into_instruction(mock_urlopen):
    mock_urlopen.return_value = _gemini_response({"text": "x", "language": ""})
    _, lang = GeminiTranscriber(api_key="gk").transcribe(AUDIO, language="fr")
    assert "'fr'" in json.loads(mock_urlopen.call_args.args[0].data)["contents"][0]["parts"][0]["text"]
    assert lang == "fr"


@patch("cloud_transcription.urllib.request.urlopen")
def test_gemini_invalid_key_is_permanent_and_not_retried(mock_urlopen):
    detail = b'{"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}'
    mock_urlopen.side_effect = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(detail))
    with pytest.raises(CloudTranscriptionError) as info:
        GeminiTranscriber(api_key="bad").transcribe(AUDIO)
    assert info.value.permanent
    mock_urlopen.assert_called_once()


@patch("cloud_transcription.urllib.request.urlopen")
def test_gemini_blocked_response_raises(mock_urlopen):
    mock_urlopen.return_value = _response({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(CloudTranscriptionError, match="SAFETY"):
        GeminiTranscriber(api_key="gk").transcribe(AUDIO)
