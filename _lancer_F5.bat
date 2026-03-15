@echo off
title Erwin F5 — Lancement
echo.
echo  Demarrage Erwin F5...
echo  Backend  : http://localhost:8000
echo  Frontend : http://localhost:3000
echo.

start "Erwin F5 Backend"  cmd /k "cd /d "%~dp0backend" && call "%~dp0backend\.venv\Scripts\activate.bat" && python main.py"
timeout /t 3 /nobreak >nul
start "Erwin F5 Frontend" cmd /k "cd /d "%~dp0frontend" && npx serve -s build -l 3000"

timeout /t 2 /nobreak >nul
start http://localhost:3000

exit
