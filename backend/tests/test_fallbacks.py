"""Fallback chain: MET Norway when Open-Meteo returns 429/5xx, and NASA POWER for the rainfall baseline
when the Open-Meteo archive fails and no baseline is saved."""
import copy
from datetime import date, datetime

import httpx
import pytest

from app import baseline, config, http
from app.rules import deficit
from app.sources import forecast, metno

from .conftest import load_fixture

NOW = datetime.fromisoformat("2026-10-31T19:00:00+05:30")
DHARWAD = {"name": "Dharwad", "district": "Dharwad district", "lat": 15.46005, "lon": 75.00778}


def metno_payload() -> dict:
    """A MET Norway compact response in the documented shape (UTC times, wind in m/s)."""
    steps = []
    for i in range(70):
        hour = datetime.fromisoformat("2026-10-31T13:00:00+00:00").timestamp() + i * 3600
        t = datetime.fromtimestamp(hour, tz=datetime.fromisoformat("2026-01-01T00:00:00+00:00").tzinfo)
        steps.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": {
            "instant": {"details": {"air_temperature": 25.0 + (i % 12), "relative_humidity": 60.0,
                                    "wind_speed": 2.78}},
            "next_1_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 0.2}},
            "next_6_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 1.2}},
        }})
    return {"type": "Feature", "properties": {"meta": {"units": {"wind_speed": "m/s"}}, "timeseries": steps}}


@pytest.fixture
def world(monkeypatch):
    """Open-Meteo answers with the script; MET Norway is served by a mock transport and counted."""
    calls = {"open_meteo": 0, "metno": []}
    om_script: list = []

    def handler(request: httpx.Request):
        if "api.met.no" in request.url.host:
            calls["metno"].append(request)
            return httpx.Response(200, json=metno_payload(),
                                  headers={"Expires": "Sat, 31 Oct 2099 14:26:35 GMT",
                                           "Last-Modified": "Sat, 31 Oct 2026 13:56:30 GMT"})
        calls["open_meteo"] += 1
        return om_script.pop(0)

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(config, "METNO_CONTACT", "test@example.org")

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_sleep)
    metno.clear()
    return calls, om_script


def test_wind_conversion_m_s_to_km_h():
    assert metno.wind_kmh(2.78) == 10.0
    assert metno.wind_kmh(0) == 0.0 and metno.wind_kmh(None) is None


async def test_open_meteo_429_switches_to_met_norway(world):
    calls, om = world
    om += [httpx.Response(429, json={"error": True, "reason": "Minutely API request limit exceeded."})]
    res = await forecast.fetch(DHARWAD["lat"], DHARWAD["lon"], past_from=date(2026, 10, 1), today=date(2026, 10, 31))

    assert calls["open_meteo"] == 1 and len(calls["metno"]) == 1
    req = calls["metno"][0]
    assert req.headers["User-Agent"] == "YieldGuard/1.0 (contact: test@example.org)"
    assert req.url.params["lat"] == "15.4601" and req.url.params["lon"] == "75.0078"  # 4 decimals

    assert res.ok and res.name == metno.NAME and "MET Norway fallback" in res.name and res.fetched_at
    assert "Open-Meteo Forecast API failed" in res.error and res.meta["fallback_for"] == "Open-Meteo"
    h = res.data["hours"][0]
    assert h["wind_speed_10m"] == 10.0  # 2.78 m/s converted before any rule runs
    assert h["precipitation_probability"] is None  # not in the compact product: rules treat it as missing
    assert res.data["provider"] == "metno" and res.data["days"][0]["temperature_2m_max"] is not None


async def test_met_norway_cache_respects_expires(world):
    calls, om = world
    om += [httpx.Response(503), httpx.Response(503), httpx.Response(503), httpx.Response(503)]
    for _ in range(2):
        r = await forecast.fetch(DHARWAD["lat"], DHARWAD["lon"], past_from=date(2026, 10, 1), today=date(2026, 10, 31))
        assert r.ok and r.name == metno.NAME
    assert len(calls["metno"]) == 1  # second answer served from the stored response until Expires


async def test_other_open_meteo_errors_do_not_use_met_norway(world):
    calls, om = world
    om += [httpx.Response(400, text="bad request")]
    res = await forecast.fetch(DHARWAD["lat"], DHARWAD["lon"], past_from=date(2026, 10, 1), today=date(2026, 10, 31))
    assert not res.ok and calls["metno"] == []


async def test_met_norway_needs_a_contact(world, monkeypatch):
    calls, om = world
    monkeypatch.setattr(config, "METNO_CONTACT", "")
    om += [httpx.Response(503), httpx.Response(503)]
    res = await forecast.fetch(DHARWAD["lat"], DHARWAD["lon"], past_from=date(2026, 10, 1), today=date(2026, 10, 31))
    assert not res.ok and calls["metno"] == []


# ---- NASA POWER baseline -----------------------------------------------------

def nasa_payload_from_archive() -> dict:
    """NASA POWER JSON built from the saved real archive values (same calendar), in NASA's format."""
    daily = load_fixture("archive_dharwad_2000_2025.json")["daily"]
    series = {t.replace("-", ""): v for t, v in zip(daily["time"], daily["precipitation_sum"])}
    return {"type": "Feature", "header": {"fill_value": -999.0},
            "properties": {"parameter": {"PRECTOTCORR": series}}}


def test_nasa_power_fill_values_are_excluded_from_the_average():
    payload = nasa_payload_from_archive()
    series = payload["properties"]["parameter"]["PRECTOTCORR"]
    series["20030915"] = -999.0  # one missing day inside the compared window for 2003
    series["20111020"] = -999    # and one for 2011

    parsed = baseline.parse_nasa_power(payload)
    assert parsed["2003-09-15"] is None and parsed["2011-10-20"] is None
    assert all(v is None or v >= 0 for v in parsed.values())  # no -999 reaches any sum

    for start, end, dropped in ((date(2026, 9, 1), date(2026, 9, 30), 2003), (date(2026, 10, 1), date(2026, 10, 30), 2011)):
        mean, years = deficit.baseline_mean(parsed, start, end, 2000, 2025)
        assert dropped not in years and len(years) == 25
        totals = [sum(parsed[date(y, start.month, d).isoformat()] for d in range(start.day, end.day + 1))
                  for y in range(2000, 2026) if y != dropped]
        assert mean == round(sum(totals) / len(totals), 1)  # average of the other years only


@pytest.fixture
def archive_down(monkeypatch):
    calls = []

    async def fake_get_json(url, params, **kw):
        calls.append(url)
        if url == config.ARCHIVE_URL:
            raise http.FetchError("HTTP 503", status=503)
        payload = nasa_payload_from_archive()
        payload["properties"]["parameter"]["PRECTOTCORR"]["20051010"] = -999.0
        return payload

    monkeypatch.setattr(baseline, "get_json", fake_get_json)
    return calls


async def test_nasa_power_builds_baseline_when_archive_fails_and_none_is_saved(archive_down, tmp_path):
    store = baseline.BaselineStore(tmp_path / "b.json", autostart=False)
    assert await store.build(DHARWAD)
    assert archive_down == [config.ARCHIVE_URL, config.NASA_POWER_URL]  # archive first, then NASA POWER
    entry = store.entries[baseline.district_key(DHARWAD)]
    assert entry["source"] == baseline.NASA_NAME and "NASA POWER" in entry["source"] and entry["built_at"]
    res = await store.get(DHARWAD, date(2026, 10, 31))
    assert res.ok and res.name == baseline.NASA_NAME and res.data["daily"]["2005-10-10"] is None


async def test_nasa_power_not_used_when_a_baseline_is_already_saved(archive_down, tmp_path):
    store = baseline.BaselineStore(tmp_path / "b.json", autostart=False)
    key = baseline.district_key(DHARWAD)
    store.entries[key] = copy.deepcopy(baseline.build_entry(DHARWAD, load_fixture("archive_dharwad_2000_2025.json"),
                                                            2000, 2025, NOW))
    assert not await store.build(DHARWAD)  # archive refresh failed...
    assert archive_down == [config.ARCHIVE_URL]  # ...and NASA POWER was not called
    assert store.entries[key]["source"] == "Open-Meteo Historical Weather (Archive) API"  # saved one kept
