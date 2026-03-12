@echo off
setlocal

echo Installing BTC ICT Advisor...
cd /d D:\btc-ict-advisor\backend || goto :error

py -3.11 -m venv .venv
if errorlevel 1 (
  echo [ERROR] Python 3.11 not found. Install Python 3.11.x and retry.
  goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :error

cd /d D:\btc-ict-advisor\frontend || goto :error
npm install
if errorlevel 1 goto :error

echo Installation complete! Run LAUNCH.bat to start.
pause
exit /b 0

:error
echo Installation failed.
pause
exit /b 1
