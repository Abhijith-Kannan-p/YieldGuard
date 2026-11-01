"""devtools/fetch_mandi_snapshot.py: file naming from the saved real snapshot, keeping unchanged files,
and writing nothing (non-zero exit, short cause only) on empty or failed responses."""
import json
import socket
import ssl

import httpx
import pytest

from app import config
from devtools import fetch_mandi_snapshot as snap

from .conftest import load_fixture

SNAPSHOT = "mandi_karnataka_2026-11-01.json"
KEY = "f" * 56  # placeholder: the shape of a data.gov.in key, never a real one
URL_WITH_KEY = f"https://api.data.gov.in/resource/x?api-key={KEY}"


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(config, "DATAGOV_API_KEY", KEY)
    monkeypatch.setattr(snap, "RETRY_PAUSE_S", 0)


def serve(answer):
    """A transport answering every request with `answer(request)`; requests are counted."""
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return answer(request)

    return httpx.MockTransport(handler), calls


def run(tmp_path, answer, capsys):
    transport, calls = serve(answer)
    code = snap.main(transport=transport, out_dir=tmp_path)
    out = capsys.readouterr()
    return code, calls, out.out + out.err


def test_saves_the_raw_snapshot_named_by_its_newest_arrival_date(tmp_path, capsys):
    payload = load_fixture(SNAPSHOT)
    code, calls, printed = run(tmp_path, lambda r: httpx.Response(200, json=payload), capsys)
    assert code == 0 and [p.name for p in tmp_path.iterdir()] == ["2026-11-01.json"]
    doc = json.loads((tmp_path / "2026-11-01.json").read_text(encoding="utf-8"))
    assert set(doc) == {"source", "fetched_at", "total", "records"}
    assert doc["records"] == payload["records"] and doc["total"] == int(payload["total"])
    assert doc["source"] == "Agmarknet mandi prices (data.gov.in)" and doc["fetched_at"].endswith("+05:30")
    req = calls[0]
    assert req.headers["user-agent"] == config.MANDI_HEADERS["User-Agent"]
    assert req.url.params["filters[state.keyword]"] == "Karnataka" and req.url.params["offset"] == "0"
    assert KEY not in (tmp_path / "2026-11-01.json").read_text(encoding="utf-8") and KEY not in printed
    assert "written: 2026-11-01.json" in printed


def test_date_selection_uses_the_record_parser():
    payload = load_fixture(SNAPSHOT)
    name, doc = snap.build(payload["records"], int(payload["total"]), snap.now_local())
    dates = sorted({"-".join(reversed(r["arrival_date"].split("/"))) for r in payload["records"]})
    assert name == f"{dates[-1]}.json" == "2026-11-01.json"


def test_unchanged_snapshot_keeps_the_existing_file(tmp_path, capsys):
    payload = load_fixture(SNAPSHOT)
    run(tmp_path, lambda r: httpx.Response(200, json=payload), capsys)
    first = (tmp_path / "2026-11-01.json").read_text(encoding="utf-8")
    code, _, printed = run(tmp_path, lambda r: httpx.Response(200, json=payload), capsys)
    assert code == 0 and "unchanged: 2026-11-01.json" in printed
    assert (tmp_path / "2026-11-01.json").read_text(encoding="utf-8") == first  # fetched_at kept too


def test_empty_response_writes_nothing(tmp_path, capsys):
    code, _, printed = run(tmp_path, lambda r: httpx.Response(200, json=load_fixture("mandi_empty.json")), capsys)
    assert code == 1 and list(tmp_path.iterdir()) == [] and "failed: no records" in printed


def test_4xx_is_not_retried(tmp_path, capsys):
    code, calls, printed = run(tmp_path, lambda r: httpx.Response(403, json={"error": "Key not authorised"}), capsys)
    assert code == 1 and len(calls) == 1 and printed.strip() == "failed: HTTP 403"
    assert list(tmp_path.iterdir()) == []


def test_5xx_is_retried_once(tmp_path, capsys):
    code, calls, printed = run(tmp_path, lambda r: httpx.Response(502), capsys)
    assert code == 1 and len(calls) == 2 and printed.strip() == "failed: HTTP 502"
    assert list(tmp_path.iterdir()) == []


def test_5xx_then_success_saves(tmp_path, capsys):
    answers = iter([httpx.Response(503), httpx.Response(200, json=load_fixture(SNAPSHOT))])
    code, calls, _ = run(tmp_path, lambda r: next(answers), capsys)
    assert code == 0 and len(calls) == 2 and (tmp_path / "2026-11-01.json").exists()


def _raise(exc_type, inner):
    """httpx raises its errors from the underlying OS or SSL error; the message holds the URL with the key."""
    def answer(request):
        try:
            raise inner
        except BaseException as e:
            raise exc_type(f"failed for {URL_WITH_KEY}", request=request) from e
    return answer


@pytest.mark.parametrize("exc_type, inner, word", [
    (httpx.ReadTimeout, TimeoutError("read timed out"), "timeout"),
    (httpx.ConnectError, ConnectionRefusedError(111, "Connection refused"), "refused"),
    (httpx.ConnectError, socket.gaierror(-2, "Name or service not known"), "DNS"),
    (httpx.ConnectError, ssl.SSLError(1, "certificate verify failed"), "TLS"),
])
def test_network_failures_print_only_a_short_cause(tmp_path, capsys, exc_type, inner, word):
    code, calls, printed = run(tmp_path, _raise(exc_type, inner), capsys)
    assert code == 1 and len(calls) == 2  # one retry
    assert printed.strip() == f"failed: {word}"
    assert KEY not in printed and "api.data.gov.in" not in printed and list(tmp_path.iterdir()) == []


def test_missing_key_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "DATAGOV_API_KEY", "")
    code, calls, printed = run(tmp_path, lambda r: httpx.Response(200, json=load_fixture(SNAPSHOT)), capsys)
    assert code == 1 and calls == [] and "DATAGOV_API_KEY is not set" in printed and list(tmp_path.iterdir()) == []
