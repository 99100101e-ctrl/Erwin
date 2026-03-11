@echo off
title BTC Trading Advisor Launcher
echo ============================================================
echo   BTC Trading Advisor — Starting...
echo ============================================================
echo.

REM ── Window 1: Python FastAPI Backend ──────────────────────────
start "BTC Advisor Backend" cmd /k "D:\btc-advisor\backend\.venv\Scripts\activate.bat && cd /d D:\btc-advisor\backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

REM Wait 2 seconds for backend to start
timeout /t 2 /nobreak >nul

REM ── Window 2: React Frontend ───────────────────────────────────
start "BTC Advisor Frontend" cmd /k "cd /d D:\btc-advisor\frontend && npm start"

REM ── Wait 8 seconds then open browser ──────────────────────────
echo Waiting for services to start...
timeout /t 8 /nobreak >nul

echo Opening browser...
start "" "http://localhost:3000"

echo.
echo ============================================================
echo   Both services are running.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/docs
echo.
echo   To stop: close the backend and frontend windows.
echo ============================================================
