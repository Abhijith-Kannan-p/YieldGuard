"""Irrigation planner: a simple daily water balance for the next FORECAST_DAILY_DAYS days.

For each day, crop water use is ET0 (FAO reference evapotranspiration) x CROP_FACTOR.
Rain refills the soil. The running deficit starts at 0 today:

    deficit(day) = max(0, deficit(day before) + ET0 x CROP_FACTOR - rain)

Irrigation is suggested on the first day the running deficit exceeds IRRIGATION_DEFICIT_MM.
This is an estimate: it ignores soil type, crop stage and any water already in the soil.
"""
from .. import config


def plan(days: list[dict]) -> dict:
    """`days`: daily rows with date, precipitation_sum, et0_fao_evapotranspiration (mm), from today."""
    rows, deficit, irrigate_on, stopped_at = [], 0.0, None, None
    for d in days[: config.FORECAST_DAILY_DAYS]:
        et0, rain = d.get("et0_fao_evapotranspiration"), d.get("precipitation_sum")
        if et0 is None or rain is None:
            stopped_at = d["date"]  # cannot continue the running balance past a gap
            break
        crop_use = round(et0 * config.CROP_FACTOR, 1)
        deficit = round(max(0.0, deficit + crop_use - rain), 1)
        over = deficit > config.IRRIGATION_DEFICIT_MM
        if over and irrigate_on is None:
            irrigate_on = d["date"]
        rows.append({"date": d["date"], "et0_mm": et0, "crop_use_mm": crop_use, "rain_mm": rain,
                     "deficit_mm": deficit, "over_threshold": over})

    if not rows:
        status = "unknown"
    elif irrigate_on:
        status = "irrigate"
    else:
        status = "ok"
    return {
        "status": status,
        "irrigate_on": irrigate_on,
        "days": rows,
        "final_deficit_mm": rows[-1]["deficit_mm"] if rows else None,
        "total_crop_use_mm": round(sum(r["crop_use_mm"] for r in rows), 1) if rows else None,
        "total_rain_mm": round(sum(r["rain_mm"] for r in rows), 1) if rows else None,
        "incomplete_from": stopped_at,
        "thresholds": {
            "crop_factor": config.CROP_FACTOR,
            "deficit_mm": config.IRRIGATION_DEFICIT_MM,
            "days": config.FORECAST_DAILY_DAYS,
        },
    }
