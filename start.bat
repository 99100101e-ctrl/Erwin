@echo off
:: ============================================================
::  BTC Trading Advisor — Strategie E
::  Lanceur Windows — Double-cliquer pour demarrer
:: ============================================================
setlocal EnableDelayedExpansion

:: Chemin automatique base sur l'emplacement du fichier
set "ROOT=%~dp0"
if "!ROOT:~-1!"=="\" set "ROOT=!ROOT:~0,-1!"

set "BACKEND=!ROOT!\backend"
set "FRONTEND=!ROOT!\frontend"
set "VENV=!BACKEND!\.venv"

title BTC Trading Advisor - Strategie E

echo.
echo  ============================================================
echo    BTC Trading Advisor - Strategie E (TP1 proche + Breakeven)
echo    Dossier : !ROOT!
echo  ============================================================

:: ---------- Verification Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python n'est pas installe.
    echo  Telechargez-le sur : https://www.python.org/downloads/
    echo  Cochez "Add Python to PATH" lors de l'installation.
    echo.
    pause
    exit /b 1
)

:: ---------- Verification Node.js ----------
node --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Node.js n'est pas installe.
    echo  Telechargez-le sur : https://nodejs.org/  (version LTS)
    echo.
    pause
    exit /b 1
)

:: ---------- Backend : environnement virtuel ----------
echo.
echo  [1/4] Preparation du backend Python...
cd /d "!BACKEND!"

if not exist "!VENV!" (
    echo        Creation du venv ^(premiere fois uniquement^)...
    python -m venv "!VENV!"
)

call "!VENV!\Scripts\activate.bat"
pip install -q -r "!BACKEND!\requirements.txt"
echo        Backend pret.

:: ---------- Frontend : npm + build production ----------
echo.
echo  [2/4] Preparation du frontend React...
cd /d "!FRONTEND!"

if not exist "!FRONTEND!\node_modules" (
    echo        Installation npm ^(premiere fois, ~2 minutes^)...
    npm install
)

echo  [3/4] Build de production en cours...
call npm run build
echo        Build termine.

:: ---------- Lancement ----------
echo.
echo  [4/4] Lancement des services...
echo.
echo   Backend  -^> http://localhost:8000
echo   Frontend -^> http://localhost:3000
echo   API docs -^> http://localhost:8000/docs
echo.
echo   Fermez les fenetres "Backend" et "Frontend" pour arreter.
echo  ============================================================
echo.

:: Fenetre Backend
set "CMD_BACKEND=cd /d "!BACKEND!" && call "!VENV!\Scripts\activate.bat" && python main.py"
start "BTC Advisor Backend" cmd /k "!CMD_BACKEND!"

:: Attendre que le backend demarre
timeout /t 5 /nobreak >nul

:: Fenetre Frontend (serveur de production stable)
set "CMD_FRONTEND=cd /d "!FRONTEND!" && node node_modules\serve\bin\serve.js -s build -l 3000"
start "BTC Advisor Frontend" cmd /k "!CMD_FRONTEND!"

:: Ouvrir le navigateur
timeout /t 4 /nobreak >nul
start "" "http://localhost:3000"

echo  Programme lance avec succes.
echo  Appuyez sur une touche pour fermer cette fenetre.
pause >nul
