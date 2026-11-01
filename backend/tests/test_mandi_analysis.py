"""POST /api/mandi/analysis from saved real responses: the 1 Nov 2026 data.gov.in snapshot, the real Open-Meteo
forecast captured on 1 Nov (posted as the browser would) and saved geocoding. The clock is frozen to the
forecast's capture time from manifest.json."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, llm, mandi_analysis
from app.http import SourceResult
from app.main import app
from app.sources import geocode, mandi

from .conftest import load_fixture

FORECAST = "forecast_browser_dharwad_2026-11-01.json"
CAPTURED = datetime.fromisoformat(load_fixture("manifest.json")[FORECAST]["captured_at"])
client = TestClient(app)


@pytest.fixture
def world(monkeypatch):
    """data.gov.in answers with the saved snapshot; places come from saved geocoding; Gemini is off unless set."""
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    payload = load_fixture("mandi_karnataka_2026-11-01.json")

    async def api(url, params, **kw):
        return payload

    saved = {**load_fixture("mandi_geocode.json")["by_query"], "Dharwad": load_fixture("geocode_dharwad.json")}

    async def search(q, count=10):
        resp = saved.get(q)
        if resp is None:
            return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, status="failed", error="no saved response")
        places = [p.__dict__ for p in geocode.pick_karnataka(resp.get("results") or [])]
        return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, data=places, fetched_at=CAPTURED)

    monkeypatch.setattr(mandi, "get_json", api)
    monkeypatch.setattr(geocode, "search", search)
    for mod in (mandi_analysis, mandi):
        monkeypatch.setattr(mod, "now_local", lambda: CAPTURED)


def browser_forecast() -> dict:
    return {"ok": True, "data": load_fixture(FORECAST), "fetched_at": CAPTURED.isoformat(), "cached": False}


def post(crop="Maize", lang="en", forecast=None, **where):
    body = {"crop": crop, "lang": lang, "forecast": forecast or browser_forecast(), **(where or {"location": "Dharwad"})}
    return client.post("/api/mandi/analysis", json=body)


def section(body, title):
    return next(s for s in body["analysis"]["sections"] if s["title"] == title)


def test_rule_based_analysis_is_labelled_cited_and_number_checked(world):
    r = post()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generated_by"] == "rules-fallback" and "Language model unavailable" in body["warnings"][-1]
    assert body["analysis"]["summary"].startswith("Automatic summary (language model unavailable):")
    assert body["mandi"]["status"] == "found" and body["mandi"]["market"]["name"] == "Ranebennur APMC"
    rec = body["mandi"]["records"][0]
    price = section(body, "Price at the nearest market")
    assert f"Rs {rec['modal_price']:g}" in price["text"] and f"Rs {rec['max_price'] - rec['min_price']:g}" in price["text"]
    assert {"mandi_modal_price", "mandi_spread", "mandi_arrival_date"} <= set(price["evidence"])
    assert section(body, "Other markets nearby")["text"] == "No other market within 125 km reports this crop."
    weather = section(body, "Weather and timing")
    assert "Estimate, not a harvest recommendation" in weather["text"] and "03/11, 05/11" in weather["text"]
    assert weather["evidence"][-2:] == ["dry_day_1", "dry_day_2"] and "max_rain_prob_24h" in weather["evidence"]
    assert body["unverified_numbers"] == []
    ids = {p["id"] for p in body["data_points"]}
    for s in body["analysis"]["sections"]:
        assert set(s["evidence"]) <= ids | {r["id"] for r in body["rules"]}
    dry = next(r for r in body["rules"] if r["id"] == "dry_days")
    assert dry["name"] == "Dry days for harvest and transport (estimate)" and dry["status"] == "found"
    assert dry["summary"].startswith("Estimate only, not a harvest recommendation")
    fc = next(s for s in body["sources"] if s["id"] == "forecast")
    assert fc["name"] == "Open-Meteo (fetched in your browser)" and fc["status"] == "ok"
    assert next(s for s in body["sources"] if s["id"] == "mandi")["status"] == "ok"


def test_gemini_answer_keeps_only_known_citations_and_flags_invented_numbers(world, monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "set")
    calls = []

    async def gemini(msg):
        calls.append(msg)
        return {"summary": "Maize at Ranebennur APMC.",
                "sections": [{"title": "Price", "text": "The modal price is Rs 3202 per quintal.",
                              "evidence": ["mandi_modal_price", "made_up_id"]},
                             {"title": "Outlook", "text": "It may reach Rs 4100 next week.", "evidence": []}],
                "missing_data": [], "disclaimer": "Prices change daily."}, "gemini-test"

    monkeypatch.setattr(llm, "mandi_analysis", gemini)
    body = post().json()
    assert body["generated_by"] == "gemini-test" and body["llm_error"] is None
    assert body["analysis"]["sections"][0]["evidence"] == ["mandi_modal_price"]  # unknown id dropped
    assert body["unverified_numbers"] == ["4100"]  # 3202 is in the snapshot; 4100 is not
    msg = calls[0]
    assert '"id": "mandi_modal_price"' in msg and '"id": "dry_days"' in msg and "test-key" not in msg


def test_repeat_within_30_minutes_is_cached(world, monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "set")
    calls = []

    async def gemini(msg):
        calls.append(msg)
        return {"summary": "s", "sections": [], "missing_data": [], "disclaimer": "d"}, "gemini-test"

    monkeypatch.setattr(llm, "mandi_analysis", gemini)
    first, again = post().json(), post().json()
    assert len(calls) == 1 and not first["served_from_cache"] and again["served_from_cache"]
    assert again["request_id"] == first["request_id"]
    assert post(lang="kn").json()["served_from_cache"] is False  # another language is another analysis


def test_hindi_fallback_uses_hindi_titles_and_crop_name(world):
    body = post(lang="hi").json()
    assert body["language"] == "hi" and body["labels"]["hi"] == "मक्का"
    assert body["analysis"]["sections"][0]["title"] == "सबसे नज़दीकी मंडी का भाव"
    assert "केवल अनुमान, कटाई की सलाह नहीं" in section(body, "मौसम और समय")["text"]
    assert body["unverified_numbers"] == []


def test_no_nearby_market(world):
    body = post(crop="Tomato").json()
    assert body["mandi"]["status"] == "no_nearby_market" and body["mandi"]["records"] == []
    assert section(body, "Price at the nearest market")["text"] == "No market within 125 km reports a price for Tomato."
    assert not any(p["id"] == "mandi_modal_price" for p in body["data_points"])


def test_older_arrival_date_says_latest_available(world, monkeypatch):
    for mod in (mandi_analysis, mandi):
        monkeypatch.setattr(mod, "now_local", lambda: CAPTURED + timedelta(days=1))
    failed = {"ok": False, "status": None, "error": "network error"}  # a day-old forecast would be rejected
    body = post(forecast=failed).json()
    assert body["mandi"]["status"] == "latest"
    text = section(body, "Price at the nearest market")["text"]
    assert "latest available: 2026-11-01" in text and "today" not in text.lower()


def test_failed_browser_forecast_still_gives_the_price_and_says_so(world):
    body = post(forecast={"ok": False, "status": 429, "error": "HTTP 429"}).json()
    fc = next(s for s in body["sources"] if s["id"] == "forecast")
    assert fc["status"] == "failed" and "Open-Meteo in your browser failed (HTTP 429)" in fc["error"]
    assert section(body, "Weather and timing")["text"].startswith("The forecast is unavailable")
    assert body["mandi"]["status"] == "found"


def test_stale_browser_forecast_is_rejected(world):
    old = {**browser_forecast(), "fetched_at": (CAPTURED - timedelta(minutes=40)).isoformat()}
    r = post(forecast=old)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_forecast"
