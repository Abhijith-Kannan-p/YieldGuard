"""Rainfall baseline: one archive request per district, built in the background, stored on disk."""
import asyncio
import calendar
from datetime import date

import pytest

from app import baseline, config
from app.rules import deficit
from app.sources.rainfall import parse_daily
from app.timeutil import now_local

from .conftest import load_fixture

DHARWAD = {"name": "Dharwad", "district": "Dharwad district", "lat": 15.46, "lon": 75.01}
HUBBALLI = {"name": "Hubballi", "district": "Dharwad district", "lat": 15.35, "lon": 75.13}
TODAY = date(2026, 10, 31)


def per_year_reference(payload: dict, start: date, end: date, years: range) -> float:
    """The previous method: one archive request per year for the compared month, then the
    mean of each year's total over the same calendar dates (Feb 29 clipped in non-leap years)."""
    full = parse_daily(payload)
    totals = []
    for y in years:
        last = calendar.monthrange(y, start.month)[1]
        # what a per-year request (start_date=y-MM-01, end_date=y-MM-last) would return
        month = {d: v for d, v in full.items() if f"{y}-{start.month:02d}-01" <= d <= f"{y}-{start.month:02d}-{last:02d}"}
        days = [date(y, start.month, d).isoformat() for d in range(start.day, min(end.day, last) + 1)]
        vals = [month.get(d) for d in days]
        if any(v is None for v in vals):
            continue
        totals.append(sum(vals))
    return round(sum(totals) / len(totals), 1)


@pytest.mark.parametrize("start,end", [
    (date(2026, 10, 1), date(2026, 10, 30)),   # this month to yesterday
    (date(2026, 6, 1), date(2026, 6, 15)),     # monsoon
    (date(2026, 1, 1), date(2026, 1, 31)),     # dry season
    (date(2028, 2, 1), date(2028, 2, 29)),     # leap-day window
])
def test_single_response_gives_same_baseline_as_per_year_method(start, end):
    payload = load_fixture("archive_dharwad_2000_2025.json")  # one real 2000-2025 archive response
    entry = baseline.build_entry(DHARWAD, payload, 2000, 2025, now_local())
    mean, years = deficit.baseline_mean(baseline.entry_daily(entry), start, end, 2000, 2025)
    assert mean == per_year_reference(payload, start, end, range(2000, 2026))
    assert years == list(range(2000, 2026)) and entry["years_used"] == years


@pytest.fixture
def archive(monkeypatch):
    """Fake Open-Meteo archive answering with the saved 2000-2025 response."""
    calls, state = [], {"fail": None}

    async def fake_get_json(url, params, **kw):
        calls.append(params)
        if state["fail"]:
            raise baseline.FetchError(state["fail"])
        return load_fixture("archive_dharwad_2000_2025.json")

    monkeypatch.setattr(baseline, "get_json", fake_get_json)
    monkeypatch.setattr(config, "BASELINE_BUILD_SPACING_S", 0)
    return calls, state


async def _wait_for(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.01)


async def test_missing_baseline_is_built_in_background_not_in_the_request(archive, tmp_path):
    calls, _ = archive
    store = baseline.BaselineStore(tmp_path / "b.json")
    first = await store.get(DHARWAD, TODAY)
    assert not first.ok and "not available yet" in first.error and "being built" in first.error
    assert calls == []  # the question itself sent no archive request

    await _wait_for(lambda: store.entries)
    assert len(calls) == 1 and calls[0]["start_date"] == "2000-01-01" and calls[0]["end_date"] == "2025-12-31"

    second = await store.get(HUBBALLI, TODAY)  # same district: same stored baseline
    assert second.ok and second.cached and second.data["district"] == "Dharwad district"
    assert second.data["years_used"] == list(range(2000, 2026)) and second.fetched_at is not None
    assert len(calls) == 1


async def test_baseline_file_is_loaded_at_startup(archive, tmp_path):
    calls, _ = archive
    path = tmp_path / "b.json"
    await baseline.BaselineStore(path, autostart=False).build(DHARWAD)
    restarted = baseline.BaselineStore(path)  # a new process
    restarted.load()
    res = await restarted.get(DHARWAD, TODAY)
    assert res.ok and res.data["built_at"] and len(calls) == 1


async def test_failed_build_gives_clear_message_and_waits_before_retrying(archive, tmp_path):
    calls, state = archive
    state["fail"] = "rate limit reached (HTTP 429); paused for 60 s"
    store = baseline.BaselineStore(tmp_path / "b.json")
    await store.get(DHARWAD, TODAY)
    await _wait_for(lambda: store.errors)
    res = await store.get(DHARWAD, TODAY)
    assert not res.ok and "last build failed" in res.error and "HTTP 429" in res.error
    assert "NASA POWER" in res.error  # no saved baseline, so NASA POWER was tried too, and also failed
    await asyncio.sleep(0.05)
    assert len(calls) == 2  # one archive try + one NASA POWER try; not retried before BASELINE_RETRY_AFTER_S
    assert "start_date" in calls[0] and calls[1]["parameters"] == "PRECTOTCORR"
