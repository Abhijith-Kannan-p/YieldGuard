"""The landing page's 'Today in your field' card must not hit the APIs more than once per hour per location."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import http, today
from app.main import app
from app.sources import forecast, geocode, soil

from .conftest import load_fixture

client = TestClient(app)
NOW = datetime.fromisoformat("2026-10-31T18:13:29+05:30")


def _fake_world(monkeypatch):
    """Count real upstream calls: get_json is what talks to Open-Meteo / SoilGrids."""
    calls = []
    payload = load_fixture("forecast_full_dharwad.json")

    async def fake_get_json(url, params, **kw):
        calls.append(url)
        if "geocoding" in url:
            found = params["name"].lower().startswith("dharwad")
            return load_fixture("geocode_dharwad.json") if found else {"results": []}
        if "forecast" in url:
            return payload
        return load_fixture("soil_dharwad_nearby.json")

    for mod in (geocode, forecast, soil):
        monkeypatch.setattr(mod, "get_json", fake_get_json)
    clock = [NOW]
    monkeypatch.setattr(today, "now_local", lambda: clock[0])
    monkeypatch.setattr(http, "now_local", lambda: clock[0])
    t = [1000.0]
    monkeypatch.setattr(today._cache, "_clock", lambda: t[0])
    monkeypatch.setattr(http.cache, "_clock", lambda: t[0])
    return calls, t


def test_today_card_calls_apis_at_most_once_per_hour_per_location(monkeypatch):
    calls, t = _fake_world(monkeypatch)
    first = client.get("/api/today", params={"location": "Dharwad"}).json()
    n = len(calls)
    assert n >= 2 and not first["served_from_cache"]  # geocode + forecast (+ soil)
    assert first["rain_24h"]["max_prob_pct"] is not None and first["sources"]["forecast"]["fetched_at"]

    for minutes in (1, 30, 59):
        t[0] = 1000.0 + minutes * 60
        again = client.get("/api/today", params={"location": "Dharwad"}).json()
        assert again["served_from_cache"] and again["computed_at"] == first["computed_at"]
    assert len(calls) == n  # no upstream call within the hour

    t[0] = 1000.0 + 61 * 60
    later = client.get("/api/today", params={"location": "Dharwad"}).json()
    assert not later["served_from_cache"] and len(calls) > n


def test_today_unknown_location_is_a_clear_error(monkeypatch):
    calls, _ = _fake_world(monkeypatch)
    r = client.get("/api/today", params={"location": "Atlantis"})
    assert r.status_code == 404 and "Atlantis" in r.json()["error"]["message"]


def test_today_reports_failed_forecast_without_crashing(monkeypatch):
    _fake_world(monkeypatch)

    async def down(*a, **k):
        raise http.FetchError("rate limit reached (HTTP 429); paused for 60 s")

    monkeypatch.setattr(forecast, "get_json", down)
    body = client.get("/api/today", params={"location": "Dharwad"}).json()
    assert body["spray"] is None and body["sources"]["forecast"]["status"] == "failed"
    assert "429" in body["sources"]["forecast"]["error"]
