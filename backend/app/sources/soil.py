"""ISRIC SoilGrids v2.0 point query (topsoil 0-5 cm, mean).

SoilGrids stores integers scaled by `d_factor` (e.g. pH x 10, clay in g/kg).
We divide by the d_factor reported in the response itself to get the target
units: clay/sand in %, pH in pH units, SOC in g/kg.

Successful responses are cached per coordinate pair (rounded to 2 decimals) for
TTL_SOIL and saved to SOIL_CACHE_FILE. If SoilGrids fails (for example HTTP 503),
the last saved response is used and labelled with its fetch time; without one,
the answer says soil data is temporarily unavailable.
"""
import math
import time

from .. import config
from ..cache import FileCache
from ..http import FetchError, SourceResult, cached_fetch, coord_key, get_json

NAME = "ISRIC SoilGrids v2.0"
NO_VALUES = "no soil values at this point or nearby (area may be urban or water)"

soil_store = FileCache(config.SOIL_CACHE_FILE)

TARGET_UNITS = {"clay": "%", "sand": "%", "phh2o": "pH", "soc": "g/kg"}


def convert(payload: dict) -> dict[str, dict]:
    """Return {property: {"value": float|None, "unit": str, "raw": int|None, "d_factor": int}}."""
    out = {}
    for layer in (payload.get("properties") or {}).get("layers", []):
        name = layer.get("name")
        if name not in config.SOIL_PROPERTIES:
            continue
        d_factor = (layer.get("unit_measure") or {}).get("d_factor") or 1
        raw = None
        for depth in layer.get("depths", []):
            if depth.get("label") == config.SOIL_DEPTH:
                raw = (depth.get("values") or {}).get(config.SOIL_VALUE)
        value = round(raw / d_factor, 2) if raw is not None else None
        out[name] = {"value": value, "unit": TARGET_UNITS.get(name, ""), "raw": raw, "d_factor": d_factor}
    return out


def has_values(props: dict) -> bool:
    return any(p.get("value") is not None for p in props.values())


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


async def _query(lat: float, lon: float, retries: int) -> dict:
    params = [("lon", lon), ("lat", lat)] + [("property", p) for p in config.SOIL_PROPERTIES] + [
        ("depth", config.SOIL_DEPTH), ("value", config.SOIL_VALUE)]
    return convert(await get_json(config.SOILGRIDS_URL, params, retries=retries))


async def fetch(lat: float, lon: float) -> SourceResult:
    async def load():
        deadline = time.monotonic() + config.SOIL_TOTAL_BUDGET_S
        props = await _query(lat, lon, retries=config.HTTP_RETRIES)
        if has_values(props):
            return {"properties": props, "query_lat": lat, "query_lon": lon, "offset_km": 0.0}
        # Exact pixel is masked (often urban). Probe nearby points one at a time
        # to stay within SoilGrids' fair-use rate limit.
        for dlat, dlon in config.SOIL_FALLBACK_OFFSETS:
            if time.monotonic() > deadline:
                break
            qlat, qlon = round(lat + dlat, 4), round(lon + dlon, 4)
            try:
                props = await _query(qlat, qlon, retries=0)
            except FetchError:
                continue
            if has_values(props):
                return {"properties": props, "query_lat": qlat, "query_lon": qlon,
                        "offset_km": distance_km(lat, lon, qlat, qlon)}
        raise FetchError(NO_VALUES)

    res = await cached_fetch("soil", NAME, config.SOILGRIDS_URL,
                             f"soil:{coord_key(lat, lon)}", config.TTL_SOIL, load, store=soil_store)
    if not res.ok and res.error != NO_VALUES:
        res.error = f"soil data is temporarily unavailable ({res.error})"
    return res
