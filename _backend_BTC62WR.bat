@echo off
title BTC62WR — Backend (port 8001)
cd /d "%~dp0backend"
call "%~dp0backend\.venv\Scripts\activate.bat"
set BACKEND_PORT=8001
set FRONTEND_PORT=3001
python main.py
pause
