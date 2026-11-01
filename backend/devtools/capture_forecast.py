"""Save a real Open-Meteo forecast for Dharwad to tests/fixtures (for tests only; the app never reads it).

    cd backend
    python -m devtools.capture_forecast

Same request the browser sends (web/lib/forecastClient.ts): 73 hours, 7 days, no past days, Asia/Kolkata.
The capture time goes into manifest.json; tests freeze their clock to it.
"""
import json
import sys
from pathlib import Path

import httpx

from app import config
from app.timeutil import iso, now_local

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
PLACE = {"latitude": 15.46, "longitude": 75.01}  # Dharwad, rounded to two decimals as the browser does


def main() -> None:
    params = {**PLACE, "hourly": ",".join(config.FORECAST_HOURLY_VARS), "daily": ",".join(config.FORECAST_DAILY_VARS),
              "timezone": config.TIMEZONE, "forecast_hours": config.FORECAST_HOURS + 1, "past_hours": 0,
              "forecast_days": config.FORECAST_DAILY_DAYS, "past_days": 0}
    captured = now_local()
    r = httpx.get(config.FORECAST_URL, params=params, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Open-Meteo answered HTTP {r.status_code}")
    name = f"forecast_browser_dharwad_{captured.date().isoformat()}.json"
    (FIXTURES / name).write_text(json.dumps(r.json(), indent=1) + "\n", encoding="utf-8")
    manifest_path = FIXTURES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[name] = {"captured_at": iso(captured), "source": "Open-Meteo Forecast API",
                      "query": "browser request: forecast_hours=73 past_hours=0 forecast_days=7 past_days=0 (Dharwad)"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"saved {name} (captured {iso(captured)})")


if __name__ == "__main__":
    main()
