"""Resolve a place name in Karnataka to coordinates via Open-Meteo Geocoding."""
from dataclasses import dataclass

from .. import config
from ..http import SourceResult, cached_fetch, get_json

NAME = "Open-Meteo Geocoding API"


@dataclass
class Place:
    name: str
    district: str | None
    state: str | None
    lat: float
    lon: float


def pick_karnataka(results: list[dict]) -> list[Place]:
    """Keep Karnataka results only, larger towns first ("Hubli" -> Hubballi city, not a village)."""
    places = []
    ranked = sorted(results or [], key=lambda r: -(r.get("population") or 0))
    for r in ranked:
        if r.get("country_code") != config.COUNTRY_CODE:
            continue
        if (r.get("admin1") or "").lower() != config.REGION_NAME.lower():
            continue
        places.append(Place(
            name=r.get("name", ""),
            district=r.get("admin2"),
            state=r.get("admin1"),
            lat=float(r["latitude"]),
            lon=float(r["longitude"]),
        ))
    return places


async def search(query: str, count: int = 10) -> SourceResult:
    query = " ".join(query.split())
    params = {"name": query, "count": count, "language": "en", "format": "json",
              "countryCode": config.COUNTRY_CODE}

    async def load():
        data = await get_json(config.GEOCODING_URL, params)
        return [p.__dict__ for p in pick_karnataka(data.get("results", []))]

    return await cached_fetch("geocode", NAME, config.GEOCODING_URL,
                              f"geo:{query.lower()}:{count}", config.TTL_GEOCODE, load)
