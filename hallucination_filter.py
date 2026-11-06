"""Drops text Whisper invents instead of hearing it.

Whisper was trained on subtitled video, so on silence, a cough or a click it likes
to produce subtitle credits ("Untertitel im Auftrag des ZDF, 2021") or sign-offs
("Vielen Dank fürs Zuschauen", "Thank you."). `vad_filter` removes most silence
before decoding, but not all of it, and it cannot help when the credit is appended
to real speech.

Three checks, all local and cheap:

- A recording that is very short, or short and without a run of speech long
  enough to be a word, is dropped before the model runs at all.
- A transcript that is a credit, or a doubtful phrase ("Danke.", "Okay.") on a
  recording with hardly any speech, is dropped.
- Credits at the end of a real transcript are cut off.

Speech is measured with a plain energy meter, not with Whisper's no-speech
probability, so the check also works before the model is loaded.

The phrase lists, thresholds and the meter follow the HallucinationFilter of
Blitztext (https://github.com/cmagnussen/blitztext-app, MIT License).
"""

import numpy as np

# Credits and sign-offs that are never meant as dictation. Normalized (see
# `phrase_key`), without years: "ZDF, 2021" and "ZDF 2017" both match "zdf".
CREDITS: frozenset[str] = frozenset({
    "untertitel im auftrag des zdf",
    "untertitel im auftrag des zdf für funk",
    "untertitelung im auftrag des zdf",
    "untertitelung des zdf",
    "untertitel des zdf",
    "untertitel der amara org community",
    "untertitel von der amara org community",
    "untertitel von amara org",
    "untertitel von stephanie geiges",
    "copyright wdr",
    "copyright swr",
    "vielen dank fürs zuschauen",
    "vielen dank für s zuschauen",
    "danke fürs zuschauen",
    "danke für s zuschauen",
    "abonniert den kanal",
    "bitte abonnieren",
    "abonniere meinen kanal",
    "subtitles by the amara org community",
    "subtitles by amara org",
    "thanks for watching",
    "thank you for watching",
    "thank you so much for watching",
    "please subscribe",
    "like and subscribe",
    "please like and subscribe",
})

# Short phrases people do say, so they only count as invented when the recording
# holds hardly any speech: Whisper writes them on a cough or a click.
DOUBTFUL_PHRASES: frozenset[str] = frozenset({
    "vielen dank", "danke", "danke schön", "dankeschön", "tschüss", "tschüs",
    "bis zum nächsten mal", "bis bald", "bis dann", "das war s", "ende",
    "thank you", "thanks", "thank you very much", "you", "bye", "bye bye",
    "okay", "ok", "ja", "hmm", "hm", "mhm",
    "musik", "music", "applaus", "applause", "lachen",
    "swr", "wdr", "zdf", "ard",
})

# Below this, a recording is a slip of the finger, whatever it holds.
MIN_RECORDING_SECONDS = 0.3
# Recordings shorter than this are checked for speech before the model runs. A
# longer one may just be quiet (a whisper, a voice across the room) and is kept.
ACCIDENTAL_RECORDING_SECONDS = 3.0
# Shorter than this, the longest run of speech is no word: a quick "Ja." is about
# 0.2 s, a click or a mic bump one or two 30 ms frames.
MIN_VOICED_SECONDS = 0.15
# Below this longest run, a doubtful phrase counts as invented.
DOUBTFUL_BELOW_SECONDS = 0.3

_FRAME_SECONDS = 0.03
_LOUD_LEVEL = 0.01          # about -40 dBFS
_ABOVE_NOISE_FLOOR = 5.62   # 15 dB
_QUIETEST_LEVEL = 0.001     # -60 dBFS: digital silence and dither are no speech
_MAX_GAP_FRAMES = 2         # bridge 60 ms so a plosive does not split a word


def longest_voiced_run(audio: np.ndarray, sample_rate: int = 16000) -> float:
    """Seconds of the longest run of speech in `audio`.

    The audio is cut into 30 ms frames. A frame counts as speech above about
    -40 dBFS, or, at a low input volume, 15 dB above the recording's noise floor
    (its quietest tenth of frames), but never below -60 dBFS. Gaps of up to two
    frames are bridged.
    """
    frame_len = max(1, int(sample_rate * _FRAME_SECONDS))
    n_frames = len(audio) // frame_len
    if n_frames == 0:
        return 0.0
    frames = np.asarray(audio[: n_frames * frame_len], dtype=np.float32).reshape(n_frames, frame_len)
    levels = np.sqrt(np.mean(frames * frames, axis=1))

    noise_floor = float(np.sort(levels)[n_frames // 10])
    threshold = min(_LOUD_LEVEL, max(noise_floor * _ABOVE_NOISE_FLOOR, _QUIETEST_LEVEL))

    longest = 0
    run_start = None
    last_voiced = 0
    for index, level in enumerate(levels):
        if level > threshold:
            if run_start is None:
                run_start = index
            last_voiced = index
        elif run_start is not None and index - last_voiced > _MAX_GAP_FRAMES:
            longest = max(longest, last_voiced - run_start + 1)
            run_start = None
    if run_start is not None:
        longest = max(longest, last_voiced - run_start + 1)
    return longest * frame_len / sample_rate


def is_accidental_recording(audio: np.ndarray, sample_rate: int = 16000) -> bool:
    """True for a recording not worth sending to the model: too short to be a
    dictation, or short and without a run of speech long enough to be a word."""
    duration = len(audio) / sample_rate
    if duration < MIN_RECORDING_SECONDS:
        return True
    if duration >= ACCIDENTAL_RECORDING_SECONDS:
        return False
    return longest_voiced_run(audio, sample_rate) < MIN_VOICED_SECONDS


def _normalized(text: str) -> str:
    """Lowercased letters and digits; every other run of characters becomes one space."""
    out: list[str] = []
    pending_space = False
    for ch in text.lower():
        if ch.isalnum():
            if pending_space and out:
                out.append(" ")
            out.append(ch)
            pending_space = False
        else:
            pending_space = True
    return "".join(out)


def phrase_key(text: str) -> str:
    """Normalized text without pure numbers, for matching against the phrase lists."""
    return " ".join(w for w in _normalized(text).split(" ") if w and not w.isdigit())


def _sentence_starts(text: str) -> list[int]:
    """0 and every index after a line break or after ".!?…" plus whitespace.
    "Amara.org" stays one sentence."""
    starts = [0]
    for i, ch in enumerate(text[:-1]):
        nxt = text[i + 1]
        if ch == "\n" or (ch in ".!?…" and nxt.isspace()):
            starts.append(i + 1)
    return starts


def _remove_trailing_credits(text: str) -> str:
    """Cuts credits off the end: "... bis morgen. Untertitel im Auftrag des ZDF, 2021."."""
    result = text.strip()
    while result:
        for start in reversed(_sentence_starts(result)[-3:]):
            if phrase_key(result[start:]) in CREDITS:
                result = result[:start].strip()
                break
        else:
            break
    return result


def filter_transcript(text: str, longest_run: float) -> str:
    """What is left of Whisper's `text`: empty when it is a credit, or a doubtful
    phrase on a recording whose longest run of speech is under 0.3 s; otherwise
    the text without trailing credits."""
    key = phrase_key(text)
    if not key:
        return text.strip()
    if key in CREDITS:
        return ""
    if longest_run < DOUBTFUL_BELOW_SECONDS and key in DOUBTFUL_PHRASES:
        return ""
    return _remove_trailing_credits(text)
