"""Heavy-rain warning for the next 24 hours.

Triggers if any hour's rain probability is above HEAVY_RAIN_PROB_PCT or the
24-hour rainfall total is above HEAVY_RAIN_TOTAL_MM.
"""
from datetime import datetime, timedelta

from .. import config
from ..timeutil import parse_local


def evaluate(hours: list[dict], now: datetime) -> dict:
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=config.HEAVY_RAIN_LOOKAHEAD_H)
    window = [h for h in hours if start <= parse_local(h["time"]) < end]

    probs = [(h["precipitation_probability"], h["time"]) for h in window
             if h.get("precipitation_probability") is not None]
    rains = [h["precipitation"] for h in window if h.get("precipitation") is not None]

    max_prob, max_prob_time = max(probs) if probs else (None, None)
    total_mm = round(sum(rains), 1) if rains else None
    missing_hours = len(window) - min(len(probs), len(rains))

    reasons = []
    if max_prob is not None and max_prob > config.HEAVY_RAIN_PROB_PCT:
        reasons.append("probability")
    if total_mm is not None and total_mm > config.HEAVY_RAIN_TOTAL_MM:
        reasons.append("total")

    if not window or (max_prob is None and total_mm is None):
        status = "unknown"
    else:
        status = "warning" if reasons else "ok"

    return {
        "status": status,
        "reasons": reasons,
        "max_precip_prob_pct": max_prob,
        "max_precip_prob_time": max_prob_time,
        "total_precip_mm": total_mm,
        "hours_checked": len(window),
        "missing_hours": missing_hours,
        "window_start": window[0]["time"] if window else None,
        "window_end": window[-1]["time"] if window else None,
        "thresholds": {
            "prob_pct": config.HEAVY_RAIN_PROB_PCT,
            "total_mm": config.HEAVY_RAIN_TOTAL_MM,
            "lookahead_h": config.HEAVY_RAIN_LOOKAHEAD_H,
        },
    }
