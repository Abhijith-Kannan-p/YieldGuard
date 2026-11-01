"""Dry days for harvest and transport (an estimate, not a harvest recommendation): forecast days in the next
FORECAST_DAILY_DAYS days with rain at most DRY_DAY_MAX_RAIN_MM and a daily maximum below HEAT_THRESHOLD_C.
Days missing either value are not counted."""
from .. import config


def evaluate(days: list[dict]) -> dict:
    checked = [d for d in days[: config.FORECAST_DAILY_DAYS]
               if d.get("precipitation_sum") is not None and d.get("temperature_2m_max") is not None]
    dry = [{"date": d["date"], "rain_mm": d["precipitation_sum"], "tmax_c": d["temperature_2m_max"]} for d in checked
           if d["precipitation_sum"] <= config.DRY_DAY_MAX_RAIN_MM and d["temperature_2m_max"] < config.HEAT_THRESHOLD_C]
    return {
        "status": "unknown" if not checked else ("found" if dry else "none"),
        "dry_days": dry,
        "days_checked": len(checked),
        "first_date": checked[0]["date"] if checked else None,
        "last_date": checked[-1]["date"] if checked else None,
        "thresholds": {"max_rain_mm": config.DRY_DAY_MAX_RAIN_MM, "tmax_below_c": config.HEAT_THRESHOLD_C,
                       "days": config.FORECAST_DAILY_DAYS},
    }
