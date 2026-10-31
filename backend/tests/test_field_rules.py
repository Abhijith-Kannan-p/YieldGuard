"""Irrigation water balance, heat-stress flag and fertiliser timing, checked against a saved real
Open-Meteo response (tests/fixtures/forecast_full_dharwad.json, see manifest.json)."""
import copy
import json
from datetime import datetime

import pytest

from app import config
from app.rules import fertiliser, heat, irrigation
from app.sources.forecast import parse_daily_vars, parse_hourly

from .conftest import FIXTURES, load_fixture

PAYLOAD = load_fixture("forecast_full_dharwad.json")
CAPTURED = datetime.fromisoformat(
    json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["forecast_full_dharwad.json"]["captured_at"])
TODAY = CAPTURED.date().isoformat()


def next_days(payload=PAYLOAD):
    return [d for d in parse_daily_vars(payload) if d["date"] >= TODAY]


# ---- water balance -------------------------------------------------------

def test_water_balance_matches_hand_calculation_on_real_forecast():
    days = next_days()
    res = irrigation.plan(days)
    assert len(res["days"]) == config.FORECAST_DAILY_DAYS and res["days"][0]["date"] == TODAY

    deficit, first_over = 0.0, None
    for d, row in zip(days, res["days"]):
        use = round(d["et0_fao_evapotranspiration"] * config.CROP_FACTOR, 1)
        deficit = round(max(0.0, deficit + use - d["precipitation_sum"]), 1)
        assert row["crop_use_mm"] == use and row["rain_mm"] == d["precipitation_sum"] and row["deficit_mm"] == deficit
        if deficit > config.IRRIGATION_DEFICIT_MM and first_over is None:
            first_over = d["date"]
    assert res["irrigate_on"] == first_over
    assert res["status"] == ("irrigate" if first_over else "ok")


def test_irrigation_suggested_on_first_day_over_threshold(monkeypatch):
    monkeypatch.setattr(config, "CROP_FACTOR", 1.0)
    monkeypatch.setattr(config, "IRRIGATION_DEFICIT_MM", 10.0)
    days = [{"date": f"2026-11-0{i}", "et0_fao_evapotranspiration": 4.0, "precipitation_sum": 0.0} for i in range(1, 8)]
    days[1]["precipitation_sum"] = 9.0  # rain on day 2 refills: 4 + 4 - 9 -> 0 (never below 0)
    res = irrigation.plan(days)
    assert [r["deficit_mm"] for r in res["days"]] == [4.0, 0.0, 4.0, 8.0, 12.0, 16.0, 20.0]
    assert res["irrigate_on"] == "2026-11-05" and res["status"] == "irrigate"


def test_water_balance_stops_at_missing_data():
    days = copy.deepcopy(next_days())
    days[3]["et0_fao_evapotranspiration"] = None
    res = irrigation.plan(days)
    assert len(res["days"]) == 3 and res["incomplete_from"] == days[3]["date"]
    assert irrigation.plan([])["status"] == "unknown"


# ---- heat stress ---------------------------------------------------------

def test_heat_on_real_forecast_reports_hottest_day():
    days = next_days()
    res = heat.evaluate(days)
    hottest = max(days[: config.FORECAST_DAILY_DAYS], key=lambda d: d["temperature_2m_max"])
    assert res["max_tmax_c"] == hottest["temperature_2m_max"] and res["max_tmax_date"] == hottest["date"]
    expected_hot = [d["date"] for d in days[: config.FORECAST_DAILY_DAYS] if d["temperature_2m_max"] > config.HEAT_THRESHOLD_C]
    assert [d["date"] for d in res["hot_days"]] == expected_hot
    assert res["status"] == ("warning" if expected_hot else "ok")


def test_heat_flags_each_day_above_threshold_with_its_date():
    days = copy.deepcopy(next_days())
    days[2]["temperature_2m_max"] = config.HEAT_THRESHOLD_C + 1.5
    days[5]["temperature_2m_max"] = config.HEAT_THRESHOLD_C  # equal is not above
    res = heat.evaluate(days)
    assert res["status"] == "warning"
    assert res["hot_days"] == [{"date": days[2]["date"], "tmax_c": config.HEAT_THRESHOLD_C + 1.5}]


# ---- fertiliser timing ---------------------------------------------------

def _hours(payload=PAYLOAD):
    return parse_hourly(payload)["hours"]


def test_fertiliser_on_real_forecast_follows_the_48h_thresholds():
    hours = _hours()
    res = fertiliser.evaluate(hours, CAPTURED)
    window = [h for h in hours if CAPTURED.replace(minute=0, second=0, microsecond=0).isoformat()[:16] <= h["time"]]
    window = window[: config.FERTILISER_LOOKAHEAD_H]
    max_prob = max(h["precipitation_probability"] for h in window)
    total = round(sum(h["precipitation"] for h in window), 1)
    assert res["max_precip_prob_pct"] == max_prob and res["total_precip_mm"] == total
    expect_delay = max_prob > config.FERTILISER_RAIN_PROB_PCT or total > config.FERTILISER_RAIN_TOTAL_MM
    assert res["status"] == ("delay" if expect_delay else "ok")


@pytest.mark.parametrize("prob,mm,expected", [
    (10, 0.0, "ok"),
    (config.FERTILISER_RAIN_PROB_PCT + 1, 0.0, "delay"),   # probability alone
    (10, 2.0, "delay"),                                     # 48 h total 48 x 2 = 96 mm alone
    (config.FERTILISER_RAIN_PROB_PCT, 0.0, "ok"),          # equal is not above
])
def test_fertiliser_thresholds(prob, mm, expected):
    payload = copy.deepcopy(PAYLOAD)
    n = len(payload["hourly"]["time"])
    payload["hourly"]["precipitation_probability"] = [prob] * n
    payload["hourly"]["precipitation"] = [mm] * n
    assert fertiliser.evaluate(_hours(payload), CAPTURED)["status"] == expected
