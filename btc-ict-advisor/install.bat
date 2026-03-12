@echo off
echo Installing BTC ICT Advisor...
cd /d D:\btc-ict-advisor\backend
python -m venv .venv
call .venv\Scripts\activate
pip install fastapi uvicorn websockets httpx pandas numpy python-dateutil --break-system-packages
cd ..\frontend
npm install
echo Installation complete! Run LAUNCH.bat to start.
pause
