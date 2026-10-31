"""Follow-up questions reuse the data stored with the last answer (in-memory session) and never call
the weather or soil APIs again."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import advisor, baseline, config, followup, http, llm, sessions
from app.main import app
from app.sources import forecast, geocode, soil

from .test_api import NOW, live  # noqa: F401  (live is a pytest fixture: saved real responses)

ASK = {"location": "Dharwad", "q": "Can I spray today?", "lang": "en"}


@pytest.fixture
def session_client(live, monkeypatch):  # noqa: F811
    """A browser with a session that already holds one full answer; then every data source is cut off."""
    c = TestClient(app)
    r = c.get("/api/advice", params=ASK)
    assert r.status_code == 200 and config.SESSION_COOKIE in r.cookies

    calls = []

    def boom(name):
        async def f(*a, **k):
            calls.append(name)
            raise AssertionError(f"follow-up must not call {name}")
        return f

    for mod, attr in ((advisor.forecast, "fetch"), (advisor.soil, "fetch"), (advisor.geocode, "search"),
                      (forecast, "get_json"), (soil, "get_json"), (geocode, "get_json"), (baseline, "get_json"),
                      (http, "get_json")):
        monkeypatch.setattr(mod, attr, boom(f"{mod.__name__}.{attr}"))
    monkeypatch.setattr(baseline.store, "get", boom("baseline.store.get"))
    monkeypatch.setattr(followup, "now_local", lambda: NOW)
    return c, calls, r.json()


def fake_llm(monkeypatch, reply: dict):
    seen = []

    async def f(msg):
        seen.append(msg)
        return reply, "gemini-test"

    monkeypatch.setattr(llm, "followup", f)
    return seen


def test_followup_reuses_stored_data_without_weather_or_soil_calls(session_client, monkeypatch):
    c, calls, first = session_client
    point = first["data_points"][0]["id"]
    seen = fake_llm(monkeypatch, {"answer": "Wind is low this morning.", "covered": True,
                                  "why": [{"text": "From the forecast.", "evidence": [point, "rule:spray_window",
                                                                                   "made_up_id"]}],
                                  "missing_data": [], "disclaimer": "Confirm with your KVK."})
    r = c.post("/api/followup", json={"question": "What about the wind in the morning?"})
    body = r.json()
    assert r.status_code == 200, body
    assert calls == []  # no weather, soil, geocoding or baseline access at all
    assert body["covered"] is True and body["not_covered_message"] is None
    assert body["answer"]["why"][0]["evidence"] == [point, "rule:spray_window"]  # unknown ids dropped
    assert {p["id"] for p in body["evidence_points"]} == {point, "rule:spray_window"}
    assert body["data_fetched_at"] == first["forecast_hourly"]["fetched_at"]  # the original fetch time
    assert body["based_on_request_id"] == first["request_id"]
    # The model saw the stored data and the question, nothing fetched now.
    assert "<stored_data>" in seen[0] and "What about the wind" in seen[0] and point in seen[0]


def test_question_outside_the_data_returns_not_covered(session_client, monkeypatch):
    c, calls, _ = session_client
    fake_llm(monkeypatch, {"answer": "The stored data has no market prices.", "covered": False, "why": [],
                           "missing_data": ["onion prices"], "disclaimer": "Confirm with your KVK."})
    body = c.post("/api/followup", json={"question": "What is the onion price in Hubballi market?"}).json()
    assert body["covered"] is False
    assert body["not_covered_message"] == followup.NOT_COVERED["en"]
    assert body["answer"]["missing_data"] == ["onion prices"] and calls == []


def test_answer_that_cites_nothing_real_counts_as_not_covered(session_client, monkeypatch):
    c, _, _ = session_client
    fake_llm(monkeypatch, {"answer": "Use 2 kg urea per acre.", "covered": True,
                           "why": [{"text": "Common practice.", "evidence": ["general_knowledge"]}],
                           "missing_data": [], "disclaimer": "x"})
    body = c.post("/api/followup", json={"question": "How much urea should I use?"}).json()
    assert body["covered"] is False and body["not_covered_message"] == followup.NOT_COVERED["en"]


def test_not_covered_message_follows_the_question_language(session_client, monkeypatch):
    c, _, _ = session_client
    fake_llm(monkeypatch, {"answer": "ಮಾಹಿತಿ ಇಲ್ಲ.", "covered": False, "why": [], "missing_data": [], "disclaimer": "x"})
    body = c.post("/api/followup", json={"question": "ಈರುಳ್ಳಿ ಬೆಲೆ ಎಷ್ಟು?"}).json()
    assert body["language"] == "kn" and body["not_covered_message"] == followup.NOT_COVERED["kn"]


def test_ten_followups_per_30_minutes(session_client, monkeypatch):
    c, _, _ = session_client
    fake_llm(monkeypatch, {"answer": "ok", "covered": False, "why": [], "missing_data": [], "disclaimer": "x"})
    t = [5000.0]
    monkeypatch.setattr(sessions, "_clock", lambda: t[0])
    for i in range(config.FOLLOWUP_LIMIT):
        t[0] += 60
        assert c.post("/api/followup", json={"question": f"q{i}"}).status_code == 200
    r = c.post("/api/followup", json={"question": "one more"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "followup_limit"
    assert "10 follow-up questions" in r.json()["error"]["message"]
    t[0] += 21 * 60  # the first follow-up leaves the 30-minute window (session itself stays alive)
    assert c.post("/api/followup", json={"question": "later"}).status_code == 200


def test_stored_data_older_than_60_minutes_asks_for_refresh(session_client, monkeypatch):
    c, calls, first = session_client
    seen = fake_llm(monkeypatch, {"answer": "x", "covered": True, "why": [], "missing_data": [], "disclaimer": "x"})
    fetched = advisor.parse_local(first["forecast_hourly"]["fetched_at"][:16])
    monkeypatch.setattr(followup, "now_local", lambda: fetched + timedelta(minutes=61))
    r = c.post("/api/followup", json={"question": "And tomorrow?"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "data_stale"
    assert "61 minutes" in r.json()["error"]["message"] and seen == [] and calls == []


def test_no_session_or_expired_session(session_client, monkeypatch):
    c, _, _ = session_client
    fresh = TestClient(app)
    r = fresh.post("/api/followup", json={"question": "spray?"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_session"

    t = [10_000.0]
    monkeypatch.setattr(sessions, "_clock", lambda: t[0])
    c.post("/api/followup", json={"question": "touch"})  # may fail on the LLM; it only refreshes last_used
    t[0] += config.SESSION_TTL_S + 1
    r = c.post("/api/followup", json={"question": "still there?"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_session"


def test_session_cookie_is_http_only(live):  # noqa: F811
    r = TestClient(app).get("/api/advice", params=ASK)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and f"max-age={config.SESSION_TTL_S}" in cookie
