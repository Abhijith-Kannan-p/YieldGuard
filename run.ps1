# Local dev server (Windows). Usage: .\run.ps1
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -r backend\requirements-dev.txt
if (-not (Test-Path web\out\index.html)) { Push-Location web; npm ci; npm run build; Pop-Location }
Set-Location backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
