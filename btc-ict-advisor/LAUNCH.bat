@echo off
start "ICT Backend" cmd /k "cd /d D:\btc-ict-advisor && backend\.venv\Scripts\activate && cd backend && uvicorn main:app --host 0.0.0.0 --port 8001 --reload"
timeout /t 5 /nobreak >nul
start "ICT Frontend" cmd /k "cd /d D:\btc-ict-advisor\frontend && set DISABLE_ESLINT_PLUGIN=true && npm start"
timeout /t 8 /nobreak >nul
start "" "http://localhost:3000"
