#!/usr/bin/env sh
# Local dev server (macOS/Linux). Usage: ./run.sh
# Saved test responses instead of live APIs (local only):  USE_FIXTURES=1 ./run.sh
set -e
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements-dev.txt
[ -f web/out/index.html ] || (cd web && npm ci && npm run build)
TARGET=app.main:app
[ "${USE_FIXTURES:-0}" = "1" ] && TARGET=devtools.fixture_server:app
cd backend && ../.venv/bin/uvicorn "$TARGET" --reload --port 8000
