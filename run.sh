#!/usr/bin/env sh
# Local dev server (macOS/Linux). Usage: ./run.sh
set -e
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements-dev.txt
[ -f web/out/index.html ] || (cd web && npm ci && npm run build)
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
