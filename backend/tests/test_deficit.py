from datetime import date

from app import config
from app.rules import deficit
from app.sources.rainfall import parse_daily

from .conftest import load_fixture


def test_window_mid_month():
    assert deficit.window(date(2026, 10, 31)) == (date(2026, 10, 1), date(2026, 10, 30))


def test_window_first_of_month_uses_previous_month():
    assert deficit.window(date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert deficit.window(date(2026, 1, 1)) == (date(2025, 12, 1), date(2025, 12, 31))


def _baseline(totals_per_year: dict[int, float], month=10, days=10):
    """Spread each year's total evenly over days 1..days of `month`."""
    daily = {}
    for y, total in totals_per_year.items():
        for d in range(1, days + 1):
            daily[date(y, month, d).isoformat()] = total / days
    return daily


def _mtd(total: float, days=10):
    return {date(2026, 10, d).isoformat(): total / days for d in range(1, days + 1)}


def run(obs_total, base_totals):
    return deficit.evaluate(_mtd(obs_total), _baseline(base_totals),
                            date(2026, 10, 1), date(2026, 10, 10), 2000, 2002)


def test_drought_risk():
    res = run(20, {2000: 100, 2001: 100, 2002: 100})
    assert res["status"] == "drought_risk" and res["percent_of_normal"] == 20
    assert res["baseline_years"] == "2000-2002" and res["baseline_year_count"] == 3


def test_waterlogging_risk():
    assert run(200, {2000: 100, 2001: 100, 2002: 100})["status"] == "waterlogging_risk"


def test_normal():
    assert run(100, {2000: 80, 2001: 100, 2002: 120})["status"] == "normal"


def test_boundaries_are_exclusive():
    assert run(config.DEFICIT_DROUGHT_PCT, {2000: 100, 2001: 100, 2002: 100})["status"] == "normal"
    assert run(config.DEFICIT_WATERLOG_PCT, {2000: 100, 2001: 100, 2002: 100})["status"] == "normal"


def test_dry_season_percentage_suppressed():
    res = run(0, {2000: 1, 2001: 0, 2002: 2})
    assert res["status"] == "dry_season" and res["percent_of_normal"] is None


def test_incomplete_baseline_year_skipped():
    base = _baseline({2000: 100, 2001: 100, 2002: 40})
    base[date(2002, 10, 5).isoformat()] = None
    res = deficit.evaluate(_mtd(50), base, date(2026, 10, 1), date(2026, 10, 10), 2000, 2002)
    assert res["baseline_year_count"] == 2 and res["baseline_mm"] == 100.0


def test_missing_sources_give_unknown():
    res = deficit.evaluate(None, None, date(2026, 10, 1), date(2026, 10, 10), 2000, 2002)
    assert res["status"] == "unknown" and res["note"]


def test_feb_29_clipped_in_non_leap_years():
    base = {date(2023, 2, d).isoformat(): 1.0 for d in range(1, 29)}
    base.update({date(2024, 2, d).isoformat(): 1.0 for d in range(1, 30)})
    mean, years = deficit.baseline_mean(base, date(2028, 2, 1), date(2028, 2, 29), 2023, 2024)
    assert years == [2023, 2024] and mean == 28.5


def test_real_dharwad_october():
    mtd = parse_daily(load_fixture("mtd_dharwad_2026-10.json"))
    base = parse_daily(load_fixture("archive_dharwad_2000_2025.json"))
    res = deficit.evaluate(mtd, base, date(2026, 10, 1), date(2026, 10, 30), 2000, 2025)
    assert res["baseline_year_count"] == 26
    assert res["observed_mm"] is not None and res["baseline_mm"] > config.DEFICIT_MIN_BASELINE_MM
    assert res["status"] in {"drought_risk", "normal", "waterlogging_risk"}
    assert res["percent_of_normal"] == round(100 * res["observed_mm"] / res["baseline_mm"])
