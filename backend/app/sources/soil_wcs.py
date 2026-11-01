"""SoilGrids through ISRIC's WCS map service: the soil fallback when the SoilGrids REST API fails.

The REST point query (sources/soil.py) is often down with HTTP 503 while the WCS service, which serves
the same SoilGrids v2.0 maps, keeps working. For each property (clay, sand, pH, SOC; 0-5 cm, mean) this
asks for a small GeoTIFF around the point, in lat/lon (EPSG:4326), and reads the pixels with a minimal
TIFF reader (16-bit integers, deflate, optional horizontal predictor; stdlib only).

- Values are the same scaled integers the REST API returns (d_factor 10 for all four properties).
- 0 means no data (masked pixel, usually urban or water), as REST's null does. When the point itself is
  masked, the nearest pixel with a pH value is used for every property and its distance is reported.
- Results are saved in the same file as REST responses (soil does not change), under their own key.
Data: ISRIC SoilGrids v2.0, CC BY 4.0.
"""
import asyncio
import logging
import struct
import time
import zlib

from .. import config
from ..http import FetchError, SourceResult, coord_key, get_client
from ..timeutil import now_local

log = logging.getLogger(__name__)

NAME = "ISRIC SoilGrids v2.0 (WCS map service)"
D_FACTOR = 10
_CRS = "http://www.opengis.net/def/crs/EPSG/0/4326"
_TYPE_SIZE = {1: 1, 3: 2, 4: 4, 8: 2, 12: 8, 16: 8}
_TYPE_FMT = {1: "B", 3: "H", 4: "I", 8: "h", 12: "d", 16: "Q"}


def _tags(b: bytes) -> tuple[str, dict]:
    bo = {b"II": "<", b"MM": ">"}.get(b[:2])
    if bo is None or struct.unpack(bo + "H", b[2:4])[0] != 42:
        raise FetchError("WCS response is not a TIFF image")
    off = struct.unpack(bo + "I", b[4:8])[0]
    tags = {}
    for i in range(struct.unpack(bo + "H", b[off:off + 2])[0]):
        e = b[off + 2 + i * 12: off + 14 + i * 12]
        tag, typ, cnt = struct.unpack(bo + "HHI", e[:8])
        if typ not in _TYPE_FMT:
            continue
        size = _TYPE_SIZE[typ] * cnt
        raw = e[8:8 + size] if size <= 4 else b[struct.unpack(bo + "I", e[8:12])[0]:][:size]
        tags[tag] = struct.unpack(bo + _TYPE_FMT[typ] * cnt, raw)
    return bo, tags


def read_grid(b: bytes) -> dict:
    """GeoTIFF -> {"values": rows of ints, "lon0", "lat0" (top-left corner), "dx", "dy"}."""
    bo, t = _tags(b)
    w, h = t[256][0], t[257][0]
    if t.get(258, (0,))[0] != 16 or t.get(339, (1,))[0] != 2 or t.get(259, (1,))[0] not in (1, 8):
        raise FetchError("WCS image is not 16-bit signed integers")
    deflate, predictor = t.get(259, (1,))[0] == 8, t.get(317, (1,))[0]
    if 322 in t:  # tiled
        tw, th, offsets, counts = t[322][0], t[323][0], t[324], t[325]
    else:         # stripped: each strip is a full-width tile
        tw, th, offsets, counts = w, t.get(278, (h,))[0], t[273], t[279]
    across = -(-w // tw)
    grid = [[0] * w for _ in range(h)]
    for n, (o, c) in enumerate(zip(offsets, counts)):
        raw = b[o:o + c]
        raw = zlib.decompress(raw) if deflate else raw
        vals = list(struct.unpack(f"{bo}{len(raw) // 2}h", raw[: len(raw) // 2 * 2]))
        row0, col0 = (n // across) * th, (n % across) * tw
        for r in range(th):
            line = vals[r * tw:(r + 1) * tw]
            if predictor == 2:
                for i in range(1, len(line)):
                    line[i] = (line[i] + line[i - 1] + 32768) % 65536 - 32768
            if row0 + r < h:
                for i, v in enumerate(line[: max(0, min(tw, w - col0))]):
                    grid[row0 + r][col0 + i] = v
    sx, sy = t[33550][0], t[33550][1]
    tie = t[33922]  # (i, j, k, x, y, z): pixel (i, j) is at (x, y)
    return {"values": grid, "lon0": tie[3] - tie[0] * sx, "lat0": tie[4] + tie[1] * sy, "dx": sx, "dy": sy}


async def _coverage(prop: str, lat: float, lon: float) -> dict:
    d = config.SOIL_WCS_HALF_WINDOW_DEG
    params = [("map", f"/map/{prop}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
              ("COVERAGEID", f"{prop}_{config.SOIL_DEPTH}_{config.SOIL_VALUE}"), ("FORMAT", "image/tiff"),
              ("SUBSET", f"long({lon - d:.5f},{lon + d:.5f})"), ("SUBSET", f"lat({lat - d:.5f},{lat + d:.5f})"),
              ("SUBSETTINGCRS", _CRS), ("OUTPUTCRS", _CRS)]
    t0 = time.perf_counter()
    status: int | str = "-"
    try:
        resp = await get_client().get(config.SOILGRIDS_WCS_URL, params=params, timeout=config.HTTP_TIMEOUT_S * 2)
        status = resp.status_code
        if resp.status_code != 200:
            raise FetchError(f"HTTP {resp.status_code}", status=resp.status_code)
        return read_grid(resp.content)
    except FetchError:
        raise
    except Exception as e:  # network errors, odd images: the fallback must never crash the request
        status = type(e).__name__
        raise FetchError(f"WCS unavailable ({type(e).__name__})") from None
    finally:
        log.info("fetch maps.isric.org wcs %s lat=%s lon=%s -> %s in %.0f ms", prop, lat, lon, status,
                 (time.perf_counter() - t0) * 1000)


def pick(grids: dict[str, dict], lat: float, lon: float) -> tuple[dict, float, float] | None:
    """The pixel nearest (lat, lon) that has a pH value: ({prop: raw}, pixel lat, pixel lon), or None."""
    from .soil import distance_km
    ph = grids["phh2o"]
    best = None
    for r, row in enumerate(ph["values"]):
        for c, v in enumerate(row):
            if v <= 0:
                continue
            plat, plon = ph["lat0"] - (r + 0.5) * ph["dy"], ph["lon0"] + (c + 0.5) * ph["dx"]
            dist = distance_km(lat, lon, plat, plon)
            if best is None or dist < best[0]:
                best = (dist, r, c, plat, plon)
    if best is None:
        return None
    _, r, c, plat, plon = best
    raw = {}
    for prop, g in grids.items():
        rows = g["values"]
        v = rows[r][c] if r < len(rows) and c < len(rows[r]) else 0
        raw[prop] = v if v > 0 else None
    return raw, round(plat, 4), round(plon, 4)


async def fetch(lat: float, lon: float) -> SourceResult:
    from .soil import NO_VALUES, TARGET_UNITS, distance_km, soil_store

    key = f"soilwcs:{coord_key(lat, lon)}"
    hit = soil_store.get(key) or soil_store.get_stale(key)  # soil does not change: any saved copy will do
    if hit is not None:
        return SourceResult("soil", NAME, config.SOILGRIDS_WCS_URL, data=hit.value, fetched_at=hit.fetched_at,
                            cached=True, meta={"fallback_for": "SoilGrids REST API"})
    try:
        grids = dict(zip(config.SOIL_PROPERTIES,
                         await asyncio.gather(*(_coverage(p, lat, lon) for p in config.SOIL_PROPERTIES))))
    except FetchError as e:
        return SourceResult("soil", NAME, config.SOILGRIDS_WCS_URL, status="failed", error=str(e))
    found = pick(grids, lat, lon)
    if found is None:
        return SourceResult("soil", NAME, config.SOILGRIDS_WCS_URL, status="failed", error=NO_VALUES)
    raw, qlat, qlon = found
    props = {p: {"value": round(v / D_FACTOR, 2) if v is not None else None, "unit": TARGET_UNITS.get(p, ""),
                 "raw": v, "d_factor": D_FACTOR} for p, v in raw.items()}
    offset = distance_km(lat, lon, qlat, qlon)
    data = {"properties": props, "query_lat": qlat, "query_lon": qlon, "offset_km": offset if offset >= 0.2 else 0.0}
    fetched_at = now_local()
    soil_store.set(key, data, fetched_at, config.TTL_SOIL)
    return SourceResult("soil", NAME, config.SOILGRIDS_WCS_URL, data=data, fetched_at=fetched_at,
                        meta={"fallback_for": "SoilGrids REST API"})
