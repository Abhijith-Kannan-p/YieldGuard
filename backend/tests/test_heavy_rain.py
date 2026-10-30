from app import config
from app.rules import heavy_rain
from app.sources.forecast import parse_hourly
from app.timeutil import parse_local

from .conftest import load_fixture, make_hours


def test_ok_when_dry():
    hours = make_hours("2026-10-31T00:00", [(5.0, 10, 0.0)] * 24)
    res = heavy_rain.evaluate(hours, parse_local("2026-10-31T00:00"))
    assert res["status"] == "ok" and res["reasons"] == []
    assert res["hours_checked"] == 24


def test_probability_trigger():
    rows = [(5.0, 10, 0.0)] * 23 + [(5.0, config.HEAVY_RAIN_PROB_PCT + 1, 1.0)]
    res = heavy_rain.evaluate(make_hours("2026-10-31T00:00", rows), parse_local("2026-10-31T00:00"))
    assert res["status"] == "warning" and res["reasons"] == ["probability"]
    assert res["max_precip_prob_time"] == "2026-10-31T23:00"


def test_total_trigger():
    rows = [(5.0, 50, 2.0)] * 24  # 48 mm total
    res = heavy_rain.evaluate(make_hours("2026-10-31T00:00", rows), parse_local("2026-10-31T00:00"))
    assert res["reasons"] == ["total"] and res["total_precip_mm"] == 48.0


def test_only_next_24_hours_count():
    rows = [(5.0, 0, 0.0)] * 24 + [(5.0, 95, 30.0)] * 6
    res = heavy_rain.evaluate(make_hours("2026-10-31T00:00", rows), parse_local("2026-10-31T00:00"))
    assert res["status"] == "ok"


def test_unknown_when_no_data():
    res = heavy_rain.evaluate([], parse_local("2026-10-31T00:00"))
    assert res["status"] == "unknown"


def test_real_forecast_nov1_storm():
    # The saved Dharwad forecast has 87-92% rain probability on Nov 1 afternoon.
    fc = parse_hourly(load_fixture("forecast_dharwad.json"))
    res = heavy_rain.evaluate(fc["hours"], parse_local("2026-11-01T00:00"))
    assert res["status"] == "warning"
    assert "probability" in res["reasons"]
    assert res["max_precip_prob_pct"] > config.HEAVY_RAIN_PROB_PCT
