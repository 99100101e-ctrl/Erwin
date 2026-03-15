@echo off
title BTC62WR — Frontend (port 3001)
cd /d "%~dp0frontend"
npx serve -s build -l 3001
pause
