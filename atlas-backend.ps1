# Atlas Backend -- FastAPI / Uvicorn
# Called by "Launch Atlas.bat". Do not run this directly unless debugging.

$Host.UI.RawUI.WindowTitle = "Atlas -- Backend"

Write-Host ""
Write-Host "  =================================================" -ForegroundColor Cyan
Write-Host "    Atlas Backend  (FastAPI + Uvicorn)"            -ForegroundColor Cyan
Write-Host "    http://localhost:8000  |  /docs for API browser" -ForegroundColor DarkCyan
Write-Host "  =================================================" -ForegroundColor Cyan
Write-Host ""

# PSScriptRoot = directory containing this script = project root
Set-Location "$PSScriptRoot\backend"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "  ERROR: .venv not found in $((Get-Location).Path)" -ForegroundColor Red
    Write-Host "  Create it with: python -m venv .venv" -ForegroundColor Yellow
    Write-Host "  Then install:   .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    Read-Host "  Press Enter to exit"
    exit 1
}

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
