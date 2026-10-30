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
