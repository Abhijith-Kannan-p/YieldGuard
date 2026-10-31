"""Heat-stress alert: any day in the next FORECAST_DAILY_DAYS days whose daily maximum
temperature (temperature_2m_max) is above HEAT_THRESHOLD_C."""
from .. import config


def evaluate(days: list[dict]) -> dict:
    checked = [d for d in days[: config.FORECAST_DAILY_DAYS] if d.get("temperature_2m_max") is not None]
    hot = [{"date": d["date"], "tmax_c": d["temperature_2m_max"]} for d in checked
           if d["temperature_2m_max"] > config.HEAT_THRESHOLD_C]
    hottest = max(checked, key=lambda d: d["temperature_2m_max"]) if checked else None
    if not checked:
        status = "unknown"
    else:
        status = "warning" if hot else "ok"
    return {
        "status": status,
        "hot_days": hot,
        "max_tmax_c": hottest["temperature_2m_max"] if hottest else None,
        "max_tmax_date": hottest["date"] if hottest else None,
        "days_checked": len(checked),
        "first_date": checked[0]["date"] if checked else None,
        "last_date": checked[-1]["date"] if checked else None,
        "thresholds": {"tmax_c": config.HEAT_THRESHOLD_C, "days": config.FORECAST_DAILY_DAYS},
    }
