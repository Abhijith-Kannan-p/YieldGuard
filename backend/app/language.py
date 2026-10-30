"""Detect the user's language from the script of the question."""
from . import config

KANNADA = (0x0C80, 0x0CFF)
DEVANAGARI = (0x0900, 0x097F)


def detect(text: str) -> str:
    """Return 'kn', 'hi' or 'en' based on which script dominates the letters."""
    kn = hi = latin = 0
    for ch in text:
        cp = ord(ch)
        if KANNADA[0] <= cp <= KANNADA[1]:
            kn += 1
        elif DEVANAGARI[0] <= cp <= DEVANAGARI[1]:
            hi += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    if kn == hi == 0:
        return "en"
    return "kn" if kn >= hi else "hi"


def resolve(requested: str | None, question: str) -> str:
    """An explicit supported choice wins; 'auto'/empty/unknown falls back to detection."""
    if requested and requested in config.SUPPORTED_LANGUAGES:
        return requested
    return detect(question)
