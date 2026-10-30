#!/usr/bin/env sh
# Local dev server (macOS/Linux). Usage: ./run.sh
set -e
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r backend/requirements-dev.txt
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
