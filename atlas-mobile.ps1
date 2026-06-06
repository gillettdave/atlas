# Atlas Mobile -- Expo / React Native
# Called by "Launch Atlas.bat". Do not run this directly unless debugging.

$Host.UI.RawUI.WindowTitle = "Atlas -- Mobile (Expo)"

Write-Host ""
Write-Host "  =================================================" -ForegroundColor Green
Write-Host "    Atlas Mobile  (Expo + React Native)"           -ForegroundColor Green
Write-Host "    Open Expo Go on your phone to connect."        -ForegroundColor DarkGreen
Write-Host "    'Android SDK not found' warnings = harmless."  -ForegroundColor DarkGray
Write-Host "  =================================================" -ForegroundColor Green
Write-Host ""

# Add Node to PATH for this session
$env:PATH = "C:\Program Files\nodejs;" + $env:PATH

# PSScriptRoot = directory containing this script = project root
Set-Location "$PSScriptRoot\mobile"

if (-not (Test-Path ".\node_modules")) {
    Write-Host "  node_modules not found -- running npm install..." -ForegroundColor Yellow
    & "C:\Program Files\nodejs\npm.cmd" install --legacy-peer-deps
}

& "C:\Program Files\nodejs\npx.cmd" expo start --host localhost
