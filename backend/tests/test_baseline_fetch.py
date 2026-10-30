"""The rainfall baseline is fetched as one small archive request per year (only the
compared month), because Open-Meteo weights calls by the length of the date range."""
import pytest

from app import config
from app.cache import FileCache
from app.sources import rainfall

DHARWAD = {"name": "Dharwad", "district": "Dharwad district", "lat": 15.46, "lon": 75.01}
HUBBALLI = {"name": "Hubballi", "district": "Dharwad district", "lat": 15.35, "lon": 75.13}


@pytest.fixture
def archive(monkeypatch):
    requests = []
    fail_years = set()

    async def fake_get_json(url, params, **kw):
        requests.append(params)
        year = int(params["start_date"][:4])
        if year in fail_years:
            raise rainfall.FetchError("HTTP 503")
        return {"daily": {"time": [params["start_date"], params["end_date"]], "precipitation_sum": [1.0, 2.0]}}

    monkeypatch.setattr(rainfall, "get_json", fake_get_json)
    return requests, fail_years


async def test_one_short_request_per_year(archive):
    requests, _ = archive
    res = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=2)
    assert res.ok and len(requests) == 26
    assert {(p["start_date"][5:], p["end_date"][5:]) for p in requests if p["start_date"][:4] == "2024"} == {
        ("02-01", "02-29")}
    assert res.data["years_fetched"] == list(range(2000, 2026)) and res.data["years_missing"] == []


async def test_some_years_missing_still_usable(archive):
    _, fail = archive
    fail.update({2003, 2010})
    res = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=10)
    assert res.ok and res.data["years_missing"] == [2003, 2010]


async def test_too_few_years_is_a_failure(archive):
    _, fail = archive
    fail.update(range(2000, 2025 - config.BASELINE_MIN_YEARS + 2))
    res = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=10)
    assert not res.ok and "HTTP 503" in res.error


async def test_built_once_per_district(archive):
    requests, _ = archive
    first = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=10)
    second = await rainfall.fetch_baseline(HUBBALLI, 2000, 2025, month=10)  # same district
    assert first.ok and not first.cached
    assert second.ok and second.cached and second.fetched_at == first.fetched_at
    assert len(requests) == 26


async def test_baseline_survives_restart(archive, tmp_path, monkeypatch):
    requests, _ = archive
    path = tmp_path / "persist.json"
    monkeypatch.setattr(rainfall, "baseline_store", FileCache(path))
    first = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=10)
    monkeypatch.setattr(rainfall, "baseline_store", FileCache(path))  # a new process reads the file
    again = await rainfall.fetch_baseline(DHARWAD, 2000, 2025, month=10)
    assert again.cached and again.fetched_at == first.fetched_at and again.data == first.data
    assert len(requests) == 26
