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
