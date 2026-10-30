from app import grounding, language


def test_detect_scripts():
    assert language.detect("Can I spray pesticide on my cotton tomorrow?") == "en"
    assert language.detect("क्या मैं कल कपास पर छिड़काव कर सकता हूँ?") == "hi"
    assert language.detect("ನಾಳೆ ಹತ್ತಿ ಬೆಳೆಗೆ ಔಷಧಿ ಸಿಂಪಡಿಸಬಹುದೇ?") == "kn"
    assert language.detect("ನಾಳೆ spray ಮಾಡಬಹುದಾ?") == "kn"


def test_resolve_prefers_explicit_choice():
    assert language.resolve("hi", "Can I spray?") == "hi"
    assert language.resolve("auto", "ನಾಳೆ?") == "kn"
    assert language.resolve("fr", "hello") == "en"


def test_numbers_traced_to_data():
    allowed = grounding.allowed_numbers([8.7, 41.4, "2026-10-31T06:00", 60.0])
    text = "Wind will be 8.7 km/h at 06:00 on 2026-10-31. Sand is 41.4%. Rain is 33 mm."
    assert grounding.unverified_numbers(text, allowed) == ["33"]


def test_rounded_values_and_native_digits_accepted():
    allowed = grounding.allowed_numbers([41.43, 72.0])
    assert grounding.unverified_numbers("ಮರಳು ೪೧.೪% ಮತ್ತು 72%", allowed) == []
