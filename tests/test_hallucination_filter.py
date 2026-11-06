import numpy as np
import pytest

from hallucination_filter import (
    filter_transcript,
    is_accidental_recording,
    longest_voiced_run,
    phrase_key,
)

RATE = 16000


def _tone(seconds: float, amplitude: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


# --- phrase_key ---

def test_phrase_key_drops_punctuation_case_and_years():
    assert phrase_key("Untertitel im Auftrag des ZDF, 2021.") == "untertitel im auftrag des zdf"


def test_phrase_key_splits_dotted_names():
    assert phrase_key("Untertitel der Amara.org-Community") == "untertitel der amara org community"


# --- longest_voiced_run ---

def test_silence_has_no_voiced_run():
    assert longest_voiced_run(_silence(2.0)) == 0.0


def test_empty_audio_has_no_voiced_run():
    assert longest_voiced_run(np.array([], dtype=np.float32)) == 0.0


def test_tone_run_is_measured():
    audio = np.concatenate([_silence(0.5), _tone(0.6), _silence(0.5)])
    assert longest_voiced_run(audio) == pytest.approx(0.6, abs=0.06)


def test_short_gap_is_bridged():
    audio = np.concatenate([_silence(0.5), _tone(0.3), _silence(0.05), _tone(0.3), _silence(0.5)])
    assert longest_voiced_run(audio) == pytest.approx(0.65, abs=0.06)


def test_quiet_speech_above_noise_floor_counts():
    # Below -40 dBFS, but far above a faint noise floor.
    rng = np.random.default_rng(0)
    noise = (0.0002 * rng.standard_normal(int(1.5 * RATE))).astype(np.float32)
    audio = noise.copy()
    start = int(0.5 * RATE)
    audio[start:start + int(0.4 * RATE)] += _tone(0.4, amplitude=0.005)
    assert longest_voiced_run(audio) == pytest.approx(0.4, abs=0.06)


# --- is_accidental_recording ---

def test_tap_is_accidental_even_with_sound():
    assert is_accidental_recording(_tone(0.2))


def test_short_click_without_speech_is_accidental():
    audio = np.concatenate([_silence(0.6), _tone(0.03), _silence(0.6)])
    assert is_accidental_recording(audio)


def test_short_word_is_kept():
    audio = np.concatenate([_silence(0.4), _tone(0.25), _silence(0.4)])
    assert not is_accidental_recording(audio)


def test_long_quiet_recording_is_kept():
    assert not is_accidental_recording(_silence(4.0))


# --- filter_transcript ---

def test_credit_is_dropped_regardless_of_speech():
    assert filter_transcript("Untertitel im Auftrag des ZDF, 2021", longest_run=2.0) == ""


def test_doubtful_phrase_dropped_on_hardly_any_speech():
    assert filter_transcript("Vielen Dank.", longest_run=0.2) == ""


def test_doubtful_phrase_kept_when_spoken():
    assert filter_transcript("Vielen Dank.", longest_run=0.8) == "Vielen Dank."


def test_trailing_credit_is_cut():
    text = "Wir sehen uns morgen. Untertitel im Auftrag des ZDF, 2021."
    assert filter_transcript(text, longest_run=2.0) == "Wir sehen uns morgen."


def test_trailing_two_sentence_credit_is_cut():
    text = "Das war es für heute. Vielen Dank fürs Zuschauen! Untertitel der Amara.org-Community"
    assert filter_transcript(text, longest_run=2.0) == "Das war es für heute."


def test_credit_words_inside_sentence_are_kept():
    text = "Das ZDF hat gestern berichtet."
    assert filter_transcript(text, longest_run=2.0) == text


def test_ordinary_text_passes_unchanged():
    assert filter_transcript("Hallo Welt, das ist ein Test.", longest_run=1.5) == "Hallo Welt, das ist ein Test."
