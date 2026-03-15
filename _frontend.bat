@echo off
cd /d "%~dp0frontend"
node node_modules\serve\bin\serve.js -s build -l 3000
pause
