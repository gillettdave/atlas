@echo off
setlocal EnableDelayedExpansion
title Project Atlas — Launcher

cls
echo.
echo  =========================================================
echo    PROJECT ATLAS  --  1-Click Launcher
echo  =========================================================
echo.

:: %~dp0 = directory of this .bat file (always the project root)
set "ROOT=%~dp0"
:: Remove trailing backslash so paths look clean in messages
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: ── Step 1: Backend ────────────────────────────────────────
echo  [1/4]  Opening backend window...
start "Atlas -- Backend" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%ROOT%\atlas-backend.ps1"

:: ── Step 2: Wait for backend ───────────────────────────────
echo  [2/4]  Waiting 5 seconds for backend to start...
timeout /t 5 /nobreak > nul

:: ── Step 3: ADB tunnels ────────────────────────────────────
echo  [3/4]  Setting up USB tunnels (phone must be plugged in)...

where adb >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo         WARNING: adb not found in PATH.
    echo         Tunnels could not be set up automatically.
    echo         After plugging in your phone, run manually:
    echo           adb reverse tcp:8081 tcp:8081
    echo           adb reverse tcp:8001 tcp:8001
    echo.
    goto :expo
)

adb reverse tcp:8081 tcp:8081 >nul 2>&1
adb reverse tcp:8001 tcp:8001 >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo         WARNING: adb tunnel failed.
    echo         Phone may not be connected or USB debugging may be off.
    echo         Plug in your phone and run manually:
    echo           adb reverse tcp:8081 tcp:8081
    echo           adb reverse tcp:8001 tcp:8001
    echo.
) else (
    echo         OK -- ports 8081 and 8000 tunnelled.
)

:: ── Step 4: Expo ───────────────────────────────────────────
:expo
echo  [4/4]  Opening Expo window...
start "Atlas -- Mobile" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%ROOT%\atlas-mobile.ps1"

:: ── Step 5: Streamlit (optional) ──────────────────────────
echo.
echo  =========================================================
echo.
echo   Backend and Expo are starting in their own windows.
echo   Open Expo Go on your phone to connect.
echo.
choice /c YN /m "  Also start the Streamlit desktop UI?"
if errorlevel 2 goto :done
if errorlevel 1 (
    echo  Starting Streamlit...
    start "Atlas -- Streamlit" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%ROOT%\atlas-streamlit.ps1"
)

:done
echo.
echo  =========================================================
echo    All done! This window can be closed.
echo.
echo    If the app shows "Connection problem":
echo      1. Make sure the backend window says "Uvicorn running"
echo      2. Re-run:  adb reverse tcp:8001 tcp:8001
echo      3. Shake your phone in Expo Go and tap Reload
echo  =========================================================
echo.
pause
endlocal
