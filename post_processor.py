import re


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
