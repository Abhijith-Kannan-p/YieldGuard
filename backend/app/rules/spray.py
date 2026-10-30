"""Spray-window rule.

An hour is safe when wind, rain probability and rain amount are all below the
thresholds in config. A spray window is a run of at least SPRAY_MIN_HOURS
consecutive safe hours. Hours with a missing value are treated as NOT safe.
"""
from datetime import datetime, timedelta

from .. import config
from ..timeutil import parse_local


def hour_check(h: dict) -> tuple[bool, str | None]:
    """Return (is_safe, reason_if_not)."""
    wind = h.get("wind_speed_10m")
    prob = h.get("precipitation_probability")
    rain = h.get("precipitation")
    if wind is None or prob is None or rain is None:
        return False, "missing data"
    allowed = config.SPRAY_ALLOWED_HOURS
    if allowed is not None:
        hr = parse_local(h["time"]).hour
        if not (allowed[0] <= hr < allowed[1]):
            return False, "outside daylight hours"
    if wind >= config.SPRAY_MAX_WIND_KMH:
        return False, "wind too strong"
    if prob >= config.SPRAY_MAX_PRECIP_PROB_PCT:
        return False, "rain likely"
    if rain > config.SPRAY_MAX_PRECIP_MM:
        return False, "rain expected"
    return True, None


def find_windows(hours: list[dict], now: datetime) -> dict:
    """Find the earliest spray windows from the current hour onwards."""
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    upcoming = [h for h in hours if parse_local(h["time"]) >= current_hour]

    runs: list[list[dict]] = []
    run: list[dict] = []
    for h in upcoming:
        safe, _ = hour_check(h)
        if safe:
            run.append(h)
        else:
            if run:
                runs.append(run)
            run = []
    if run:
        runs.append(run)

    windows = []
    for r in runs:
        if len(r) < config.SPRAY_MIN_HOURS:
            continue
        winds = [h["wind_speed_10m"] for h in r]
        probs = [h["precipitation_probability"] for h in r]
        windows.append({
            "start": r[0]["time"],
            # end is exclusive: the hour after the last safe hour starts
            "end": _plus_one_hour(r[-1]["time"]),
            "hours": len(r),
            "max_wind_kmh": max(winds),
            "max_precip_prob_pct": max(probs),
        })
        if len(windows) >= config.SPRAY_MAX_WINDOWS:
            break

    return {
        "windows": windows,
        "hours_checked": len(upcoming),
        "checked_from": upcoming[0]["time"] if upcoming else None,
        "checked_to": upcoming[-1]["time"] if upcoming else None,
        "thresholds": {
            "max_wind_kmh": config.SPRAY_MAX_WIND_KMH,
            "max_precip_prob_pct": config.SPRAY_MAX_PRECIP_PROB_PCT,
            "max_precip_mm": config.SPRAY_MAX_PRECIP_MM,
            "min_hours": config.SPRAY_MIN_HOURS,
            "allowed_hours": list(config.SPRAY_ALLOWED_HOURS) if config.SPRAY_ALLOWED_HOURS else None,
        },
    }


def _plus_one_hour(t: str) -> str:
    return (parse_local(t) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
