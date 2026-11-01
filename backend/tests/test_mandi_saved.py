"""Mandi saved copy from the GitHub "data" branch, used when the live data.gov.in call fails.

GitHub and data.gov.in are served from saved real responses: the contents listing, the published
2026-11-01.json, GitHub's 404 body, and data.gov.in's real empty response (as an "empty file").
index.json is made by the real write_index() from the real file, as the publish script does.
"""
import json
import logging
import shutil
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, mandi_page
from app.cache import cache
from app.http import SourceResult
from app.main import app
from app.sources import geocode, mandi
from app.timeutil import TZ
from devtools import fetch_mandi_snapshot

from .conftest import FIXTURES, load_fixture

KEY = "f" * 56
FILE = "github_mandi_2026-11-01.json"
NOW = datetime(2026, 11, 1, 20, 0, tzinfo=TZ)


def real_index(tmp_path) -> dict:
    shutil.copy(FIXTURES / FILE, tmp_path / "2026-11-01.json")
    fetch_mandi_snapshot.write_index(tmp_path)
    return json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))


@pytest.fixture
def world(monkeypatch):
    """data.gov.in answers state["live"]; GitHub answers from saved responses; calls are counted by kind."""
    monkeypatch.setattr(config, "DATAGOV_API_KEY", KEY)
    monkeypatch.setattr(config, "MANDI_SAVED_REPO", "Abhijith-Kannan-p/YieldGuard")
    monkeypatch.setattr(mandi, "now_local", lambda: NOW)
    state = {"live": httpx.Response(502), "index": httpx.Response(404, text=(FIXTURES / "github_raw_404.txt").read_text()),
             "listing": httpx.Response(200, json=load_fixture("github_mandi_contents.json")),
             "file": httpx.Response(200, text=(FIXTURES / FILE).read_text(encoding="utf-8")),
             "calls": {"live": 0, "index": 0, "listing": 0, "file": 0}}

    def answer(kind):
        state["calls"][kind] += 1
        a = state[kind]
        if isinstance(a, Exception):
            raise a
        return a

    def handler(request: httpx.Request):
        host, path = request.url.host, request.url.path
        if host == "api.data.gov.in":
            return answer("live")
        if host == "api.github.com" and path.endswith("/contents/data/mandi"):
            assert request.url.params["ref"] == "data"
            return answer("listing")
        if host == "raw.githubusercontent.com" and path == "/Abhijith-Kannan-p/YieldGuard/data/data/mandi/index.json":
            return answer("index")
        if host == "raw.githubusercontent.com" and path == "/Abhijith-Kannan-p/YieldGuard/data/data/mandi/2026-11-01.json":
            return answer("file")
        return httpx.Response(404)

    from app import http
    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_sleep)
    return state


def saved_fetched_at() -> datetime:
    return datetime.fromisoformat(json.loads((FIXTURES / FILE).read_text(encoding="utf-8"))["fetched_at"])


async def test_live_fails_and_the_data_branch_copy_is_used(world):
    res = await mandi.fetch()
    assert res.ok and res.stale and res.cached and res.meta["saved_copy"] == "data branch"
    assert res.name == "Agmarknet mandi prices (data.gov.in), saved copy from the YieldGuard data branch"
    assert res.fetched_at == saved_fetched_at()  # the file's own fetch time
    assert res.url.endswith("/data/data/mandi/2026-11-01.json") and KEY not in res.url
    assert res.error.startswith("data.gov.in failed (HTTP 502)")
    assert "showing the copy fetched 1 Nov 2026, 19:28 IST from the YieldGuard data branch" in res.error
    assert len(res.data["records"]) == 31 and res.data["snapshot_date"] == "2026-11-01"
    assert world["calls"]["index"] == 1 and world["calls"]["listing"] == 1  # no index yet: contents API used


async def test_index_is_used_when_present(world, tmp_path):
    world["index"] = httpx.Response(200, json=real_index(tmp_path))
    res = await mandi.fetch()
    assert res.ok and res.meta["saved_copy"] == "data branch" and world["calls"]["listing"] == 0


@pytest.mark.parametrize("live, cause", [
    (httpx.ConnectError("refused"), "network error (ConnectError)"),
    (httpx.ReadTimeout("slow"), "timed out after 30s"),
    (httpx.Response(403, json={"error": "Key not authorised"}), "HTTP 403"),
])
async def test_any_live_failure_falls_back(world, live, cause):
    world["live"] = live
    res = await mandi.fetch()
    assert res.ok and res.meta["saved_copy"] == "data branch" and cause in res.error


async def test_missing_key_uses_the_saved_copy_without_calling_data_gov_in(world, monkeypatch):
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "")
    res = await mandi.fetch()
    assert res.ok and res.meta["saved_copy"] == "data branch" and world["calls"]["live"] == 0
    assert "DATAGOV_API_KEY is not set" in res.error


async def test_live_first_github_untouched(world):
    world["live"] = httpx.Response(200, json=load_fixture("mandi_karnataka_2026-11-01.json"))
    res = await mandi.fetch()
    assert res.ok and not res.stale and res.name == mandi.NAME
    assert world["calls"]["index"] == world["calls"]["listing"] == world["calls"]["file"] == 0


async def test_both_fail_is_unavailable_with_both_causes(world):
    world["listing"] = httpx.Response(403)  # e.g. GitHub's rate limit for unauthenticated calls
    res = await mandi.fetch()
    assert not res.ok and res.error.startswith("data.gov.in failed (HTTP 502); saved copy unavailable (HTTP 403")


async def test_empty_saved_file_is_ignored(world):
    world["file"] = httpx.Response(200, json=load_fixture("mandi_empty.json"))
    res = await mandi.fetch()
    assert not res.ok and "saved snapshot 2026-11-01.json has no usable records" in res.error


async def test_invalid_saved_file_is_ignored(world):
    world["file"] = httpx.Response(200, text=(FIXTURES / "github_raw_404.txt").read_text())
    res = await mandi.fetch()
    assert not res.ok and "saved copy unavailable (response was not valid JSON)" in res.error


async def test_copy_older_than_the_limit_is_unavailable(world, monkeypatch):
    monkeypatch.setattr(mandi, "now_local", lambda: NOW + timedelta(days=8))
    res = await mandi.fetch()
    assert not res.ok and "latest arrival date 2026-11-01 is more than 7 days old" in res.error


async def test_saved_copy_is_cached_and_retries_pause(world):
    await mandi.fetch()
    calls = dict(world["calls"])
    again = await mandi.fetch()
    assert again.ok and world["calls"] == calls  # live is pausing and GitHub is cached: no new request


async def test_saved_copy_failure_pauses_github_too(world):
    world["file"] = httpx.Response(503)
    await mandi.fetch()
    calls = dict(world["calls"])
    res = await mandi.fetch()
    assert not res.ok and "failed recently" in res.error and world["calls"] == calls


def _memory_copy(at: datetime):
    """The real snapshot as an expired in-memory copy fetched at `at`."""
    payload = load_fixture("mandi_karnataka_2026-11-01.json")
    cache.set(mandi.CACHE_KEY, mandi.parse(payload["records"], int(payload["total"])), at, ttl_s=-1)


@pytest.mark.parametrize("offset_min, used", [(+5, "memory"), (-5, "data branch"), (0, "memory")])
async def test_newer_copy_wins_and_a_tie_keeps_memory(world, offset_min, used):
    _memory_copy(saved_fetched_at() + timedelta(minutes=offset_min))
    res = await mandi.fetch()
    assert res.ok and res.meta["saved_copy"] == used
    label = "this server's memory" if used == "memory" else "the YieldGuard data branch"
    assert res.name.endswith(f"saved copy from {label}")


async def test_key_never_logged(world, caplog):
    import app.main  # noqa: F401  (sets the httpx log level)
    with caplog.at_level(logging.INFO):
        await mandi.fetch()
    assert KEY not in caplog.text and "fetch raw.githubusercontent.com" in caplog.text


def test_endpoints_and_advice_work_from_the_saved_copy(world, monkeypatch):
    from app import advisor, llm

    saved_geo = {**load_fixture("mandi_geocode.json")["by_query"], "Dharwad": load_fixture("geocode_dharwad.json")}

    async def search(q, count=10):
        resp = saved_geo.get(q)
        if resp is None:
            return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, status="failed", error="no saved response")
        places = [p.__dict__ for p in geocode.pick_karnataka(resp.get("results") or [])]
        return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, data=places, fetched_at=NOW)

    def down(source_id):
        async def f(*a, **k):
            return SourceResult(source_id, source_id, "", status="failed", error="not used in this test")
        return f

    monkeypatch.setattr(geocode, "search", search)
    monkeypatch.setattr(mandi_page, "now_local", lambda: NOW + timedelta(days=1))  # one day after the arrival date
    monkeypatch.setattr(advisor, "now_local", lambda: NOW + timedelta(days=1))
    monkeypatch.setattr(advisor.forecast, "fetch", down("forecast"))
    monkeypatch.setattr(advisor.soil, "fetch", down("soil"))
    monkeypatch.setattr(advisor.baseline.store, "get", down("rain_baseline"))
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    c = TestClient(app)

    crops = c.get("/api/mandi/crops").json()
    assert crops["status"] == "ok" and len(crops["crops"]) == 30
    assert crops["source"]["status"] == "ok" and crops["source"]["stale"] and "data branch" in crops["source"]["name"]

    page = c.get("/api/mandi", params={"crop": "Maize", "location": "Dharwad"}).json()
    assert page["status"] == "latest" and page["records"][0]["arrival_date"] == "2026-11-01"
    assert page["source"]["note"].startswith("data.gov.in failed recently")  # second request: live is pausing

    body = c.get("/api/advice", params={"q": "What is the maize price?", "location": "Dharwad"}).json()
    assert body["mandi"]["status"] == "latest"
    row = next(s for s in body["sources"] if s["id"] == "mandi")
    assert row["status"] == "ok" and row["stale"] and row["name"].endswith("saved copy from the YieldGuard data branch")
    rule = next(r for r in body["rules"] if r["id"] == "mandi_price")
    assert "latest available: 2026-11-01" in rule["summary"] and "today" not in rule["summary"].lower()
    assert any("live refresh failed" in w and "data.gov.in failed" in w for w in body["warnings"])
    assert body["unverified_numbers"] == []
