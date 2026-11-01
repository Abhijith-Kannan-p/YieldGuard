"""Save real data.gov.in mandi responses to tests/fixtures (for tests only; the app never reads them).

    cd backend
    python -m devtools.capture_mandi

Needs DATAGOV_API_KEY in the environment (or .env). The key is never written to the saved files.
Saves the full Karnataka snapshot, a real empty response (a commodity filter that matches nothing),
and the real Open-Meteo geocoding response for each market name in the snapshot.
"""
import json
import sys
from pathlib import Path

import httpx

from app import config
from app.sources.mandi import market_query
from app.timeutil import iso, now_local

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def get(params: dict) -> dict:
    full = {"api-key": config.DATAGOV_API_KEY, "format": "json", **params}
    # Errors are reported by status only: httpx messages include the URL, and the URL holds the key.
    try:
        r = httpx.get(config.MANDI_URL, params=full, timeout=120)
    except httpx.HTTPError as e:
        sys.exit(f"data.gov.in request failed ({type(e).__name__})")
    if r.status_code != 200:
        sys.exit(f"data.gov.in answered HTTP {r.status_code}")
    return r.json()


def save(name: str, payload: dict, query: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if config.DATAGOV_API_KEY in text:
        sys.exit(f"refusing to save {name}: the response contains the API key")
    (FIXTURES / name).write_text(text + "\n", encoding="utf-8")
    manifest_path = FIXTURES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[name] = {"captured_at": iso(now_local()), "source": "Agmarknet mandi prices (data.gov.in)", "query": query}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"saved {name}: total={payload.get('total')} records={len(payload.get('records') or [])}")


def main() -> None:
    if not config.DATAGOV_API_KEY:
        sys.exit("set DATAGOV_API_KEY first")
    snap = get({"limit": config.MANDI_PAGE_SIZE, "offset": 0, "filters[state.keyword]": config.REGION_NAME})
    day = max((r.get("arrival_date", "") for r in snap.get("records") or []), default="")
    stamp = "-".join(reversed(day.split("/"))) if day else iso(now_local())[:10]
    save(f"mandi_karnataka_{stamp}.json", snap, f"filters[state.keyword]=Karnataka limit={config.MANDI_PAGE_SIZE}")
    empty = get({"limit": 10, "filters[state.keyword]": config.REGION_NAME, "filters[commodity]": "No Such Commodity"})
    save("mandi_empty.json", empty, "filters[state.keyword]=Karnataka filters[commodity]=No Such Commodity")
    names = sorted({market_query(r.get("market", "")) for r in snap.get("records") or []} - {""})
    geo = {}
    for name in names:
        r = httpx.get(config.GEOCODING_URL, params={"name": name, "count": 10, "language": "en", "format": "json",
                                                    "countryCode": config.COUNTRY_CODE}, timeout=30)
        geo[name] = r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    save("mandi_geocode.json", {"records": [], "total": len(geo), "by_query": geo},
         f"Open-Meteo Geocoding for {len(geo)} market names in the snapshot")


if __name__ == "__main__":
    main()
