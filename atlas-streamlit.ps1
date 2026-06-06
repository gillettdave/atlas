# Atlas Streamlit -- Desktop operator UI (optional)
# Called by "Launch Atlas.bat". Do not run this directly unless debugging.

$Host.UI.RawUI.WindowTitle = "Atlas -- Streamlit UI"

Write-Host ""
Write-Host "  =================================================" -ForegroundColor Yellow
Write-Host "    Atlas Streamlit UI  (desktop operator)"        -ForegroundColor Yellow
Write-Host "    Opens automatically at http://localhost:8501"  -ForegroundColor DarkYellow
Write-Host "  =================================================" -ForegroundColor Yellow
Write-Host ""

# PSScriptRoot = directory containing this script = project root
Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "  ERROR: .venv not found in $((Get-Location).Path)" -ForegroundColor Red
    Read-Host "  Press Enter to exit"
    exit 1
}

.\.venv\Scripts\python.exe -m streamlit run streamlit_app\Home.py
