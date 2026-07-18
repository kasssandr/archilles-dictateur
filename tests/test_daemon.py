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
        result = service.transcribe(audio)
        assert result == "Hallo Welt"


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
