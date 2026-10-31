"""End-to-end API tests with the network replaced by saved real responses,
plus failure scenarios: a source down, all sources down, unknown location,
LLM failure, and LLM output that cites unknown ids or invents numbers."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import advisor, llm
from app.http import SourceResult
from app.main import app
from app.sources.forecast import parse_hourly
from app.sources.rainfall import parse_daily
from app.sources.soil import convert
from app.timeutil import TZ

from .conftest import load_fixture

NOW = datetime(2026, 10, 31, 8, 30, tzinfo=TZ)
FETCHED = datetime(2026, 10, 31, 8, 29, tzinfo=TZ)
DHARWAD = {"name": "Dharwad", "district": "Dharwad district", "state": "Karnataka", "lat": 15.46005, "lon": 75.00778}


def ok(source_id, data):
    return SourceResult(source_id, source_id.title(), "https://example.invalid", data=data, fetched_at=FETCHED)


def failed(source_id):
    return SourceResult(source_id, source_id.title(), "https://example.invalid", status="failed",
                        error="timed out after 8s")


@pytest.fixture
def live(monkeypatch):
    """Patch every source with saved real responses; tests override individual ones."""
    state = {
        "geocode": ok("geocode", [DHARWAD]),
        # One forecast request returns both the hourly forecast and recent daily rain (past_days).
        "forecast": ok("forecast", {**parse_hourly(load_fixture("forecast_dharwad.json")),
                                    "daily": parse_daily(load_fixture("mtd_dharwad_2026-10.json"))}),
        "rain_baseline": ok("rain_baseline", {"daily": parse_daily(load_fixture("archive_dharwad_2000_2025.json")),
                                              "district": "Dharwad district", "start_year": 2000, "end_year": 2025}),
        "soil": ok("soil", {"properties": convert(load_fixture("soil_dharwad_nearby.json")),
                            "query_lat": 15.4801, "query_lon": 75.0078, "offset_km": 2.2}),
    }

    async def geo(q, count=10):
        return state["geocode"]

    async def fc(lat, lon, past_from=None, today=None):
        return state["forecast"]

    async def base(place, today):
        return state["rain_baseline"]

    async def soil(lat, lon):
        return state["soil"]

    monkeypatch.setattr(advisor.geocode, "search", geo)
    monkeypatch.setattr(advisor.forecast, "fetch", fc)
    monkeypatch.setattr(advisor.baseline.store, "get", base)
    monkeypatch.setattr(advisor.soil, "fetch", soil)
    monkeypatch.setattr(advisor, "now_local", lambda: NOW)
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")  # default: no LLM -> fallback
    return state


client = TestClient(app)


def get(**params):
    return client.get("/api/advice", params=params)


def test_every_data_point_has_source_and_fetch_time(live):
    r = get(q="Can I spray today?", location="Dharwad")
    assert r.status_code == 200
    body = r.json()
    assert body["data_points"]
    for p in body["data_points"]:
        assert p["source"] and p["fetched_at"], p
    for s in body["sources"]:
        assert s["status"] == "ok" and s["fetched_at"]
    assert body["generated_by"] == "rules-fallback"
    assert body["answer"]["disclaimer"]


def test_rules_reference_existing_data_points(live):
    body = get(q="spray?").json()
    ids = {p["id"] for p in body["data_points"]}
    for rule in body["rules"]:
        assert set(rule["evidence"]) <= ids
    assert {r["id"] for r in body["rules"]} == {"spray_window", "heavy_rain", "rain_deficit", "soil"}


def test_language_follows_question(live):
    assert get(q="ನಾಳೆ ಸಿಂಪಡಿಸಬಹುದೇ?").json()["language"] == "kn"
    assert get(q="क्या मैं कल छिड़काव कर सकता हूँ?").json()["language"] == "hi"
    assert get(q="spray?", lang="kn").json()["language"] == "kn"


def test_one_source_down_is_reported_not_crashed(live):
    live["soil"] = failed("soil")
    body = get(q="Should I irrigate?").json()
    assert any("Soil" in w for w in body["warnings"])
    assert not any(p["id"].startswith("soil_") for p in body["data_points"])
    assert next(r for r in body["rules"] if r["id"] == "soil")["status"] == "unknown"
    assert next(s for s in body["sources"] if s["id"] == "soil")["error"] == "timed out after 8s"


def test_all_data_sources_down(live):
    for k in ("forecast", "rain_baseline", "soil"):
        live[k] = failed(k)
    r = get(q="Can I spray?")
    assert r.status_code == 200
    body = r.json()
    assert len(body["warnings"]) >= 4
    assert body["spray_windows"] == [] and body["forecast_hourly"] is None
    assert body["answer"]["missing_data"]


def test_unknown_location(live):
    live["geocode"] = ok("geocode", [])
    r = get(q="spray?", location="Atlantis")
    assert r.status_code == 404
    assert "Atlantis" in r.json()["error"]["message"]


def test_geocoder_down(live):
    live["geocode"] = failed("geocode")
    r = get(q="spray?", location="Hubballi")
    assert r.status_code == 503 and r.json()["error"]["code"] == "geocoding_failed"


def test_coordinates_outside_karnataka_rejected(live):
    r = get(q="spray?", lat=28.6, lon=77.2)
    assert r.status_code == 422


def test_coordinates_inside_karnataka_accepted(live):
    body = get(q="spray?", lat=15.35, lon=75.14).json()
    assert body["location"]["lat"] == 15.35


def test_empty_question(live):
    assert get(q="   ").status_code == 422


def test_llm_answer_is_sanitised_and_number_checked(live, monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "test-key")

    async def fake_generate(msg):
        assert "<farmer_question>" in msg and "spray_window_1" in msg
        return {
            "answer": "Yes. Spray between 11:00 and 19:00. Wind stays under 9.4 km/h. Expect 55 mm rain.",
            "recommendations": [{"text": "Spray in the morning window.", "evidence": ["spray_window_1", "made_up_id"]}],
            "why": [{"text": "Wind is low.", "evidence": ["max_wind_24h"]}],
            "missing_data": [],
            "disclaimer": "Confirm with your KVK.",
        }, "gemini-test"

    monkeypatch.setattr(llm, "generate", fake_generate)
    body = get(q="Can I spray?").json()
    assert body["generated_by"] == "gemini-test"
    assert body["answer"]["recommendations"][0]["evidence"] == ["spray_window_1"]
    assert body["unverified_numbers"] == ["55"]


def test_llm_failure_falls_back(live, monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "test-key")

    async def boom(msg):
        raise llm.LLMError("language model timed out after 45s")

    monkeypatch.setattr(llm, "generate", boom)
    body = get(q="ನಾಳೆ ಸಿಂಪಡಿಸಬಹುದೇ?").json()
    assert body["generated_by"] == "rules-fallback"
    assert "timed out" in body["llm_error"]
    assert "ಸಿಂಪಡಣೆ" in body["answer"]["text"]


def test_rules_endpoint_reflects_config():
    from app import config
    assert client.get("/api/rules").json()["spray_window"]["max_wind_kmh"] == config.SPRAY_MAX_WIND_KMH


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_health_calls_no_external_service(monkeypatch):
    from app import http

    def no_network(*a, **k):
        raise AssertionError("health must not call an external service")

    monkeypatch.setattr(http, "get_client", no_network)
    monkeypatch.setattr(llm, "_get_client", no_network)
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and "rainfall_baselines" in body


def test_advice_alias_takes_question_param(live):
    r = client.get("/advice", params={"location": "Dharwad", "question": "Can I spray today?", "lang": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "en" and body["location"]["name"] == "Dharwad"


def test_advice_alias_unknown_location_is_json_error(live):
    live["geocode"] = ok("geocode", [])
    r = client.get("/advice", params={"location": "Atlantis", "question": "spray?"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "location_not_found"


def test_advice_without_question_serves_page_not_json():
    r = client.get("/advice")
    assert r.headers["content-type"].startswith("text/html")


def test_gemini_model_env_var(monkeypatch):
    import importlib

    from app import config

    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("LLM_MODEL", "gemini-old-name")
    try:
        assert importlib.reload(config).LLM_MODEL == "gemini-test-model"
        monkeypatch.delenv("GEMINI_MODEL")
        assert importlib.reload(config).LLM_MODEL == "gemini-old-name"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def _wav(n_bytes=4000):
    import struct

    data = b"\x00\x00" * (n_bytes // 2)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def test_transcribe_returns_text(monkeypatch):
    async def fake(wav, lang):
        assert wav[:4] == b"RIFF" and lang == "kn"
        return {"text": "ನಾಳೆ ಸಿಂಪಡಿಸಬಹುದೇ?", "language": "kn"}, "gemini-main"

    monkeypatch.setattr(llm, "transcribe", fake)
    r = client.post("/api/transcribe?lang=kn", content=_wav(), headers={"content-type": "audio/wav"})
    assert r.status_code == 200
    assert r.json()["text"] == "ನಾಳೆ ಸಿಂಪಡಿಸಬಹುದೇ?" and r.json()["language"] == "kn"


def test_transcribe_rejects_non_wav_and_oversize():
    assert client.post("/api/transcribe", content=b"hello" * 500).status_code == 422
    from app import config

    big = _wav(config.TRANSCRIBE_MAX_BYTES + 10)
    r = client.post("/api/transcribe", content=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "audio_too_long"


def test_transcribe_without_key_is_clear_error(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    r = client.post("/api/transcribe", content=_wav())
    assert r.status_code == 503 and "type your question" in r.json()["error"]["message"]
