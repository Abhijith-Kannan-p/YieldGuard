"""Soil fallback: when the SoilGrids REST API fails, the same maps are read from ISRIC's WCS map service.
The GeoTIFFs here are written by a small encoder in this file, in the layout the service returns
(16-bit signed, deflate, horizontal predictor, tiled), so no test touches the network."""
import struct
import zlib
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from app import http
from app.http import FetchError
from app.sources import soil, soil_wcs
from app.timeutil import now_local

from .conftest import load_fixture

DX = 0.0025  # degrees per pixel


def make_tiff(grid: list[list[int]], lon0: float, lat0: float, tile: int | None = None) -> bytes:
    """Little-endian GeoTIFF: int16, deflate, predictor 2; tiled (tile x tile) or one strip."""
    h, w = len(grid), len(grid[0])
    tw, th = (tile, tile) if tile else (w, h)
    chunks = []
    for r0 in range(0, h, th):
        for c0 in range(0, w if tile else 1, tw):
            rows = []
            for r in range(r0, r0 + th):
                line = [(grid[r][c] if r < h and c < w else 0) for c in range(c0, c0 + tw)]
                rows += [line[0]] + [((line[i] - line[i - 1] + 32768) % 65536) - 32768 for i in range(1, tw)]
            chunks.append(zlib.compress(struct.pack(f"<{len(rows)}h", *rows)))
    entries = [(256, 4, [w]), (257, 4, [h]), (258, 3, [16]), (259, 3, [8]), (277, 3, [1]), (317, 3, [2]),
               (339, 3, [2]), (33550, 12, [DX, DX, 0.0]), (33922, 12, [0.0, 0.0, 0.0, lon0, lat0, 0.0])]
    entries += ([(322, 4, [tw]), (323, 4, [th]), (324, 4, None), (325, 4, [len(c) for c in chunks])] if tile else
                [(273, 4, None), (278, 4, [h]), (279, 4, [len(c) for c in chunks])])
    entries.sort()
    fmt, size = {3: ("H", 2), 4: ("I", 4), 12: ("d", 8)}, lambda typ, n: {3: 2, 4: 4, 12: 8}[typ] * n
    ifd_len = 2 + 12 * len(entries) + 4
    extra_at = 8 + ifd_len
    n_chunks = len(chunks)
    # Lay out out-of-line values first, then the image data.
    extras, positions, pos = b"", {}, extra_at
    for tag, typ, vals in entries:
        n = n_chunks if vals is None else len(vals)
        if size(typ, n) > 4:
            positions[tag] = pos
            pos += size(typ, n)
            extras += b"\0" * size(typ, n)
    data_at = pos
    offsets, p = [], data_at
    for c in chunks:
        offsets.append(p)
        p += len(c)
    out_entries, extras = b"", bytearray(extras)
    for tag, typ, vals in entries:
        vals = offsets if vals is None else vals
        packed = struct.pack(f"<{len(vals)}{fmt[typ][0]}", *vals)
        if tag in positions:
            start = positions[tag] - extra_at
            extras[start:start + len(packed)] = packed
            out_entries += struct.pack("<HHII", tag, typ, len(vals), positions[tag])
        else:
            out_entries += struct.pack("<HHI", tag, typ, len(vals)) + packed.ljust(4, b"\0")
    ifd = struct.pack("<H", len(entries)) + out_entries + b"\0\0\0\0"
    return b"II" + struct.pack("<HI", 42, 8) + ifd + bytes(extras) + b"".join(chunks)


@pytest.mark.parametrize("tile", [None, 16])
def test_reads_values_and_georeference(tile):
    grid = [[r * 100 + c for c in range(22)] for r in range(20)]
    g = soil_wcs.read_grid(make_tiff(grid, 75.0, 15.5, tile=tile))
    assert g["values"] == grid
    assert (g["lon0"], g["lat0"], g["dx"], g["dy"]) == (75.0, 15.5, DX, DX)


def test_not_a_tiff_is_a_fetch_error():
    with pytest.raises(FetchError):
        soil_wcs.read_grid(b"<html>503</html>")


RAW = {"clay": 282, "sand": 414, "phh2o": 69, "soc": 183}  # the saved REST response for this area


def wcs_grid(prop: str, masked_center: bool) -> list[list[int]]:
    """5x5 pixels around the point; the centre (urban) pixel masked if asked, its east neighbour valid."""
    grid = [[0] * 5 for _ in range(5)]
    grid[2][3] = RAW[prop]
    if not masked_center:
        grid[2][2] = RAW[prop] + 1
    return grid


@pytest.fixture
def world(monkeypatch):
    """REST is down (503). WCS answers from wcs_grid(); every WCS request is counted."""
    state = {"wcs": 0, "wcs_status": 200, "masked_center": True}
    lat, lon = 15.46, 75.01

    async def rest_down(*a, **k):
        raise FetchError("HTTP 503", status=503)

    def handler(request: httpx.Request):
        assert request.url.host == "maps.isric.org"
        state["wcs"] += 1
        if state["wcs_status"] != 200:
            return httpx.Response(state["wcs_status"], text="<html>503</html>")
        prop = parse_qs(request.url.query.decode())["COVERAGEID"][0].split("_")[0]
        # Top-left corner such that pixel (2, 2) is centred on the point.
        return httpx.Response(200, content=make_tiff(wcs_grid(prop, state["masked_center"]),
                                                     lon - 2.5 * DX, lat + 2.5 * DX))

    monkeypatch.setattr(soil, "get_json", rest_down)
    monkeypatch.setattr(http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return state, lat, lon


async def test_rest_503_uses_wcs_nearest_valid_pixel(world):
    state, lat, lon = world
    res = await soil.fetch(lat, lon)
    assert res.ok and res.name == soil_wcs.NAME and res.meta["fallback_for"] == "SoilGrids REST API"
    assert "SoilGrids REST API failed (HTTP 503)" in res.error
    props = res.data["properties"]
    assert {k: v["value"] for k, v in props.items()} == {"clay": 28.2, "sand": 41.4, "phh2o": 6.9, "soc": 18.3}
    assert res.data["offset_km"] == soil.distance_km(lat, lon, lat, round(lon + DX, 4))
    assert state["wcs"] == 4  # one image per property

    again = await soil.fetch(lat, lon)  # saved: no new WCS request
    assert again.ok and again.cached and state["wcs"] == 4


async def test_point_itself_valid_reports_no_offset(world):
    state, lat, lon = world
    state["masked_center"] = False
    res = await soil.fetch(lat, lon)
    assert res.data["offset_km"] == 0.0 and res.data["properties"]["clay"]["value"] == 28.3


async def test_saved_rest_copy_is_preferred_over_wcs(world):
    state, lat, lon = world
    saved = {"properties": soil.convert(load_fixture("soil_dharwad_nearby.json")),
             "query_lat": lat, "query_lon": lon, "offset_km": 0.0}
    soil.soil_store.set("soil:15.46,75.01", saved, now_local() - timedelta(days=10), ttl_s=-1)
    res = await soil.fetch(lat, lon)
    assert res.ok and res.stale and res.name == soil.NAME and state["wcs"] == 0


async def test_rest_and_wcs_both_down(world):
    state, lat, lon = world
    state["wcs_status"] = 503
    res = await soil.fetch(lat, lon)
    assert not res.ok and "soil data is temporarily unavailable" in res.error
