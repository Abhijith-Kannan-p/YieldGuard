# Local dev server (Windows). Usage: .\run.ps1
# Saved test responses instead of live APIs (local only):  $env:USE_FIXTURES = "1"; .\run.ps1
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -r backend\requirements-dev.txt
if (-not (Test-Path web\out\index.html)) { Push-Location web; npm ci; npm run build; Pop-Location }
Set-Location backend
$target = if ($env:USE_FIXTURES -eq "1") { "devtools.fixture_server:app" } else { "app.main:app" }
..\.venv\Scripts\python -m uvicorn $target --reload --port 8000
