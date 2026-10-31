"""USE_FIXTURES=1 is a local-development switch. These tests check that it cannot leak into the
deployed app, and that when it is on, it is obvious. Fixture-mode runs happen in a subprocess
because the fixture server patches modules for the whole process."""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

PROBE = """
import json, sys
from fastapi.testclient import TestClient
import devtools.fixture_server as fs
c = TestClient(fs.app)
r = c.get("/advice", params={"location": "Dharwad", "question": "Can I spray tomorrow?", "lang": "en"})
other = c.get("/advice", params={"location": "Mysuru", "question": "spray?"})
sys.stdout.write(json.dumps({"status": r.status_code, "header": r.headers.get("X-YieldGuard-Data"),
                             "body": r.json(), "other_status": other.status_code}))
"""


def _run(env_extra: dict, code: str = PROBE) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("USE_FIXTURES", "RENDER")}
    env.update(env_extra)
    env["GEMINI_API_KEY"] = ""  # keep the test offline: rule-based answer
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def test_app_package_never_references_fixtures():
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "fixture" not in text and "devtools" not in text, path


def test_deployed_start_command_is_the_live_app():
    render = (BACKEND.parent / "render.yaml").read_text(encoding="utf-8")
    assert "uvicorn app.main:app" in render and "devtools" not in render and "USE_FIXTURES" not in render


def test_fixture_server_refuses_without_switch():
    res = _run({}, "import devtools.fixture_server")
    assert res.returncode != 0 and "USE_FIXTURES=1" in res.stderr


def test_fixture_server_refuses_on_render():
    res = _run({"USE_FIXTURES": "1", "RENDER": "true"}, "import devtools.fixture_server")
    assert res.returncode != 0 and "never run it on Render" in res.stderr


def test_fixture_mode_serves_saved_responses_and_says_so():
    res = _run({"USE_FIXTURES": "1"})
    assert res.returncode == 0, res.stderr[-2000:]
    out = json.loads(res.stdout)
    body = out["body"]
    assert out["status"] == 200 and out["header"] == "saved-test-responses"
    assert body["fixture_mode"] is True and body["warnings"][0].startswith("FIXTURE MODE")
    assert all("[SAVED TEST RESPONSE]" in s["name"] for s in body["sources"] if s["id"] != "user")
    assert all(s["status"] == "ok" for s in body["sources"])
    assert {r["id"]: r["status"] for r in body["rules"]}["rain_deficit"] != "unknown"
    assert body["forecast_hourly"]["hours"], "frozen clock should line up with the saved forecast"
    assert out["other_status"] == 404  # only Dharwad has saved responses
