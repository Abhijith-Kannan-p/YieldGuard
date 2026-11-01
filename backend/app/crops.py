"""Crop named in the farmer's question, and whether an Agmarknet commodity name is that crop.

Words come from config.CROP_ALIASES (English, Hindi, Kannada). The longest word wins, so a word
inside a longer one (ಜೋಳ inside ಮೆಕ್ಕೆಜೋಳ) does not count. English words must be whole words;
Hindi and Kannada words may carry endings (ಜೋಳದ, ಜೋಳಕ್ಕೆ), so they match inside words.
"""
import re

from . import config


def _pattern(word: str) -> re.Pattern:
    if word.isascii():
        return re.compile(rf"(?<![a-z]){re.escape(word)}(?![a-z])")
    return re.compile(re.escape(word))


_WORDS = sorted(((w.lower(), crop) for crop, a in config.CROP_ALIASES.items() for w in a["words"]),
                key=lambda x: -len(x[0]))
_PATTERNS = [(_pattern(w), w, crop) for w, crop in _WORDS]


def find_crop(question: str) -> dict | None:
    """The first crop named in the question: {"crop", "word"} or None."""
    text = " ".join((question or "").lower().split())
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str, str]] = []
    for pat, word, crop in _PATTERNS:
        for m in pat.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue  # inside a longer word already matched
            taken.append((m.start(), m.end()))
            found.append((m.start(), crop, word))
    if not found:
        return None
    _, crop, word = min(found)
    return {"crop": crop, "word": word}


def matches(crop: str, commodity: str) -> bool:
    """Whether an Agmarknet commodity name (e.g. "Jowar(Sorghum)") is this crop."""
    a = config.CROP_ALIASES[crop]
    name = (commodity or "").lower()
    return any(f in name for f in a["commodity"]) and not any(x in name for x in a.get("exclude", []))
