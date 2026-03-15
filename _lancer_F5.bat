@echo off
title Erwin F5 — Lancement
echo.
echo  Demarrage Erwin F5...
echo  Backend  : http://localhost:8000
echo  Frontend : http://localhost:3000
echo.

set ROOT=%~dp0
set VENV=%ROOT%backend\.venv\Scripts\activate.bat

start "Erwin F5 Backend"  cmd /k "cd /d %ROOT%backend && call %VENV% && python main.py"
timeout /t 3 /nobreak >nul
start "Erwin F5 Frontend" cmd /k "cd /d %ROOT%frontend && npx serve -s build -l 3000"

timeout /t 2 /nobreak >nul
start http://localhost:3000

exit
