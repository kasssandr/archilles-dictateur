import re

# Spoken punctuation/formatting commands. Whisper transcribes them as ordinary
# words; we turn them into the actual symbols here, locally, with no extra model.
#
# Each entry is (spoken phrase, replacement, spacing class). The spacing class
# controls which surrounding whitespace is absorbed so the symbol sits correctly:
#   "collapse" — eats whitespace on both sides (line breaks, tight joiners)
#   "left"     — eats the space before it, keeps the one after (closing marks)
#   "open"     — eats the space after it, keeps the one before (opening marks)
#   "spaced"   — replaces the word only, leaving the surrounding spaces intact
#
# "Punkt" is deliberately absent: Whisper already sets sentence periods from
# prosody, and the bare word collides with normal speech too often.
_VOICE_COMMANDS: list[tuple[str, str, str]] = [
    # Line breaks and tight joiners — swallow the spaces around them.
    ("Absatz", "\n\n", "collapse"),
    ("neue Zeile", "\n", "collapse"),
    ("Bindestrich", "-", "collapse"),
    ("Schrägstrich", "/", "collapse"),
    # Marks that hug the preceding word.
    ("Komma", ",", "left"),
    ("Doppelpunkt", ":", "left"),
    ("Semikolon", ";", "left"),
    ("Fragezeichen", "?", "left"),
    ("Ausrufezeichen", "!", "left"),
    ("Klammer zu", ")", "left"),
    ("Anführungszeichen zu", "“", "left"),  # “
    # Marks that hug the following word.
    ("Klammer auf", "(", "open"),
    ("Anführungszeichen auf", "„", "open"),  # „
    # A dash sits between two words with a space on each side (German style).
    ("Gedankenstrich", "–", "spaced"),  # –
]

_SPACING_PATTERNS = {
    "collapse": r"\s*\b{p}\b\s*",
    "left": r"\s*\b{p}\b",
    "open": r"\b{p}\b\s*",
    "spaced": r"\b{p}\b",
}

# Compile once. Longest phrases first so a multi-word command wins over any
# shorter phrase nested inside it.
_COMPILED_VOICE_COMMANDS = [
    (re.compile(_SPACING_PATTERNS[cls].format(p=re.escape(phrase)), re.IGNORECASE), repl)
    for phrase, repl, cls in sorted(_VOICE_COMMANDS, key=lambda c: len(c[0]), reverse=True)
]


def apply_voice_commands(text: str) -> str:
    """Turn spoken punctuation/formatting commands into their symbols.

    Matching is case-insensitive and word-boundary sensitive, so "Absatz"
    inside "Absatzweise" is left alone. A replacement function is used so the
    literal symbols are inserted verbatim (re.sub would otherwise interpret
    backslashes in the replacement).
    """
    if not text:
        return text

    for pattern, repl in _COMPILED_VOICE_COMMANDS:
        text = pattern.sub(lambda _m, r=repl: r, text)
    return text


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Replace words in text according to corrections, word-boundary sensitive.

    Longer keys are applied first so that, given overlapping keys, the longest
    match wins. Matching is case-sensitive. Keys are regex-escaped so they are
    treated as literal strings.
    """
    if not text or not corrections:
        return text

    sorted_keys = sorted(corrections.keys(), key=len, reverse=True)
    for wrong in sorted_keys:
        right = corrections[wrong]
        pattern = r"\b" + re.escape(wrong) + r"\b"
        text = re.sub(pattern, right, text)
    return text
