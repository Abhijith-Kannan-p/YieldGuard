import httpx
import pytest

from app import http
from app.cache import TTLCache


@pytest.fixture
def transport(monkeypatch):
    """Route the shared client through a scripted handler. Returns the call log."""
    calls = []
    script = []

    def handler(request):
        calls.append(str(request.url))
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(http.asyncio, "sleep", _no_sleep)
    return calls, script


async def _no_sleep(_):
    return None


async def test_retries_once_after_timeout(transport):
    calls, script = transport
    script += [httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": 1})]
    assert await http.get_json("https://x.test/a", {}) == {"ok": 1}
    assert len(calls) == 2


async def test_gives_up_after_one_retry(transport):
    calls, script = transport
    script += [httpx.Response(503), httpx.Response(503)]
    with pytest.raises(http.FetchError, match="HTTP 503"):
        await http.get_json("https://x.test/a", {})
    assert len(calls) == 2


async def test_client_error_not_retried(transport):
    calls, script = transport
    script += [httpx.Response(400, text="bad lat")]
    with pytest.raises(http.FetchError, match="HTTP 400"):
        await http.get_json("https://x.test/a", {})
    assert len(calls) == 1


async def test_invalid_json_reported(transport):
    _, script = transport
    script += [httpx.Response(200, text="<html>"), httpx.Response(200, text="<html>")]
    with pytest.raises(http.FetchError, match="not valid JSON"):
        await http.get_json("https://x.test/a", {})


async def test_cached_fetch_keeps_original_fetch_time():
    n = {"calls": 0}

    async def loader():
        n["calls"] += 1
        return {"v": 1}

    first = await http.cached_fetch("s", "S", "u", "k1", 60, loader)
    second = await http.cached_fetch("s", "S", "u", "k1", 60, loader)
    assert n["calls"] == 1
    assert not first.cached and second.cached
    assert second.fetched_at == first.fetched_at


async def test_cached_fetch_turns_errors_into_failed_result():
    async def loader():
        raise http.FetchError("timed out after 8s")

    res = await http.cached_fetch("s", "S", "u", "k2", 60, loader)
    assert res.status == "failed" and res.error == "timed out after 8s"


async def test_cached_fetch_survives_parser_bug():
    async def loader():
        return {}["missing"]

    res = await http.cached_fetch("s", "S", "u", "k3", 60, loader)
    assert res.status == "failed" and "KeyError" in res.error


def test_ttl_expiry():
    t = {"now": 0.0}
    c = TTLCache(clock=lambda: t["now"])
    from datetime import datetime
    c.set("a", 1, datetime.now(), ttl_s=10)
    assert c.get("a").value == 1
    t["now"] = 11
    assert c.get("a") is None


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(http, "_clock", lambda: t[0])
    return t


async def test_429_backs_off_without_sending_another_request(transport, clock):
    calls, script = transport
    url = "https://api.open-meteo.com/v1/forecast"
    script += [httpx.Response(429, json={"error": True, "reason": "Minutely API request limit exceeded."})]
    with pytest.raises(http.FetchError, match="rate limit reached .*Minutely API request limit"):
        await http.get_json(url, {})
    assert len(calls) == 1  # not retried straight away

    # During the backoff no request is sent - not to the same host, nor to other Open-Meteo hosts.
    clock[0] += 59
    for u in (url, "https://archive-api.open-meteo.com/v1/archive", "https://geocoding-api.open-meteo.com/v1/search"):
        with pytest.raises(http.FetchError, match="paused"):
            await http.get_json(u, {})
    assert len(calls) == 1

    # Other providers are not affected.
    script += [httpx.Response(200, json={"soil": 1})]
    assert await http.get_json("https://rest.isric.org/soilgrids", {}) == {"soil": 1}
    assert len(calls) == 2

    # After the backoff (at least RATE_LIMIT_BACKOFF_S) requests go out again.
    clock[0] += 2
    script += [httpx.Response(200, json={"ok": 1})]
    assert await http.get_json(url, {}) == {"ok": 1}
    assert len(calls) == 3


async def test_429_honours_longer_retry_after(transport, clock):
    calls, script = transport
    url = "https://api.open-meteo.com/v1/forecast"
    script += [httpx.Response(429, headers={"Retry-After": "300"})]
    with pytest.raises(http.FetchError, match="paused for 300 s"):
        await http.get_json(url, {})
    clock[0] += 200
    with pytest.raises(http.FetchError, match="paused"):
        await http.get_json(url, {})
    assert len(calls) == 1


async def test_429_serves_cached_value_when_available(transport, clock):
    from datetime import timedelta

    from app.cache import cache
    from app.timeutil import now_local

    calls, script = transport
    url = "https://api.open-meteo.com/v1/forecast"
    fetched = now_local() - timedelta(minutes=90)
    cache.set("fc:x", {"v": 1}, fetched, ttl_s=-1)  # expired, but within STALE_MAX_AGE_S
    script += [httpx.Response(429)]

    async def load():
        return await http.get_json(url, {})

    res = await http.cached_fetch("forecast", "Forecast", url, "fc:x", 3600, load)
    assert res.ok and res.stale and res.data == {"v": 1} and res.fetched_at == fetched
    assert "429" in res.error and len(calls) == 1


async def test_open_meteo_calls_run_one_at_a_time(monkeypatch):
    import asyncio

    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={})

    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await asyncio.gather(*(http.get_json("https://archive-api.open-meteo.com/v1/archive", {"start_date": i})
                           for i in range(5)))
    assert peak == 1


async def test_concurrent_requests_for_same_key_share_one_call():
    import asyncio

    n = 0

    async def load():
        nonlocal n
        n += 1
        await asyncio.sleep(0.01)
        return {"v": n}

    a, b = await asyncio.gather(http.cached_fetch("forecast", "F", "u", "k", 60, load),
                                http.cached_fetch("forecast", "F", "u", "k", 60, load))
    assert n == 1 and a.data == b.data == {"v": 1}


async def test_refresh_failure_serves_last_good_data_marked_stale(monkeypatch):
    from datetime import timedelta

    from app.cache import cache
    from app.timeutil import now_local

    fetched = now_local() - timedelta(hours=2)
    cache.set("fc:test", {"v": 1}, fetched, ttl_s=-1)  # already expired

    async def failing():
        raise http.FetchError("rate limit reached (HTTP 429)")

    res = await http.cached_fetch("forecast", "Forecast", "u", "fc:test", 3600, failing)
    assert res.ok and res.stale and res.cached
    assert res.data == {"v": 1} and res.fetched_at == fetched
    assert "429" in res.error


async def test_stale_data_too_old_is_not_used(monkeypatch):
    from datetime import timedelta

    from app.cache import cache
    from app.timeutil import now_local

    cache.set("fc:old", {"v": 1}, now_local() - timedelta(hours=13), ttl_s=-1)

    async def failing():
        raise http.FetchError("HTTP 503")

    res = await http.cached_fetch("forecast", "Forecast", "u", "fc:old", 3600, failing)
    assert not res.ok and res.error == "HTTP 503"
