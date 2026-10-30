"""Check that every number in the generated answer exists in the retrieved data.

This is a safety net on top of the prompt: numbers the model writes that we
cannot trace back to a data point, threshold or timestamp are flagged in the
response so the UI can show them as unverified.
"""
import re

NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
ANY_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# Kannada and Devanagari digits -> ASCII so the check works in every language.
_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯०१२३४५६७८९", "01234567890123456789")


def allowed_numbers(values) -> set[str]:
    """Build the set of acceptable number strings from data values."""
    allowed = set()
    for v in values:
        if v is None or isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            f = float(v)
            for s in (f"{f:g}", f"{f:.1f}", f"{f:.0f}", str(round(f)), f"{abs(f):g}"):
                allowed.add(_norm(s))
        elif isinstance(v, str):
            # Loose match so dates/times like 2026-10-31T06:00 yield every part.
            for m in ANY_NUM_RE.findall(v.translate(_DIGITS)):
                allowed.add(_norm(m))
    return allowed


def unverified_numbers(text: str, allowed: set[str]) -> list[str]:
    found = NUM_RE.findall(text.translate(_DIGITS))
    out = []
    for n in found:
        key = _norm(n)
        # Small integers are list markers, counts or clock hours ("3 hours", "step 1").
        if key.isdigit() and int(key) <= 24:
            continue
        if key not in allowed and n not in out:
            out.append(n)
    return out


def _norm(s: str) -> str:
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.lstrip("0") or "0"
