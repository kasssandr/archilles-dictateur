import re

# Spoken punctuation/formatting commands. Whisper transcribes them as ordinary
# words; we turn them into the actual symbols here, locally, with no extra model.
#
# There is one set per language, keyed by ISO code. The right set is chosen from
# the language Whisper detected for the recording, so a German sentence gets
# German commands and an English one gets English commands — no manual switch.
#
# Each entry is (spoken phrase, replacement, spacing class). The spacing class
# controls which surrounding whitespace is absorbed so the symbol sits correctly:
#   "collapse" — eats whitespace on both sides (line breaks, tight joiners)
#   "left"     — eats the space before it, keeps the one after (closing marks)
#   "open"     — eats the space after it, keeps the one before (opening marks)
#   "spaced"   — replaces the word only, leaving the surrounding spaces intact
#
# The sentence-ending period ("Punkt" / "period" / "punto" / "точка" / "point")
# is deliberately absent from every set: Whisper already sets it from prosody,
# and the bare word collides with normal speech too often.
_VOICE_COMMANDS: dict[str, list[tuple[str, str, str]]] = {
    "de": [
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
    ],
    "en": [
        ("new paragraph", "\n\n", "collapse"),
        ("new line", "\n", "collapse"),
        ("hyphen", "-", "collapse"),
        ("slash", "/", "collapse"),
        ("comma", ",", "left"),
        ("colon", ":", "left"),
        ("semicolon", ";", "left"),
        ("question mark", "?", "left"),
        ("exclamation mark", "!", "left"),
        ("exclamation point", "!", "left"),
        ("close parenthesis", ")", "left"),
        ("close paren", ")", "left"),
        ("close quote", "”", "left"),  # ”
        ("unquote", "”", "left"),  # ”
        ("open parenthesis", "(", "open"),
        ("open paren", "(", "open"),
        ("open quote", "“", "open"),  # “
        ("quote", "“", "open"),  # “  — pairs with "unquote"
        ("dash", "–", "spaced"),  # –
    ],
    # Spanish, Italian and Russian conventionally use guillemets « » for quotes.
    "es": [
        ("nuevo párrafo", "\n\n", "collapse"),
        ("nueva línea", "\n", "collapse"),
        ("guion", "-", "collapse"),
        ("guión", "-", "collapse"),  # pre-2010 spelling Whisper may still emit
        ("barra", "/", "collapse"),
        ("coma", ",", "left"),
        ("dos puntos", ":", "left"),
        ("punto y coma", ";", "left"),
        ("signo de interrogación", "?", "left"),
        ("signo de exclamación", "!", "left"),
        ("cerrar paréntesis", ")", "left"),
        ("cerrar comillas", "»", "left"),  # »
        ("abrir paréntesis", "(", "open"),
        ("abrir comillas", "«", "open"),  # «
        ("raya", "–", "spaced"),  # –
    ],
    "it": [
        ("nuovo paragrafo", "\n\n", "collapse"),
        ("nuova riga", "\n", "collapse"),
        ("trattino", "-", "collapse"),
        ("barra", "/", "collapse"),
        ("virgola", ",", "left"),
        ("due punti", ":", "left"),
        ("punto e virgola", ";", "left"),
        ("punto interrogativo", "?", "left"),
        ("punto esclamativo", "!", "left"),
        ("chiudi parentesi", ")", "left"),
        ("chiudi virgolette", "»", "left"),  # »
        ("apri parentesi", "(", "open"),
        ("apri virgolette", "«", "open"),  # «
        ("lineetta", "–", "spaced"),  # –
    ],
    "ru": [
        ("новый абзац", "\n\n", "collapse"),
        ("новая строка", "\n", "collapse"),
        ("дефис", "-", "collapse"),
        ("косая черта", "/", "collapse"),
        ("запятая", ",", "left"),
        ("двоеточие", ":", "left"),
        ("точка с запятой", ";", "left"),
        ("вопросительный знак", "?", "left"),
        ("восклицательный знак", "!", "left"),
        ("закрыть скобку", ")", "left"),
        ("закрыть кавычки", "»", "left"),  # »
        ("открыть скобку", "(", "open"),
        ("открыть кавычки", "«", "open"),  # «
        ("тире", "–", "spaced"),  # –
    ],
    # French uses guillemets too, but with an inner space: « comme ceci ». The
    # space is baked into the replacement (regular space, not NBSP, so it pastes
    # cleanly everywhere).
    "fr": [
        ("nouveau paragraphe", "\n\n", "collapse"),
        ("nouvelle ligne", "\n", "collapse"),
        ("trait d'union", "-", "collapse"),
        ("barre oblique", "/", "collapse"),
        ("virgule", ",", "left"),
        ("deux points", ":", "left"),
        ("point virgule", ";", "left"),
        ("point d'interrogation", "?", "left"),
        ("point d'exclamation", "!", "left"),
        ("fermer la parenthèse", ")", "left"),
        ("fermer les guillemets", " »", "left"),  # space before » (French style)
        ("ouvrir la parenthèse", "(", "open"),
        ("ouvrir les guillemets", "« ", "open"),  # space after « (French style)
        ("tiret", "–", "spaced"),  # –
    ],
}

# Language used when the detected code matches no set (mumbled fragments, an
# exotic misdetection). German is this tool's everyday case.
_DEFAULT_COMMAND_LANG = "de"

_SPACING_PATTERNS = {
    "collapse": r"\s*\b{p}\b\s*",
    "left": r"\s*\b{p}\b",
    # An opening mark hugs the following word. It also swallows one stray comma
    # that Whisper tends to insert at the pause after the spoken command, so
    # "Anführungszeichen auf, Wort" becomes „Wort and not „, Wort.
    "open": r"\b{p}\b\s*,?\s*",
    "spaced": r"\b{p}\b",
}


def _compile(commands: list[tuple[str, str, str]]) -> list[tuple[re.Pattern, str]]:
    # Longest phrases first so a multi-word command wins over any shorter phrase
    # nested inside it (e.g. "open parenthesis" before "open paren").
    result = []
    for phrase, repl, cls in sorted(commands, key=lambda c: len(c[0]), reverse=True):
        # Match either apostrophe Whisper might emit (straight ' or curly ’),
        # so French phrases like "point d'interrogation" are not missed.
        escaped = re.escape(phrase).replace("'", "['’]")
        result.append((re.compile(_SPACING_PATTERNS[cls].format(p=escaped), re.IGNORECASE), repl))
    return result


_COMPILED_VOICE_COMMANDS = {lang: _compile(cmds) for lang, cmds in _VOICE_COMMANDS.items()}


def apply_voice_commands(text: str, language: str = _DEFAULT_COMMAND_LANG) -> str:
    """Turn spoken punctuation/formatting commands into their symbols.

    `language` is an ISO code (e.g. "de", "en", "en-US"); only the leading two
    letters matter, and an unknown code falls back to the default set. Matching
    is case-insensitive and word-boundary sensitive, so "Absatz" inside
    "Absatzweise" is left alone. A replacement function is used so the literal
    symbols are inserted verbatim (re.sub would otherwise interpret backslashes
    in the replacement).
    """
    if not text:
        return text

    lang = (language or "")[:2].lower()
    compiled = _COMPILED_VOICE_COMMANDS.get(lang, _COMPILED_VOICE_COMMANDS[_DEFAULT_COMMAND_LANG])
    for pattern, repl in compiled:
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
