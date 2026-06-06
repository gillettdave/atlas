# Project Atlas — create venvs (if needed), install deps, open API + Streamlit in new windows.
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File .\start-atlas-dev.ps1
#
# Prereqs: PostgreSQL running, backend\.env configured, migrations applied once:
#   cd backend; .\.venv\Scripts\Activate.ps1; alembic upgrade head

param(
    [string] $RepoRoot = $PSScriptRoot,
    [string] $Python = "python",
    [int] $ApiPort = 8001
)

$ErrorActionPreference = "Stop"

$backend = Join-Path $RepoRoot "backend"
$frontend = Join-Path $RepoRoot "frontend"

if (-not (Test-Path $backend)) { throw "backend not found at: $backend" }
if (-not (Test-Path $frontend)) { throw "frontend not found at: $frontend" }

function Ensure-Venv {
    param([string] $Dir, [string] $RequirementsRel)
    $venvPy = Join-Path $Dir ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "Creating venv: $Dir\.venv"
        Push-Location $Dir
        try {
            & $Python -m venv .venv
        } finally {
            Pop-Location
        }
    }
    $pip = Join-Path $Dir ".venv\Scripts\pip.exe"
    & $pip install -q -r (Join-Path $Dir $RequirementsRel)
}

Write-Host "Ensuring backend venv + requirements..."
Ensure-Venv -Dir $backend -RequirementsRel "requirements.txt"

Write-Host "Ensuring frontend venv + requirements..."
Ensure-Venv -Dir $frontend -RequirementsRel "requirements.txt"

if (-not (Test-Path (Join-Path $backend ".env"))) {
    Write-Warning "backend\.env missing — copy from .env.example if you have one, or create .env with ATLAS_DATABASE_URL (see backend\README.md)."
}

$apiBase = "http://127.0.0.1:$ApiPort"

Write-Host "Starting API on $apiBase (new window)..."
Start-Process pwsh -WorkingDirectory $backend -ArgumentList @(
    "-NoExit",
    "-Command",
    ". .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --host 127.0.0.1 --port $ApiPort"
)

Start-Sleep -Seconds 2

Write-Host "Starting Streamlit on http://localhost:8501 (new window)..."
Start-Process pwsh -WorkingDirectory $frontend -ArgumentList @(
    "-NoExit",
    "-Command",
    ". .\.venv\Scripts\Activate.ps1; `$env:ATLAS_API_BASE='$apiBase'; streamlit run streamlit_app/Home.py"
)

Write-Host "Done. Close the two pwsh windows to stop servers."
