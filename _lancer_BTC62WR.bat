@echo off
title BTC62WR — Lancement
echo.
echo  Demarrage BTC62WR...
echo  Backend  : http://localhost:8001
echo  Frontend : http://localhost:3001
echo.

set ROOT=%~dp0
set VENV=%ROOT%backend\.venv\Scripts\activate.bat

start "BTC62WR Backend"  cmd /k "cd /d %ROOT%backend && call %VENV% && set BACKEND_PORT=8001 && set FRONTEND_PORT=3001 && python main.py"
timeout /t 3 /nobreak >nul
start "BTC62WR Frontend" cmd /k "cd /d %ROOT%frontend && npx serve -s build -l 3001"

timeout /t 2 /nobreak >nul
start http://localhost:3001

exit
