import numpy as np
from unittest.mock import MagicMock, patch
from daemon import AudioRecorder, TranscriptionService, DaemonConfig, DaemonServer


def test_config_defaults():
    cfg = DaemonConfig()
    assert cfg.model_size == "medium"
    assert cfg.compute_type == "int8_float16"
    assert cfg.language == "auto"
    assert cfg.port == 9876
    assert cfg.sample_rate == 16000
    assert cfg.idle_unload_minutes == 5.0


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


@patch("daemon.WhisperModel")
def test_server_loads_model_on_demand_and_unloads_when_idle(MockModel):
    server = DaemonServer(DaemonConfig(idle_unload_minutes=5.0))
    assert server.transcriber is None, "model must not occupy VRAM before first use"

    server._ensure_model()
    assert server.transcriber is not None
    MockModel.assert_called_once()

    server._unload_model()
    assert server.transcriber is None

    # A second dictation reloads it rather than failing.
    server._ensure_model()
    assert server.transcriber is not None
    assert MockModel.call_count == 2


@patch("daemon.WhisperModel")
def test_unload_is_idempotent(MockModel):
    server = DaemonServer(DaemonConfig())
    server._unload_model()
    assert server.transcriber is None


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
        text, language = service.transcribe(audio)
        assert text == "Hallo Welt"
        assert language == "de"


def test_transcribe_auto_leaves_language_unset():
    with patch("daemon.WhisperModel") as MockModel:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([MagicMock(text="hi")], MagicMock())
        MockModel.return_value = mock_instance
        service = TranscriptionService(model_size="tiny", device="cpu", compute_type="int8")
        service.transcribe(np.zeros(16000, dtype=np.float32), language="auto")
        _, kwargs = mock_instance.transcribe.call_args
        assert "language" not in kwargs, "auto must let Whisper detect the language"


def test_transcribe_pins_explicit_language():
    with patch("daemon.WhisperModel") as MockModel:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([MagicMock(text="hallo")], MagicMock())
        MockModel.return_value = mock_instance
        service = TranscriptionService(model_size="tiny", device="cpu", compute_type="int8")
        service.transcribe(np.zeros(16000, dtype=np.float32), language="de")
        _, kwargs = mock_instance.transcribe.call_args
        assert kwargs["language"] == "de"


# --- Backend selection ---

def test_backend_defaults_to_local():
    server = DaemonServer(DaemonConfig())
    assert server.cloud is None


def test_openrouter_without_key_falls_back_to_local():
    server = DaemonServer(DaemonConfig(backend="openrouter", cloud_api_key=""))
    assert server.cloud is None


def test_api_key_is_not_in_config_repr():
    assert "secret" not in repr(DaemonConfig(cloud_api_key="secret"))


@patch("daemon.WhisperModel")
def test_openrouter_backend_skips_local_model(MockModel):
    server = DaemonServer(DaemonConfig(backend="openrouter", cloud_api_key="k"))
    server.cloud = MagicMock()
    server.cloud.transcribe.return_value = ("Hallo", "de")
    assert server._transcribe(np.zeros(16000, dtype=np.float32), "") == ("Hallo", "de")
    MockModel.assert_not_called()
    assert server.transcriber is None


@patch("daemon.WhisperModel")
def test_cloud_failure_falls_back_to_local_model(MockModel):
    from cloud_transcription import CloudTranscriptionError

    mock_instance = MagicMock()
    mock_instance.transcribe.return_value = ([MagicMock(text="lokal")], MagicMock(language="de"))
    MockModel.return_value = mock_instance
    server = DaemonServer(DaemonConfig(backend="openrouter", cloud_api_key="k"))
    server.cloud = MagicMock()
    server.cloud.transcribe.side_effect = CloudTranscriptionError("HTTP 429: quota")
    assert server._transcribe(np.zeros(16000, dtype=np.float32), "") == ("lokal", "de")
    MockModel.assert_called_once()


@patch("daemon.WhisperModel")
def test_permanent_cloud_error_disables_cloud_for_session(MockModel):
    from cloud_transcription import CloudTranscriptionError

    mock_instance = MagicMock()
    mock_instance.transcribe.return_value = ([MagicMock(text="lokal")], MagicMock(language="de"))
    MockModel.return_value = mock_instance
    server = DaemonServer(DaemonConfig(backend="openrouter", cloud_api_key="k"))
    cloud = MagicMock()
    cloud.name = "OpenRouter"
    cloud.transcribe.side_effect = CloudTranscriptionError("HTTP 402: no credit", status=402)
    server.cloud = cloud

    server._transcribe(np.zeros(16000, dtype=np.float32), "")
    assert server.cloud is None, "no credit will not fix itself; stop paying the round trip"
    server._transcribe(np.zeros(16000, dtype=np.float32), "")
    cloud.transcribe.assert_called_once()


@patch("daemon.WhisperModel")
def test_transient_cloud_error_keeps_cloud(MockModel):
    from cloud_transcription import CloudTranscriptionError

    mock_instance = MagicMock()
    mock_instance.transcribe.return_value = ([MagicMock(text="lokal")], MagicMock(language="de"))
    MockModel.return_value = mock_instance
    server = DaemonServer(DaemonConfig(backend="groq", cloud_api_key="k"))
    cloud = MagicMock()
    cloud.name = "Groq"
    cloud.transcribe.side_effect = CloudTranscriptionError("HTTP 429: slow down", status=429)
    server.cloud = cloud
    server._transcribe(np.zeros(16000, dtype=np.float32), "")
    assert server.cloud is cloud


def test_groq_backend_uses_default_model():
    server = DaemonServer(DaemonConfig(backend="groq", cloud_api_key="k"))
    assert server.cloud.name == "Groq"
    assert server.cloud.model == "whisper-large-v3"


def test_unknown_backend_stays_local():
    assert DaemonServer(DaemonConfig(backend="nonsense", cloud_api_key="k")).cloud is None


def test_main_reads_backend_specific_env(monkeypatch):
    import daemon

    monkeypatch.setenv("DICTATEUR_BACKEND", "Groq")
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("DICTATEUR_GROQ_MODEL", "whisper-large-v3-turbo")
    monkeypatch.setenv("OPENROUTER_API_KEY", "ork")
    captured = {}
    monkeypatch.setattr(daemon, "DaemonServer", lambda cfg: captured.setdefault("cfg", cfg) and MagicMock())
    monkeypatch.setattr(daemon.signal, "signal", lambda *a: None)
    daemon.main()
    cfg = captured["cfg"]
    assert (cfg.backend, cfg.cloud_api_key, cfg.cloud_model) == ("groq", "gk", "whisper-large-v3-turbo")
