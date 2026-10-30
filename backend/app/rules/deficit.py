"""Rainfall deficit: month-to-date rainfall as a % of the long-run average
for the same calendar dates.

Window: 1st of this month to yesterday (today is incomplete). On the 1st of a
month there is nothing to compare yet, so the whole previous month is used.
"""
import calendar
from datetime import date, timedelta

from .. import config


def window(today: date) -> tuple[date, date]:
    if today.day == 1:
        end = today - timedelta(days=1)
        return end.replace(day=1), end
    return today.replace(day=1), today - timedelta(days=1)


def _same_dates(year: int, start: date, end: date) -> list[str]:
    """ISO dates in `year` matching start..end (same month). Feb 29 is clipped."""
    last_day = calendar.monthrange(year, start.month)[1]
    days = range(start.day, min(end.day, last_day) + 1)
    return [date(year, start.month, d).isoformat() for d in days]


def baseline_mean(daily: dict[str, float | None], start: date, end: date,
                  start_year: int, end_year: int) -> tuple[float | None, list[int]]:
    """Average of the window total over baseline years with complete data."""
    totals, years = [], []
    for y in range(start_year, end_year + 1):
        vals = [daily.get(d) for d in _same_dates(y, start, end)]
        if not vals or any(v is None for v in vals):
            continue
        totals.append(sum(vals))
        years.append(y)
    if not totals:
        return None, []
    return round(sum(totals) / len(totals), 1), years


def evaluate(mtd_daily: dict[str, float | None] | None, baseline_daily: dict[str, float | None] | None,
             start: date, end: date, start_year: int, end_year: int) -> dict:
    result = {
        "status": "unknown",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "days": (end - start).days + 1,
        "observed_mm": None,
        "observed_missing_days": None,
        "baseline_mm": None,
        "baseline_years": None,
        "baseline_year_count": 0,
        "percent_of_normal": None,
        "note": None,
        "thresholds": {
            "drought_below_pct": config.DEFICIT_DROUGHT_PCT,
            "waterlog_above_pct": config.DEFICIT_WATERLOG_PCT,
            "min_baseline_mm": config.DEFICIT_MIN_BASELINE_MM,
        },
    }

    if mtd_daily is not None:
        wanted = [(start + timedelta(days=i)).isoformat() for i in range(result["days"])]
        vals = [mtd_daily.get(d) for d in wanted]
        present = [v for v in vals if v is not None]
        result["observed_missing_days"] = len(vals) - len(present)
        if present and result["observed_missing_days"] <= 1:
            result["observed_mm"] = round(sum(present), 1)

    if baseline_daily is not None:
        mean, years = baseline_mean(baseline_daily, start, end, start_year, end_year)
        result["baseline_mm"] = mean
        result["baseline_year_count"] = len(years)
        if years:
            result["baseline_years"] = f"{years[0]}-{years[-1]}"

    obs, base = result["observed_mm"], result["baseline_mm"]
    if obs is None or base is None:
        result["note"] = "missing observed or baseline rainfall"
        return result
    if base < config.DEFICIT_MIN_BASELINE_MM:
        # Normal rainfall is near zero (dry season), so a percentage is meaningless.
        result["status"] = "dry_season"
        result["note"] = "normal rainfall for these dates is very low; percentage not meaningful"
        return result

    pct = round(100 * obs / base)
    result["percent_of_normal"] = pct
    if pct < config.DEFICIT_DROUGHT_PCT:
        result["status"] = "drought_risk"
    elif pct > config.DEFICIT_WATERLOG_PCT:
        result["status"] = "waterlogging_risk"
    else:
        result["status"] = "normal"
    return result
