"""Mandi prices: crop words, the data.gov.in fetch (slow, failing, saved copy), and the nearest-market states.

Market tests use saved real responses (tests/fixtures/mandi_*.json, from devtools/capture_mandi.py):
the Karnataka snapshot, a real empty response, and real Open-Meteo geocoding for each market name.
They are skipped, with the reason, until those files have been captured.
"""
import asyncio
from datetime import date, timedelta

import pytest

from app import config, crops, evidence, grounding
from app.cache import cache
from app.http import FetchError, SourceResult
from app.sources import geocode, mandi
from app.timeutil import now_local

from .conftest import FIXTURES, load_fixture

SNAPSHOTS = sorted(FIXTURES.glob("mandi_karnataka_*.json"))
needs_snapshot = pytest.mark.skipif(
    not SNAPSHOTS or not (FIXTURES / "mandi_geocode.json").exists() or not (FIXTURES / "mandi_empty.json").exists(),
    reason="real data.gov.in responses not captured yet: run `python -m devtools.capture_mandi` in backend/")


# Crop words

@pytest.mark.parametrize("question, crop", [
    ("What is the price of jowar today?", "jowar"),
    ("ಮೆಕ್ಕೆಜೋಳದ ಬೆಲೆ ಎಷ್ಟು?", "maize"),         # contains ಜೋಳ (jowar): the longer word wins
    ("ಜೋಳಕ್ಕೆ ಬೆಲೆ ಎಷ್ಟು", "jowar"),               # Kannada ending on the word
    ("ಕಡಲೆಕಾಯಿ ಬೆಲೆ", "groundnut"),                 # contains ಕಡಲೆ (Bengal gram)
    ("ಕಡಲೆ ಬೆಲೆ", "bengal_gram"),
    ("प्याज का भाव क्या है?", "onion"),
    ("green gram rate in Haveri", "green_gram"),
    ("ತೊಗರಿ ದರ", "tur"),
    ("ರಾಗಿ ಬೆಲೆ", "ragi"),
])
def test_crop_words_in_three_languages(question, crop):
    assert crops.find_crop(question)["crop"] == crop


@pytest.mark.parametrize("question", ["Can I spray tomorrow?", "my program", "Will it rain in Dharwad?"])
def test_no_crop_named(question):
    assert crops.find_crop(question) is None


@pytest.mark.parametrize("crop, commodity, ok", [
    ("jowar", "Jowar(Sorghum)", True),
    ("bengal_gram", "Bengal Gram(Gram)(Whole)", True),
    ("bengal_gram", "Bengal Gram Dal (Chana Dal)", False),  # a processed product
    ("groundnut", "Ground Nut Seed", True),
    ("rice", "Paddy(Common)", False),
    ("tur", "Arhar Dal(Tur Dal)", False),
])
def test_commodity_names(crop, commodity, ok):
    assert crops.matches(crop, commodity) is ok


# Number check

def test_digit_group_commas_are_one_number():
    allowed = grounding.allowed_numbers([2350.0, 102500.0])
    assert grounding.unverified_numbers("Modal Rs 2,350 per quintal, Rs 1,02,500 in total.", allowed) == []
    assert grounding.unverified_numbers("Modal Rs 2,351 per quintal.", allowed) == ["2351"]
    assert grounding.unverified_numbers("Windows 1,2 and 3.", allowed) == []  # list commas untouched


# Fetch

async def test_missing_key_is_a_clear_failure():
    res = await mandi.fetch()
    assert not res.ok and "DATAGOV_API_KEY is not set" in res.error


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "test-key")
    calls = []
    return calls


async def test_slow_api_does_not_hold_the_question_and_failure_pauses_retries(keyed, monkeypatch):
    monkeypatch.setattr(config, "MANDI_WAIT_S", 0.05)

    async def slow_then_fail(url, params, **kw):
        keyed.append(params)
        await asyncio.sleep(0.2)
        raise FetchError("timed out after 30s")

    monkeypatch.setattr(mandi, "get_json", slow_then_fail)
    first = await mandi.fetch()
    assert not first.ok and "slow to answer" in first.error
    await mandi._task  # the fetch keeps running in the background and fails
    again = await mandi.fetch()
    assert not again.ok and "failed recently" in again.error
    assert len(keyed) == 1  # the second question made no request
    assert all(p["api-key"] == "test-key" for p in keyed)


async def test_request_sends_the_mandi_headers(keyed, monkeypatch):
    import httpx

    from app import http

    seen = []

    def handler(request: httpx.Request):
        seen.append(request.headers)
        return httpx.Response(502)

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await mandi.fetch()
    await mandi._task
    assert seen  # get_json retries once on 502, so every attempt is checked
    for h in seen:
        assert h["user-agent"] == "YieldGuard/1.0 (hackathon project)" and h["accept"] == "*/*"


async def test_api_key_never_in_source_url_or_error(keyed, monkeypatch):
    async def down(url, params, **kw):
        raise FetchError("HTTP 502")

    monkeypatch.setattr(mandi, "get_json", down)
    res = await mandi.fetch()
    assert "test-key" not in res.url and "test-key" not in (res.error or "")


# Market selection (saved real responses)

def snapshot() -> dict:
    return load_fixture(SNAPSHOTS[-1].name)


def snapshot_src(payload: dict | None = None) -> SourceResult:
    payload = payload or snapshot()
    data = mandi.parse(payload.get("records") or [], int(payload.get("total") or 0))
    return SourceResult("mandi", mandi.NAME, config.MANDI_URL, data=data, fetched_at=now_local())


@pytest.fixture
def saved_geocoder(monkeypatch):
    """geocode.search answered from the saved real Open-Meteo responses; lookups are counted."""
    by_query = load_fixture("mandi_geocode.json")["by_query"]
    lookups = []

    async def search(q, count=10):
        lookups.append(q)
        resp = by_query.get(q)
        if resp is None or "error" in resp:
            return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, status="failed", error="no saved response")
        places = [p.__dict__ for p in geocode.pick_karnataka(resp.get("results") or [])]
        return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, data=places, fetched_at=now_local())

    monkeypatch.setattr(mandi.geocode, "search", search)
    return lookups


def dharwad() -> dict:
    return geocode.pick_karnataka(load_fixture("geocode_dharwad.json")["results"])[0].__dict__


def reported_crop(src: SourceResult) -> dict:
    for crop in config.CROP_ALIASES:
        if any(crops.matches(crop, r["commodity"]) for r in src.data["records"]):
            return {"crop": crop, "word": config.CROP_ALIASES[crop]["words"][0]}
    pytest.skip("no aliased crop in the saved snapshot")


def snapshot_day(src: SourceResult) -> date:
    return date.fromisoformat(src.data["snapshot_date"])


@needs_snapshot
def test_parse_keeps_real_rows_and_skips_unusable_ones():
    payload = snapshot()
    rows = payload["records"]
    broken = [{**rows[0], "modal_price": ""}, {**rows[0], "arrival_date": "not a date"}]
    data = mandi.parse(rows + broken, len(rows) + 2)
    assert data["skipped"] >= 2 and len(data["records"]) <= len(rows)
    r = data["records"][0]
    assert isinstance(r["modal_price"], float) and len(r["arrival_date"]) == 10


@needs_snapshot
async def test_nearest_market_within_the_limit(saved_geocoder, monkeypatch):
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)  # every located market qualifies
    src = snapshot_src()
    crop = reported_crop(src)
    res = await mandi.nearest(dharwad(), crop, src, snapshot_day(src))
    assert res["status"] in ("found", "latest"), res
    rec = res["records"][0]
    assert rec["modal_price"] > 0 and crops.matches(crop["crop"], rec["commodity"])
    assert res["status"] == ("found" if rec["arrival_date"] == res["today"] else "latest")
    assert res["market"]["distance_km"] >= 0 and res["market"]["district"] == rec["district"]


@needs_snapshot
async def test_no_nearby_market_never_uses_the_far_one(saved_geocoder, monkeypatch):
    src = snapshot_src()
    crop = reported_crop(src)
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    nearest_km = (await mandi.nearest(dharwad(), crop, src, snapshot_day(src)))["market"]["distance_km"]
    if nearest_km < 1:
        pytest.skip("the nearest saved market is at the place itself")
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", nearest_km - 0.5)
    res = await mandi.nearest(dharwad(), crop, src, snapshot_day(src))
    assert res["status"] == "no_nearby_market" and res["records"] == [] and res["market"] is None
    assert res["nearest_beyond"]["distance_km"] == nearest_km
    assert "today" in res["note"]  # the snapshot is from "today" here

    ev = evidence.Evidence()
    evidence.add_mandi(ev, src, res)
    assert not any(p["id"].endswith("_price") for p in ev.points)


@needs_snapshot
async def test_older_arrival_date_says_latest_available_never_today(saved_geocoder, monkeypatch):
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    src = snapshot_src()
    crop = reported_crop(src)
    later = snapshot_day(src) + timedelta(days=1)
    res = await mandi.nearest(dharwad(), crop, src, later)
    assert res["status"] == "latest"
    ev = evidence.Evidence()
    evidence.add_mandi(ev, src, res)
    summary = next(r for r in ev.rules if r["id"] == "mandi_price")["summary"]
    assert f"latest available: {res['records'][0]['arrival_date']}" in summary
    assert "today" not in summary.lower()

    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 0)
    none = await mandi.nearest(dharwad(), crop, src, later)
    assert "today" not in none["note"] and f"in the latest data ({src.data['snapshot_date']})" in none["note"]


@needs_snapshot
async def test_empty_response_is_no_data(saved_geocoder):
    src = snapshot_src(load_fixture("mandi_empty.json"))
    res = await mandi.nearest(dharwad(), {"crop": "jowar", "word": "jowar"}, src, date.today())
    assert res["status"] == "no_data" and res["records"] == [] and saved_geocoder == []


@needs_snapshot
async def test_crop_not_reported_is_no_market(saved_geocoder):
    src = snapshot_src()
    absent = next((c for c in config.CROP_ALIASES
                   if not any(crops.matches(c, r["commodity"]) for r in src.data["records"])), None)
    if absent is None:
        pytest.skip("every aliased crop is in the saved snapshot")
    res = await mandi.nearest(dharwad(), {"crop": absent, "word": absent}, src, snapshot_day(src))
    assert res["status"] == "no_market" and saved_geocoder == []


@needs_snapshot
async def test_lookup_cap_gives_incomplete_not_no_nearby(saved_geocoder, monkeypatch):
    monkeypatch.setattr(config, "MANDI_MAX_GEOCODES", 0)
    src = snapshot_src()
    res = await mandi.nearest(dharwad(), reported_crop(src), src, snapshot_day(src))
    assert res["status"] == "incomplete" and res["markets_not_located"] == res["markets_reporting"]
    assert saved_geocoder == []


TOMATO = {"crop": "tomato", "word": "tomato"}  # reported only by Ramanagara APMC in the saved snapshot


@needs_snapshot
async def test_market_alias_locates_ramanagara_but_shows_its_own_name(saved_geocoder, monkeypatch):
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    src = snapshot_src()
    res = await mandi.nearest(dharwad(), TOMATO, src, snapshot_day(src))
    assert res["status"] == "found" and saved_geocoder == ["Closepet"]  # looked up by its alias
    closepet = geocode.pick_karnataka(load_fixture("mandi_geocode.json")["by_query"]["Closepet"]["results"])[0]
    m = res["market"]
    assert m["name"] == "Ramanagara APMC" and m["located_as"] == "Closepet"  # the farmer sees the data.gov.in name
    assert (m["lat"], m["lon"]) == (closepet.lat, closepet.lon) and res["markets_not_located"] == 0
    ev = evidence.Evidence()
    evidence.add_mandi(ev, src, res)
    assert next(p for p in ev.points if p["id"] == "mandi_market")["value"].startswith("Ramanagara APMC")

    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 125)  # Ramanagara is far from Dharwad
    far = await mandi.nearest(dharwad(), TOMATO, src, snapshot_day(src))
    assert far["status"] == "no_nearby_market" and far["nearest_beyond"]["market"] == "Ramanagara APMC"
    assert far["nearest_beyond"]["distance_km"] > 125


@needs_snapshot
async def test_unaliased_market_that_does_not_geocode_is_still_incomplete(saved_geocoder, monkeypatch):
    monkeypatch.setattr(config, "MARKET_GEOCODE_NAMES", {})
    src = snapshot_src()
    res = await mandi.nearest(dharwad(), TOMATO, src, snapshot_day(src))
    # The saved real lookup for "Ramanagara" has only Andhra Pradesh towns, so the market is not located.
    assert saved_geocoder == ["Ramanagara"]
    assert res["status"] == "incomplete" and res["markets_not_located"] == 1 and res["records"] == []


@needs_snapshot
async def test_saved_snapshot_is_served_during_the_retry_pause(keyed, monkeypatch):
    src = snapshot_src()
    cache.set(mandi.CACHE_KEY, src.data, now_local() - timedelta(hours=7), ttl_s=-1)  # expired, still saved

    async def down(url, params, **kw):
        keyed.append(params)
        raise FetchError("HTTP 502")

    monkeypatch.setattr(mandi, "get_json", down)
    first = await mandi.fetch()
    assert first.ok and first.stale and "502" in first.error
    again = await mandi.fetch()
    assert again.ok and again.stale and "failed recently" in again.error and len(keyed) == 1


@needs_snapshot
def test_prices_have_data_ids_and_pass_the_number_check(saved_geocoder, monkeypatch):
    from fastapi.testclient import TestClient

    from app import advisor, llm
    from app.main import app

    from .test_api import DHARWAD, NOW, ok

    monkeypatch.setattr(config, "DATAGOV_API_KEY", "test-key")
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    payload = snapshot()

    async def snapshot_api(url, params, **kw):
        return payload

    async def geo(q, count=10):
        return ok("geocode", [DHARWAD])

    def down(source_id):
        async def f(*a, **k):
            return SourceResult(source_id, source_id, "", status="failed", error="not used in this test")
        return f

    monkeypatch.setattr(mandi, "get_json", snapshot_api)
    monkeypatch.setattr(advisor.geocode, "search", geo)
    monkeypatch.setattr(advisor.forecast, "fetch", down("forecast"))
    monkeypatch.setattr(advisor.soil, "fetch", down("soil"))
    monkeypatch.setattr(advisor.baseline.store, "get", down("rain_baseline"))
    monkeypatch.setattr(advisor, "now_local", lambda: NOW)
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")  # rule-based answer: its numbers must all check out
    src = snapshot_src()
    word = reported_crop(src)["word"]

    body = TestClient(app).get("/api/advice", params={"q": f"What is the {word} price?", "location": "Dharwad"}).json()
    assert body["mandi"]["status"] in ("found", "latest")
    ids = {p["id"] for p in body["data_points"]}
    assert {"mandi_modal_price", "mandi_market", "mandi_distance_km", "mandi_arrival_date"} <= ids
    modal = next(p for p in body["data_points"] if p["id"] == "mandi_modal_price")
    assert modal["unit"] == "Rs/quintal" and modal["source"] == mandi.NAME and modal["fetched_at"]
    assert body["unverified_numbers"] == []
    assert f"{modal['value']:g}" in body["answer"]["text"] or any(
        f"{modal['value']:g}" in r["text"] for r in body["answer"]["recommendations"])
    mandi_row = next(s for s in body["sources"] if s["id"] == "mandi")
    assert mandi_row["status"] == "ok" and mandi_row["attribution"] == config.ATTRIBUTION["datagov"]


async def test_request_urls_with_the_key_are_never_logged(keyed, monkeypatch, caplog):
    import logging

    import httpx

    from app import http, main  # noqa: F401  (main sets the log levels)

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(502))))
    with caplog.at_level(logging.INFO):
        await mandi.fetch()
        await mandi._task
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert "test-key" not in caplog.text and "fetch api.data.gov.in" in caplog.text


# Advice path: mandi prices only for price or selling questions

@pytest.mark.parametrize("question, asks", [
    ("What is the price of jowar?", True), ("Should I sell my maize now?", True), ("ಜೋಳದ ಬೆಲೆ ಎಷ್ಟು?", True),
    ("ज्वार का भाव क्या है?", True), ("Can I spray jowar tomorrow?", False),
    ("ಇದರ ಬಗ್ಗೆ ಹೇಳಿ, ಜೋಳ ಸಿಂಪಡಿಸಬಹುದೇ?", False),  # ಇದರ holds ದರ (rate), which is why ದರ is not a price word
    ("ಈ ಮಾರ್ಗದಲ್ಲಿ ಮಳೆ ಬರುತ್ತದೆಯೇ?", False), ("marketing tips", False),
])
def test_price_questions(question, asks):
    assert crops.asks_price(question) is asks


@pytest.fixture
def advice_world(monkeypatch):
    """The advice path with saved real forecast, baseline and soil; data.gov.in calls are counted."""
    calls = []
    payload = load_fixture(SNAPSHOTS[-1].name) if SNAPSHOTS else {"records": [], "total": 0}

    async def api(url, params, **kw):
        calls.append(url)
        return payload

    monkeypatch.setattr(config, "DATAGOV_API_KEY", "test-key")
    monkeypatch.setattr(mandi, "get_json", api)
    return calls


def _advice(question, monkeypatch):
    from fastapi.testclient import TestClient

    from app import advisor, llm
    from app.main import app

    from .test_api import DHARWAD, NOW, ok
    from app.sources.forecast import parse_hourly
    from app.sources.rainfall import parse_daily
    from app.sources.soil import convert

    state = {
        "forecast": ok("forecast", {**parse_hourly(load_fixture("forecast_dharwad.json")),
                                    "daily": parse_daily(load_fixture("mtd_dharwad_2026-10.json"))}),
        "base": ok("rain_baseline", {"daily": parse_daily(load_fixture("archive_dharwad_2000_2025.json")),
                                     "district": "Dharwad district", "start_year": 2000, "end_year": 2025}),
        "soil": ok("soil", {"properties": convert(load_fixture("soil_dharwad_nearby.json")),
                            "query_lat": 15.4801, "query_lon": 75.0078, "offset_km": 2.2}),
    }

    async def geo(q, count=10):
        return ok("geocode", [DHARWAD])

    async def fc(*a, **k):
        return state["forecast"]

    async def base(*a, **k):
        return state["base"]

    async def soil(*a, **k):
        return state["soil"]

    monkeypatch.setattr(advisor.geocode, "search", geo)
    monkeypatch.setattr(advisor.forecast, "fetch", fc)
    monkeypatch.setattr(advisor.baseline.store, "get", base)
    monkeypatch.setattr(advisor.soil, "fetch", soil)
    monkeypatch.setattr(advisor, "now_local", lambda: NOW)
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    return TestClient(app).get("/api/advice", params={"q": question, "location": "Dharwad"}).json()


@needs_snapshot
def test_price_question_still_brings_prices(advice_world, monkeypatch):
    body = _advice("What is the price of jowar?", monkeypatch)
    assert body["mandi"]["status"] in ("found", "latest") and len(advice_world) == 1
    assert any(s["id"] == "mandi" for s in body["sources"])


def test_spray_question_naming_a_crop_brings_no_prices(advice_world, monkeypatch):
    body = _advice("Can I spray jowar tomorrow?", monkeypatch)
    assert body["mandi"] is None and advice_world == []
    assert not any(s["id"] == "mandi" for s in body["sources"])
    assert not any(p["id"].startswith("mandi") for p in body["data_points"])
    assert not any(r["id"] == "mandi_price" for r in body["rules"])


def test_other_advice_output_is_unchanged(advice_world, monkeypatch):
    with_crop = _advice("Can I spray jowar tomorrow?", monkeypatch)
    without = _advice("Can I spray tomorrow?", monkeypatch)
    for key in ("data_points", "rules", "spray_windows", "forecast_hourly", "forecast_daily", "water_balance",
                "heat", "fertiliser", "sources", "warnings"):
        assert with_crop[key] == without[key], key
    assert with_crop["answer"]["recommendations"] == without["answer"]["recommendations"]
