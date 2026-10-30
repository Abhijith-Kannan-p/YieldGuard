from datetime import timedelta

from app import config
from app.rules import spray
from app.sources.forecast import parse_hourly
from app.timeutil import parse_local

from .conftest import load_fixture, make_hours

CALM = (5.0, 0, 0.0)


def test_finds_window_of_min_length():
    hours = make_hours("2026-10-31T08:00", [CALM] * 3)
    res = spray.find_windows(hours, parse_local("2026-10-31T08:00"))
    assert len(res["windows"]) == 1
    w = res["windows"][0]
    assert (w["start"], w["end"], w["hours"]) == ("2026-10-31T08:00", "2026-10-31T11:00", 3)


def test_two_hour_run_is_not_a_window():
    hours = make_hours("2026-10-31T08:00", [CALM, CALM, (15.0, 0, 0.0), CALM, CALM])
    assert spray.find_windows(hours, parse_local("2026-10-31T08:00"))["windows"] == []


def test_each_threshold_breaks_a_window():
    for bad in [(config.SPRAY_MAX_WIND_KMH, 0, 0.0),          # wind at threshold is not "below"
                (5.0, config.SPRAY_MAX_PRECIP_PROB_PCT, 0.0),  # prob at threshold
                (5.0, 0, 0.2)]:                                # any rain
        hours = make_hours("2026-10-31T08:00", [CALM, CALM, bad, CALM, CALM])
        assert spray.find_windows(hours, parse_local("2026-10-31T08:00"))["windows"] == [], bad


def test_missing_value_is_not_safe():
    hours = make_hours("2026-10-31T08:00", [CALM, CALM, (None, 0, 0.0), CALM, CALM])
    assert spray.find_windows(hours, parse_local("2026-10-31T08:00"))["windows"] == []


def test_past_hours_are_ignored():
    hours = make_hours("2026-10-31T08:00", [CALM] * 6)
    res = spray.find_windows(hours, parse_local("2026-10-31T11:30"))
    assert res["windows"][0]["start"] == "2026-10-31T11:00"


def test_night_hours_excluded_when_configured(monkeypatch):
    monkeypatch.setattr(config, "SPRAY_ALLOWED_HOURS", (6, 19))
    hours = make_hours("2026-10-31T00:00", [CALM] * 5)  # 00:00-04:00
    assert spray.find_windows(hours, parse_local("2026-10-31T00:00"))["windows"] == []
    monkeypatch.setattr(config, "SPRAY_ALLOWED_HOURS", None)
    assert len(spray.find_windows(hours, parse_local("2026-10-31T00:00"))["windows"]) == 1


def test_returns_at_most_max_windows():
    rows = ([CALM] * 3 + [(20.0, 0, 0.0)]) * 5
    hours = make_hours("2026-10-31T06:00", rows)
    res = spray.find_windows(hours, parse_local("2026-10-31T06:00"))
    assert len(res["windows"]) == config.SPRAY_MAX_WINDOWS
    starts = [w["start"] for w in res["windows"]]
    assert starts == sorted(starts)


def test_real_forecast_windows_respect_thresholds():
    fc = parse_hourly(load_fixture("forecast_dharwad.json"))
    by_time = {h["time"]: h for h in fc["hours"]}
    res = spray.find_windows(fc["hours"], parse_local(fc["hours"][0]["time"]))
    assert res["hours_checked"] == len(fc["hours"])
    assert 1 <= len(res["windows"]) <= config.SPRAY_MAX_WINDOWS
    for w in res["windows"]:
        assert w["hours"] >= config.SPRAY_MIN_HOURS
        assert w["max_wind_kmh"] < config.SPRAY_MAX_WIND_KMH
        assert w["max_precip_prob_pct"] < config.SPRAY_MAX_PRECIP_PROB_PCT
        t = parse_local(w["start"])
        for _ in range(w["hours"]):
            h = by_time[t.strftime("%Y-%m-%dT%H:%M")]
            assert spray.hour_check(h)[0]
            t += timedelta(hours=1)
