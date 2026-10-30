"""Build the list of data points and rule outcomes that ground every answer.

Each data point carries: id, label, value, unit, the time the value refers to,
the source it came from and when that source was fetched. The language model
cites data points by id; the UI renders source and fetch time next to each.
"""
from datetime import datetime, timedelta

from . import config
from .http import SourceResult
from .timeutil import iso, parse_local


class Evidence:
    def __init__(self):
        self.points: list[dict] = []
        self.rules: list[dict] = []
        self._ids: set[str] = set()

    def add(self, pid: str, label: str, value, unit: str, src: SourceResult, valid_time: str | None = None):
        if src is None or not src.ok or pid in self._ids:
            return
        self._ids.add(pid)
        self.points.append({
            "id": pid,
            "label": label,
            "value": value,
            "unit": unit,
            "valid_time": valid_time,
            "source_id": src.source_id,
            "source": src.name,
            "fetched_at": iso(src.fetched_at) if src.fetched_at else None,
            "cached": src.cached,
        })

    def rule(self, rid: str, name: str, status: str, summary: str, thresholds: dict, evidence_ids: list[str]):
        self.rules.append({
            "id": rid,
            "name": name,
            "status": status,
            "summary": summary,
            "thresholds": thresholds,
            "evidence": [e for e in evidence_ids if e in self._ids],
        })

    def has(self, pid: str) -> bool:
        return pid in self._ids


def add_location(ev: Evidence, place: dict, geo: SourceResult):
    ev.add("loc_lat", "Latitude", place["lat"], "°", geo)
    ev.add("loc_lon", "Longitude", place["lon"], "°", geo)


def add_forecast(ev: Evidence, fc: SourceResult, now: datetime):
    if not fc.ok:
        return
    hours = fc.data["hours"]
    current = now.replace(minute=0, second=0, microsecond=0)
    nxt = [h for h in hours if current <= parse_local(h["time"]) < current + timedelta(hours=24)]
    if nxt:
        h0 = nxt[0]
        ev.add("now_temp", "Temperature (this hour)", h0["temperature_2m"], "°C", fc, h0["time"])
        ev.add("now_humidity", "Relative humidity (this hour)", h0["relative_humidity_2m"], "%", fc, h0["time"])
        ev.add("now_wind", "Wind speed at 10 m (this hour)", h0["wind_speed_10m"], "km/h", fc, h0["time"])
        ev.add("now_rain_prob", "Rain probability (this hour)", h0["precipitation_probability"], "%", fc, h0["time"])
        winds = [(h["wind_speed_10m"], h["time"]) for h in nxt if h["wind_speed_10m"] is not None]
        temps = [(h["temperature_2m"], h["time"]) for h in nxt if h["temperature_2m"] is not None]
        if winds:
            w, t = max(winds)
            ev.add("max_wind_24h", "Highest wind speed, next 24 h", w, "km/h", fc, t)
        if temps:
            hi, thi = max(temps)
            lo, tlo = min(temps)
            ev.add("max_temp_24h", "Highest temperature, next 24 h", hi, "°C", fc, thi)
            ev.add("min_temp_24h", "Lowest temperature, next 24 h", lo, "°C", fc, tlo)
    rain72 = [h["precipitation"] for h in hours if parse_local(h["time"]) >= current and h["precipitation"] is not None]
    if rain72:
        ev.add("rain_total_rest", "Forecast rain, rest of 3-day forecast", round(sum(rain72), 1), "mm", fc,
               f"{max(current, parse_local(hours[0]['time'])).strftime('%Y-%m-%dT%H:%M')} to {hours[-1]['time']}")


def add_spray(ev: Evidence, fc: SourceResult, res: dict):
    if not fc.ok:
        ev.rule("spray_window", "Spray window", "unknown",
                "Forecast unavailable, so spray windows could not be checked.", {}, [])
        return
    ids = []
    for i, w in enumerate(res["windows"], 1):
        pid = f"spray_window_{i}"
        ev.add(pid, f"Spray window {i}", f"{w['start']} to {w['end']} ({w['hours']} h, wind ≤ {w['max_wind_kmh']} km/h, "
               f"rain chance ≤ {w['max_precip_prob_pct']}%)", "", fc, w["start"])
        ids.append(pid)
    t = res["thresholds"]
    rule_text = (f"Wind below {t['max_wind_kmh']:g} km/h, rain probability below {t['max_precip_prob_pct']:g}% and no rain, "
                 f"for at least {t['min_hours']} hours in a row")
    if t["allowed_hours"]:
        rule_text += f", between {t['allowed_hours'][0]:02d}:00 and {t['allowed_hours'][1]:02d}:00"
    if ids:
        summary = f"{len(ids)} safe spray window(s) found. Rule: {rule_text}."
        status = "found"
    else:
        summary = f"No safe spray window in the forecast ({res['hours_checked']} hours checked). Rule: {rule_text}."
        status = "none"
        ids = [i for i in ("max_wind_24h",) if ev.has(i)]
    ev.rule("spray_window", "Spray window", status, summary, t, ids)


def add_heavy_rain(ev: Evidence, fc: SourceResult, res: dict):
    if not fc.ok:
        ev.rule("heavy_rain", "Heavy-rain warning", "unknown", "Forecast unavailable.", {}, [])
        return
    t = res["thresholds"]
    if res["max_precip_prob_pct"] is not None:
        ev.add("max_rain_prob_24h", "Highest rain probability, next 24 h", res["max_precip_prob_pct"], "%", fc,
               res["max_precip_prob_time"])
    if res["total_precip_mm"] is not None:
        ev.add("rain_total_24h", "Total forecast rain, next 24 h", res["total_precip_mm"], "mm", fc,
               f"{res['window_start']} to {res['window_end']}")
    rule_text = f"warn if rain probability > {t['prob_pct']:g}% or 24 h total > {t['total_mm']:g} mm"
    if res["status"] == "warning":
        summary = f"Heavy-rain warning: postpone field work and check drainage ({rule_text})."
    elif res["status"] == "ok":
        summary = f"No heavy rain expected in the next 24 h ({rule_text})."
    else:
        summary = "Not enough forecast data to check heavy rain."
    ev.rule("heavy_rain", "Heavy-rain warning", res["status"], summary, t, ["max_rain_prob_24h", "rain_total_24h"])


def add_deficit(ev: Evidence, mtd: SourceResult, base: SourceResult, res: dict):
    span = f"{res['window_start']} to {res['window_end']}"
    if res["observed_mm"] is not None:
        ev.add("rain_mtd", "Rainfall so far this month", res["observed_mm"], "mm", mtd, span)
    if res["baseline_mm"] is not None:
        ev.add("rain_normal", f"Average rainfall for same dates ({res['baseline_years']})", res["baseline_mm"], "mm",
               base, span)
        ev.add("baseline_years", "Baseline years used", f"{res['baseline_years']} ({res['baseline_year_count']} years)",
               "", base)
    if res["percent_of_normal"] is not None:
        # derived from two sources; attribute to the archive (the baseline)
        ev.add("rain_pct_normal", "Rainfall as % of normal", res["percent_of_normal"], "%", base, span)
    t = res["thresholds"]
    rule_text = f"drought risk below {t['drought_below_pct']:g}% of normal, waterlogging risk above {t['waterlog_above_pct']:g}%"
    summaries = {
        "drought_risk": f"Rainfall is {res['percent_of_normal']}% of normal: drought risk ({rule_text}).",
        "waterlogging_risk": f"Rainfall is {res['percent_of_normal']}% of normal: waterlogging risk ({rule_text}).",
        "normal": f"Rainfall is {res['percent_of_normal']}% of normal: within the normal range ({rule_text}).",
        "dry_season": "Normal rainfall for these dates is very low, so a percentage is not meaningful.",
        "unknown": f"Could not compare rainfall with normal: {res['note']}.",
    }
    ev.rule("rain_deficit", "Rainfall vs normal", res["status"], summaries[res["status"]], t,
            ["rain_mtd", "rain_normal", "rain_pct_normal", "baseline_years"])


def add_soil(ev: Evidence, soil: SourceResult, res: dict):
    if soil.ok:
        props = soil.data["properties"]
        where = f"{soil.data['offset_km']} km from the location" if soil.data["offset_km"] else "at the location"
        for key, pid, label in (("sand", "soil_sand", "Sand, topsoil 0-5 cm"),
                                ("clay", "soil_clay", "Clay, topsoil 0-5 cm"),
                                ("phh2o", "soil_ph", "pH (water), topsoil 0-5 cm"),
                                ("soc", "soil_soc", "Soil organic carbon, 0-5 cm")):
            p = props.get(key) or {}
            if p.get("value") is not None:
                ev.add(pid, f"{label} ({where})", p["value"], p.get("unit", ""), soil)
        if soil.data["offset_km"]:
            ev.add("soil_offset", "Distance to nearest soil sample point", soil.data["offset_km"], "km", soil)
    t = res["thresholds"]
    rule_text = (f"sand > {t['sand_high_pct']:g}%: lighter, more frequent irrigation; clay > {t['clay_high_pct']:g}%: "
                 f"caution in heavy rain; pH < {t['ph_low']:g} or > {t['ph_high']:g}: get a soil test")
    if res["status"] == "unknown":
        summary = "Soil data unavailable for this point."
    elif res["flags"]:
        summary = f"Soil flags: {', '.join(res['flags'])} ({rule_text})."
    else:
        summary = f"No soil flags raised ({rule_text})."
    ev.rule("soil", "Soil", res["status"], summary, t, ["soil_sand", "soil_clay", "soil_ph", "soil_offset"])


def data_lookup(ev: Evidence) -> dict[str, dict]:
    return {p["id"]: p for p in ev.points}


def all_values(ev: Evidence, extra: list | None = None) -> list:
    """Every value the model may legitimately quote (data, times, thresholds)."""
    vals = []
    for p in ev.points:
        vals += [p["value"], p["valid_time"], p["fetched_at"]]
    for r in ev.rules:
        vals += [v for v in r["thresholds"].values() if not isinstance(v, (list, dict))]
        vals += [x for v in r["thresholds"].values() if isinstance(v, list) for x in v]
    vals += [config.SPRAY_MIN_HOURS, config.HEAVY_RAIN_LOOKAHEAD_H, config.FORECAST_DAYS * 24]
    return vals + (extra or [])
