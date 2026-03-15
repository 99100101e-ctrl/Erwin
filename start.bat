@echo off
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

title BTC Trading Advisor - Strategie E

echo.
echo  ============================================================
echo    BTC Trading Advisor - Strategie E
echo    Dossier : %ROOT%
echo  ============================================================

:: ---------- Verification Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python non trouve. Installez Python 3.10+ et cochez
    echo  "Add Python to PATH".
    echo  https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ---------- Verification Node.js ----------
node --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Node.js non trouve. Installez Node.js LTS.
    echo  https://nodejs.org/
    pause
    exit /b 1
)

:: ---------- Venv Python ----------
echo.
echo  [1/4] Preparation backend Python...
if not exist "%ROOT%\backend\.venv" (
    echo        Creation du venv...
    python -m venv "%ROOT%\backend\.venv"
)
call "%ROOT%\backend\.venv\Scripts\activate.bat"
pip install -q -r "%ROOT%\backend\requirements.txt"
echo        OK.

:: ---------- npm + build ----------
echo.
echo  [2/4] Installation des dependances npm...
cd /d "%ROOT%\frontend"
if not exist "node_modules" (
    npm install
)

echo.
echo  [3/4] Build React production...
npm run build
echo        OK.

:: ---------- Lancement ----------
echo.
echo  [4/4] Lancement...
echo.
echo   Backend  -^> http://localhost:8000
echo   Frontend -^> http://localhost:3000
echo   API docs -^> http://localhost:8000/docs
echo.
echo  ============================================================

start "BTC - Backend" "%ROOT%\_backend.bat"
timeout /t 5 /nobreak >nul
start "BTC - Frontend" "%ROOT%\_frontend.bat"
timeout /t 4 /nobreak >nul
start "" "http://localhost:3000"

echo.
echo  Services lances. Fermez les fenetres Backend et Frontend pour arreter.
pause
