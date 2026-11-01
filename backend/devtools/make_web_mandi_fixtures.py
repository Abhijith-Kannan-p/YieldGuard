"""Write the Mandi page's frontend test fixtures (web/tests/fixtures/mandi_*.json) from saved backend fixtures.

    cd backend
    python -m devtools.make_web_mandi_fixtures

Calls the real /api/mandi endpoints with data.gov.in answered by the saved snapshot (or the saved empty
response), geocoding answered by the saved Open-Meteo responses, and the clock set to the snapshot day.
No network request is made and nothing is written by hand.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, mandi_page
from app.http import SourceResult
from app.main import app
from app.sources import geocode, mandi
from app.timeutil import TZ

BACKEND_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
WEB_FIXTURES = Path(__file__).resolve().parents[2] / "web" / "tests" / "fixtures"


def _load(name: str):
    return json.loads((BACKEND_FIXTURES / name).read_text(encoding="utf-8"))


def main() -> None:
    snapshot_file = sorted(BACKEND_FIXTURES.glob("mandi_karnataka_*.json"))[-1]
    day = snapshot_file.stem.rsplit("_", 1)[-1]
    clock = {"now": datetime.fromisoformat(day).replace(hour=10, tzinfo=TZ)}
    payload = {"value": _load(snapshot_file.name)}
    saved_geo = {**_load("mandi_geocode.json")["by_query"], "Dharwad": _load("geocode_dharwad.json")}

    async def api(url, params, **kw):
        return payload["value"]

    async def search(q, count=10):
        resp = saved_geo.get(q)
        if resp is None:
            return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, status="failed", error="no saved response")
        places = [p.__dict__ for p in geocode.pick_karnataka(resp.get("results") or [])]
        return SourceResult("geocode", geocode.NAME, config.GEOCODING_URL, data=places, fetched_at=clock["now"])

    config.DATAGOV_API_KEY = "saved-fixtures"
    mandi.get_json = api
    geocode.search = search
    mandi_page.now_local = lambda: clock["now"]

    def fresh() -> None:
        mandi.cache.clear()
        mandi.clear()

    outputs = {}
    c = TestClient(app)  # no "with": app startup would queue a live rainfall-baseline build
    fresh()
    outputs["mandi_crops.json"] = c.get("/api/mandi/crops").json()
    fresh()
    outputs["mandi_found.json"] = c.get("/api/mandi", params={"crop": "Maize", "location": "Dharwad"}).json()
    fresh()
    outputs["mandi_no_nearby.json"] = c.get("/api/mandi", params={"crop": "Tomato", "location": "Dharwad"}).json()
    fresh()
    clock["now"] += timedelta(days=1)
    outputs["mandi_latest.json"] = c.get("/api/mandi", params={"crop": "Maize", "location": "Dharwad"}).json()
    clock["now"] -= timedelta(days=1)
    fresh()
    payload["value"] = _load("mandi_empty.json")
    outputs["mandi_no_data.json"] = c.get("/api/mandi", params={"crop": "Maize", "location": "Dharwad"}).json()
    WEB_FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, body in outputs.items():
        (WEB_FIXTURES / name).write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote web/tests/fixtures/{name}: status={body.get('status')}")


if __name__ == "__main__":
    main()
