@echo off
title BTC Advisor Setup
echo ============================================================
echo   BTC Trading Advisor — First-Time Setup
echo ============================================================
echo.
echo This will install all required dependencies.
echo Python 3.9+ and Node.js 18+ must be installed.
echo.

REM ── 1. Create Python virtual environment ──────────────────────
echo [1/4] Creating Python virtual environment...
cd /d D:\btc-advisor\backend
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Could not create Python venv. Is Python 3.9+ installed?
    pause
    exit /b 1
)

REM ── 2. Install Python dependencies ────────────────────────────
echo [2/4] Installing Python dependencies...
D:\btc-advisor\backend\.venv\Scripts\pip install --upgrade pip
D:\btc-advisor\backend\.venv\Scripts\pip install -r D:\btc-advisor\backend\requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python packages.
    pause
    exit /b 1
)

REM ── 3. Install Node.js dependencies ───────────────────────────
echo [3/4] Installing Node.js dependencies...
cd /d D:\btc-advisor\frontend
npm install
if errorlevel 1 (
    echo ERROR: Failed to install npm packages. Is Node.js 18+ installed?
    pause
    exit /b 1
)

REM ── 4. Done ───────────────────────────────────────────────────
echo [4/4] Setup complete!
echo.
echo ============================================================
echo   Setup successful!
echo   Double-click LAUNCH.bat to start the application.
echo ============================================================
echo.
pause
