@echo off
cd /d "%~dp0frontend"
npx serve -s build -l 3000
pause
