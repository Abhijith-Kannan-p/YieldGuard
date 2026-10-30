"""Test helpers. Fixtures are real API responses saved for testing only;
the app itself never reads them at runtime."""
import json
from pathlib import Path

import pytest

from app.cache import cache

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_hours(start: str, rows: list[tuple]):
    """rows: (wind, prob, precip) per hour starting at `start` (local ISO hour)."""
    from datetime import timedelta
    from app.timeutil import parse_local
    t0 = parse_local(start)
    out = []
    for i, (wind, prob, rain) in enumerate(rows):
        t = (t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
        out.append({"time": t, "temperature_2m": 25.0, "relative_humidity_2m": 60,
                    "precipitation_probability": prob, "precipitation": rain, "wind_speed_10m": wind})
    return out
