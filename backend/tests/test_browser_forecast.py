"""POST /api/advice with a forecast fetched in the visitor's browser: the server checks it, uses it in place of
its own Open-Meteo call, and falls back to MET Norway (without calling Open-Meteo) when the browser fetch failed."""
import copy
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import advisor, config, http, llm
from app.http import SourceResult
from app.main import app
from app.sources import browser_forecast, metno
from app.sources.rainfall import parse_daily
from app.sources.soil import convert
from app.timeutil import TZ, iso

from .conftest import load_fixture
from .test_fallbacks import metno_payload

# The saved forecast starts at 2026-10-31T17:00 local time.
NOW = datetime(2026, 10, 31, 17, 20, tzinfo=TZ)
DHARWAD = {"name": "Dharwad", "district": "Dharwad district", "state": "Karnataka", "lat": 15.46005, "lon": 75.00778}

client = TestClient(app)


def ok(source_id, data):
    return SourceResult(source_id, source_id.title(), "https://example.invalid", data=data, fetched_at=NOW)


@pytest.fixture
def world(monkeypatch):
    """Geocode, baseline and soil are stubbed. Every outgoing HTTP call is counted; a server-side
    Open-Meteo call fails the test."""
    calls = {"open_meteo": 0, "metno": 0}

    def handler(request: httpx.Request):
        if "api.met.no" in request.url.host:
            calls["metno"] += 1
            return httpx.Response(200, json=metno_payload(), headers={"Expires": "Sat, 31 Oct 2099 14:26:35 GMT"})
        calls["open_meteo"] += 1
        return httpx.Response(500)

    async def geo(q, count=10):
        return ok("geocode", [DHARWAD])

    async def base(place, today):
        return ok("rain_baseline", {"daily": parse_daily(load_fixture("archive_dharwad_2000_2025.json")),
                                    "district": "Dharwad district", "start_year": 2000, "end_year": 2025})

    async def soil(lat, lon):
        return ok("soil", {"properties": convert(load_fixture("soil_dharwad_nearby.json")),
                           "query_lat": 15.4801, "query_lon": 75.0078, "offset_km": 2.2})

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "METNO_CONTACT", "test@example.org")
    monkeypatch.setattr(advisor.geocode, "search", geo)
    monkeypatch.setattr(advisor.baseline.store, "get", base)
    monkeypatch.setattr(advisor.soil, "fetch", soil)
    monkeypatch.setattr(advisor, "now_local", lambda: NOW)
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    metno.clear()
    return calls


def fetched(minutes_ago: float = 1) -> str:
    return iso(NOW - timedelta(minutes=minutes_ago))


def post(forecast: dict, **extra):
    body = {"question": "Can I spray today?", "location": "Dharwad", "lang": "en", "forecast": forecast, **extra}
    return client.post("/api/advice", json=body)


def good() -> dict:
    return {"ok": True, "data": copy.deepcopy(load_fixture("forecast_full_dharwad.json")), "fetched_at": fetched(),
            "cached": False}


def test_browser_forecast_is_used_and_named(world):
    r = post(good())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forecast_path"] == "browser"
    fc = next(s for s in body["sources"] if s["id"] == "forecast")
    assert fc["name"] == "Open-Meteo (fetched in your browser)" and fc["status"] == "ok"
    assert fc["fetched_at"] == fetched()
    mtd = next(s for s in body["sources"] if s["id"] == "rain_mtd")
    assert "fetched in your browser" in mtd["name"] and mtd["status"] == "ok"
    assert body["forecast_hourly"]["hours"] and body["spray_windows"] is not None
    assert world == {"open_meteo": 0, "metno": 0}  # the server called no weather API


def test_browser_429_uses_met_norway_without_any_open_meteo_call(world):
    r = post({"ok": False, "status": 429, "error": "HTTP 429"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forecast_path"] == "metno"
    fc = next(s for s in body["sources"] if s["id"] == "forecast")
    assert fc["name"] == metno.NAME and fc["fallback_for"] == "Open-Meteo"
    assert "Open-Meteo in your browser failed (HTTP 429)" in fc["note"]
    assert world == {"open_meteo": 0, "metno": 1}


def test_browser_failure_and_met_norway_unavailable(world, monkeypatch):
    monkeypatch.setattr(config, "METNO_CONTACT", "")
    body = post({"ok": False, "status": None, "error": "timeout"}).json()
    assert body["forecast_path"] == "unavailable"
    fc = next(s for s in body["sources"] if s["id"] == "forecast")
    assert fc["status"] == "failed" and "Open-Meteo in your browser failed (timeout)" in fc["error"]
    assert world["open_meteo"] == 0


def _with(path: str, value) -> dict:
    f = good()
    section, var, i = path.split(".")
    f["data"][section][var][int(i)] = value
    return f


@pytest.mark.parametrize("forecast, says", [
    (_with("hourly.temperature_2m.3", 75.0), "'hourly.temperature_2m' has the value 75.0, outside -20 to 60"),
    (_with("hourly.wind_speed_10m.0", -4), "'hourly.wind_speed_10m'"),
    (_with("hourly.wind_speed_10m.0", 301), "'hourly.wind_speed_10m'"),
    (_with("hourly.precipitation_probability.5", 120), "'hourly.precipitation_probability'"),
    (_with("hourly.precipitation_probability.5", "high"), "'hourly.precipitation_probability'"),
    (_with("daily.temperature_2m_max.31", -40), "'daily.temperature_2m_max'"),
    ({**good(), "fetched_at": fetched(minutes_ago=40)}, "fetched 40 minutes ago"),
    ({**good(), "fetched_at": fetched(minutes_ago=-30)}, "in the future"),
    ({**good(), "fetched_at": "yesterday"}, "not a valid time"),
    ({**good(), "data": None}, "no forecast data was sent"),
])
def test_bad_forecast_is_rejected_with_a_clear_message(world, forecast, says):
    r = post(forecast)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_forecast" and says in err["message"], err
    assert world["open_meteo"] == 0


def test_missing_column_and_wrong_place_are_rejected(world):
    f = good()
    del f["data"]["hourly"]["wind_speed_10m"]
    assert "'hourly.wind_speed_10m' is missing" in post(f).json()["error"]["message"]

    f = good()
    f["data"]["latitude"] = 12.97  # Bengaluru's grid point, sent for Dharwad
    assert "not for 15.460, 75.008" in post(f).json()["error"]["message"]

    f = good()
    f["data"]["hourly"]["time"] = [t.replace("2026-10-31", "2026-10-29") for t in f["data"]["hourly"]["time"]]
    assert "not at the current hour" in post(f).json()["error"]["message"]


def test_get_advice_still_uses_the_server_fetch(world, monkeypatch):
    seen = []

    async def fc(lat, lon, past_from=None, today=None):
        seen.append((lat, lon))
        return browser_forecast.SourceResult("forecast", "Open-Meteo Forecast API", config.FORECAST_URL,
                                             status="failed", error="HTTP 500")

    monkeypatch.setattr(advisor.forecast, "fetch", fc)
    body = client.get("/api/advice", params={"q": "Can I spray?", "location": "Dharwad"}).json()
    assert seen and body["forecast_path"] == "unavailable"


# --- past rain: a separate request, once per place per day ----------------------------------------

def light() -> dict:
    """The forecast as the page now asks for it: no past days."""
    f = good()
    daily = f["data"]["daily"]
    keep = [i for i, t in enumerate(daily["time"]) if t >= "2026-10-31"]
    f["data"]["daily"] = {k: [v[i] for i in keep] for k, v in daily.items()}
    return f


def rain(hours_ago: float = 3, cached: bool = True) -> dict:
    return {"ok": True, "data": copy.deepcopy(load_fixture("mtd_dharwad_2026-10.json")),
            "fetched_at": iso(NOW - timedelta(hours=hours_ago)), "cached": cached}


def deficit(body: dict) -> dict:
    return next(r for r in body["rules"] if r["id"] == "rain_deficit")


def test_past_rain_from_its_own_request_feeds_the_deficit_rule(world):
    r = post(light(), past_rain=rain())
    assert r.status_code == 200, r.text
    body = r.json()
    mtd = next(s for s in body["sources"] if s["id"] == "rain_mtd")
    assert mtd["name"] == browser_forecast.PAST_RAIN_NAME and mtd["status"] == "ok" and mtd["cached"]
    assert mtd["fetched_at"] == iso(NOW - timedelta(hours=3))  # its own fetch time, not the forecast's
    assert deficit(body)["status"] != "unknown"
    assert world == {"open_meteo": 0, "metno": 0}


def test_light_forecast_without_past_rain_reports_rain_missing(world):
    body = post(light(), past_rain={"ok": False, "status": 429, "error": "HTTP 429"}).json()
    mtd = next(s for s in body["sources"] if s["id"] == "rain_mtd")
    assert mtd["status"] == "failed" and "HTTP 429" in mtd["error"]
    assert body["forecast_path"] == "browser" and deficit(body)["status"] == "unknown"
    assert world == {"open_meteo": 0, "metno": 0}


def test_past_rain_still_used_when_the_forecast_falls_back_to_met_norway(world):
    body = post({"ok": False, "status": 429, "error": "HTTP 429"}, past_rain=rain()).json()
    assert body["forecast_path"] == "metno"
    mtd = next(s for s in body["sources"] if s["id"] == "rain_mtd")
    assert mtd["status"] == "ok" and deficit(body)["status"] != "unknown"
    assert world == {"open_meteo": 0, "metno": 1}


@pytest.mark.parametrize("change, says", [
    (lambda p: p.update(fetched_at=iso(NOW - timedelta(days=1))), "not fetched today"),
    (lambda p: p["data"]["daily"]["time"].__setitem__(-1, "2026-10-31"), "outside 2026-10-01 to 2026-10-30"),
    (lambda p: p["data"]["daily"]["precipitation_sum"].__setitem__(4, -3), "'daily.precipitation_sum'"),
    (lambda p: p["data"].update(longitude=77.59), "the past rain is for"),
])
def test_bad_past_rain_is_rejected_before_any_fetch(world, change, says):
    p = rain()
    change(p)
    r = post(light(), past_rain=p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_past_rain"
    assert says in r.json()["error"]["message"], r.json()
    assert world == {"open_meteo": 0, "metno": 0}
