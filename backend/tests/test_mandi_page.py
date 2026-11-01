"""The Mandi page endpoints (/api/mandi/crops, /api/mandi), from saved real responses: the data.gov.in
snapshot of 1 Nov 2026, a real empty response, and real Open-Meteo geocoding for Dharwad and the markets."""
from collections import defaultdict
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, mandi_page
from app.http import FetchError, SourceResult
from app.main import app
from app.sources import geocode, mandi
from app.timeutil import TZ

from .conftest import load_fixture

SNAPSHOT = "mandi_karnataka_2026-11-01.json"
client = TestClient(app)


def at(day: str, hour: int = 10) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=TZ)


@pytest.fixture
def world(monkeypatch):
    """data.gov.in answers with a saved response (state["payload"]); places come from saved geocoding."""
    state = {"payload": load_fixture(SNAPSHOT), "calls": 0}
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "test-key")

    async def api(url, params, **kw):
        state["calls"] += 1
        if isinstance(state["payload"], Exception):
            raise state["payload"]
        return state["payload"]

    saved = {**load_fixture("mandi_geocode.json")["by_query"], "Dharwad": load_fixture("geocode_dharwad.json")}

    async def search(q, count=10):
        resp = saved.get(q)
        if resp is None:
            return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, status="failed", error="no saved response")
        places = [p.__dict__ for p in geocode.pick_karnataka(resp.get("results") or [])]
        return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, data=places, fetched_at=at("2026-11-01", 9))

    monkeypatch.setattr(mandi, "get_json", api)
    monkeypatch.setattr(geocode, "search", search)  # the same module serves advisor.resolve_location
    monkeypatch.setattr(mandi_page, "now_local", lambda: at("2026-11-01"))
    return state


def saved_place(query: str) -> dict:
    return geocode.pick_karnataka(load_fixture("mandi_geocode.json")["by_query"][query]["results"])[0].__dict__


def get(**params):
    return client.get("/api/mandi", params=params)


# Crop list

def test_crop_list_is_built_from_the_snapshot(world):
    body = client.get("/api/mandi/crops").json()
    records = load_fixture(SNAPSHOT)["records"]
    assert body["status"] == "ok" and body["snapshot_date"] == "2026-11-01" and body["today"] == "2026-11-01"
    assert [c["commodity"] for c in body["crops"]] == sorted({r["commodity"] for r in records}, key=str.lower)
    by = {c["commodity"]: c for c in body["crops"]}
    assert by["Jowar(Sorghum)"]["labels"] == {"en": "Jowar(Sorghum)", "hi": "ज्वार", "kn": "ಜೋಳ"}
    assert by["Maize"]["labels"]["kn"] == "ಮೆಕ್ಕೆಜೋಳ"
    assert by["Beans"]["crop"] is None and by["Beans"]["labels"] == {"en": "Beans", "hi": "Beans", "kn": "Beans"}
    assert by["Brinjal"]["varieties"] == ["Brinjal", "Round"]
    src = body["source"]
    assert src["id"] == "mandi" and src["status"] == "ok" and not src["cached"] and src["fetched_at"]


def test_crop_list_second_call_is_cached(world):
    client.get("/api/mandi/crops")
    body = client.get("/api/mandi/crops").json()
    assert body["source"]["cached"] and world["calls"] == 1


def test_names_sharing_an_alias_are_told_apart(world, monkeypatch):
    aliases = {k: dict(v) for k, v in config.CROP_ALIASES.items()}
    aliases["paddy"]["commodity"] = ["paddy", "maize"]  # two real names in the snapshot now share one alias
    del aliases["maize"]
    monkeypatch.setattr(config, "CROP_ALIASES", aliases)
    by = {c["commodity"]: c for c in client.get("/api/mandi/crops").json()["crops"]}
    assert by["Paddy(Common)"]["labels"]["hi"] == "धान (Paddy(Common))"
    assert by["Maize"]["labels"]["kn"] == "ಭತ್ತ (Maize)"
    assert by["Maize"]["varieties"] == ["Local"] and by["Paddy(Common)"]["varieties"] == ["Paddy"]


def test_crop_list_empty_response_is_no_data(world):
    world["payload"] = load_fixture("mandi_empty.json")
    body = client.get("/api/mandi/crops").json()
    assert body["status"] == "no_data" and body["crops"] == [] and body["source"]["status"] == "ok"


def test_crop_list_api_down_is_unavailable(world):
    world["payload"] = FetchError("HTTP 502")
    body = client.get("/api/mandi/crops").json()
    assert body["status"] == "unavailable" and body["crops"] == []
    assert body["source"]["status"] == "failed" and "502" in body["source"]["error"]


# Prices

def test_nearest_market_found_today(world):
    p = saved_place("Ranebennur")
    body = get(crop="Jowar(Sorghum)", lat=p["lat"], lon=p["lon"]).json()
    assert body["status"] == "found" and body["commodity"] == "Jowar(Sorghum)"
    assert body["labels"]["kn"] == "ಜೋಳ"
    m, r = body["market"], body["records"][0]
    assert m["name"] == "Ranebennur APMC" and m["district"] == "Haveri" and m["distance_km"] == 0.0
    raw = next(x for x in load_fixture(SNAPSHOT)["records"] if x["commodity"] == "Jowar(Sorghum)")
    assert (r["modal_price"], r["min_price"], r["max_price"]) == (
        float(raw["modal_price"]), float(raw["min_price"]), float(raw["max_price"]))
    assert r["variety"] == raw["variety"] and r["arrival_date"] == "2026-11-01"
    assert body["nearby"] == []  # no other market reports jowar in this snapshot
    assert body["source"]["status"] == "ok" and body["source"]["fetched_at"]


def test_by_place_name(world):
    body = get(crop="Ground Nut Seed", location="Dharwad").json()
    assert body["location"]["name"] == "Dharwad" and body["status"] == "found"
    assert body["market"]["name"] == "Ranebennur APMC" and body["market"]["distance_km"] <= config.MANDI_MAX_DISTANCE_KM


def test_nearby_markets_are_listed_nearest_first(world, monkeypatch):
    records = load_fixture(SNAPSHOT)["records"]
    markets = defaultdict(set)
    for r in records:
        markets[r["commodity"]].add(r["market"])
    shared = [c for c, ms in markets.items() if len(ms) > 1]
    if not shared:
        pytest.skip("the saved snapshot has no commodity reported by two markets; recapture on a weekday")
    monkeypatch.setattr(config, "MANDI_MAX_DISTANCE_KM", 10_000)
    body = get(crop=shared[0], location="Dharwad").json()
    kms = [body["market"]["distance_km"]] + [n["distance_km"] for n in body["nearby"]]
    assert kms == sorted(kms) and body["market"]["name"] not in [n["market"] for n in body["nearby"]]
    assert all(n["records"] and n["records"][0]["modal_price"] > 0 for n in body["nearby"])


def test_no_nearby_market_gives_no_price(world):
    body = get(crop="Tomato", location="Dharwad").json()
    assert body["status"] == "no_nearby_market" and body["records"] == [] and body["nearby"] == []
    assert body["market"] is None and body["nearest_beyond"]["market"] == "Ramanagara APMC"
    assert body["nearest_beyond"]["distance_km"] > config.MANDI_MAX_DISTANCE_KM


def test_older_arrival_date_is_latest_not_today(world, monkeypatch):
    monkeypatch.setattr(mandi_page, "now_local", lambda: at("2026-11-01") + timedelta(days=1))
    p = saved_place("Ranebennur")
    body = get(crop="Onion", lat=p["lat"], lon=p["lon"]).json()
    assert body["status"] == "latest" and body["today"] == "2026-11-02"
    assert body["records"][0]["arrival_date"] == "2026-11-01" == body["snapshot_date"]


def test_crop_not_in_snapshot_is_no_market(world):
    body = get(crop="No Such Commodity", location="Dharwad").json()
    assert body["status"] == "no_market" and body["records"] == []
    assert body["labels"] == {"en": "No Such Commodity", "hi": "No Such Commodity", "kn": "No Such Commodity"}


def test_empty_response_is_no_data(world):
    world["payload"] = load_fixture("mandi_empty.json")
    body = get(crop="Tomato", location="Dharwad").json()
    assert body["status"] == "no_data" and body["records"] == []


def test_api_down_is_unknown_with_failed_source(world):
    world["payload"] = FetchError("HTTP 502")
    body = get(crop="Tomato", location="Dharwad").json()
    assert body["status"] == "unknown" and body["source"]["status"] == "failed"


def test_place_outside_karnataka_is_rejected(world):
    r = get(crop="Tomato", lat=19.07, lon=72.88)
    assert r.status_code == 422 and r.json()["error"]["code"] == "outside_region"


def test_crop_is_required(world):
    assert get(location="Dharwad").status_code == 422
