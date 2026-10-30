"""Soil-aware adjustments from SoilGrids topsoil properties."""
from .. import config


def evaluate(props: dict | None) -> dict:
    """`props` is the converted SoilGrids dict: {name: {"value": float|None, ...}}."""
    props = props or {}
    sand = (props.get("sand") or {}).get("value")
    clay = (props.get("clay") or {}).get("value")
    ph = (props.get("phh2o") or {}).get("value")
    soc = (props.get("soc") or {}).get("value")

    flags = []
    if sand is not None and sand > config.SOIL_SAND_HIGH_PCT:
        flags.append("high_sand")   # -> lighter, more frequent irrigation
    if clay is not None and clay > config.SOIL_CLAY_HIGH_PCT:
        flags.append("high_clay")   # -> drains slowly, caution in heavy rain
    if ph is not None and ph < config.SOIL_PH_LOW:
        flags.append("acidic")      # -> suggest soil test
    if ph is not None and ph > config.SOIL_PH_HIGH:
        flags.append("alkaline")    # -> suggest soil test

    known = [v for v in (sand, clay, ph) if v is not None]
    return {
        "status": "unknown" if not known else ("flags" if flags else "ok"),
        "flags": flags,
        "sand_pct": sand,
        "clay_pct": clay,
        "ph": ph,
        "soc_g_per_kg": soc,
        "missing": [n for n, v in (("sand", sand), ("clay", clay), ("pH", ph)) if v is None],
        "thresholds": {
            "sand_high_pct": config.SOIL_SAND_HIGH_PCT,
            "clay_high_pct": config.SOIL_CLAY_HIGH_PCT,
            "ph_low": config.SOIL_PH_LOW,
            "ph_high": config.SOIL_PH_HIGH,
        },
    }
