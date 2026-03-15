@echo off
:: ============================================================
::  BTC Trading Advisor — Stratégie E
::  Lanceur Windows — Double-cliquer pour démarrer
:: ============================================================
setlocal

:: Chemin automatique basé sur l'emplacement du fichier
set ROOT=%~dp0
:: Supprimer le \ final si présent
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

set BACKEND=%ROOT%\backend
set FRONTEND=%ROOT%\frontend

title BTC Trading Advisor — Stratégie E

echo.
echo  ============================================================
echo    BTC Trading Advisor — Stratégie E (TP1 proche + Breakeven)
echo    Dossier : %ROOT%
echo  ============================================================

:: ---------- Vérification Python ----------
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Python n'est pas installé.
    echo  Télécharge-le sur : https://www.python.org/downloads/
    echo  Coche "Add Python to PATH" lors de l'installation.
    echo.
    pause
    exit /b 1
)

:: ---------- Vérification Node.js ----------
node --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERREUR] Node.js n'est pas installé.
    echo  Télécharge-le sur : https://nodejs.org/  (version LTS)
    echo.
    pause
    exit /b 1
)

:: ---------- Backend : environnement virtuel ----------
echo.
echo  [1/4] Vérification de l'environnement Python...
cd /d "%BACKEND%"

if not exist ".venv" (
    echo        Création du venv (première fois seulement)...
    python -m venv .venv
)

call "%BACKEND%\.venv\Scripts\activate.bat"

echo  [2/4] Installation des dépendances Python...
pip install -q -r "%BACKEND%\requirements.txt"
echo        Backend prêt.

:: ---------- Frontend : npm + build ----------
echo.
echo  [3/4] Vérification du frontend React...
cd /d "%FRONTEND%"

if not exist "node_modules" (
    echo        Installation npm (première fois, ~2 minutes)...
    npm install --silent
)

if not exist "build" (
    echo        Build de production en cours...
    npm run build
    echo        Build terminé.
)
echo        Frontend prêt.

:: ---------- Lancement ----------
echo.
echo  [4/4] Lancement des services...
echo.
echo   Backend  ^-^> http://localhost:8000
echo   Frontend ^-^> http://localhost:3000
echo   API docs ^-^> http://localhost:8000/docs
echo.
echo   Fermer les fenêtres "Backend" et "Frontend" pour arrêter.
echo  ============================================================
echo.

:: Ouvrir backend dans une nouvelle fenêtre
start "BTC Advisor — Backend" cmd /k "cd /d "%BACKEND%" && call "%BACKEND%\.venv\Scripts\activate.bat" && python main.py"

:: Attendre que le backend démarre
timeout /t 4 /nobreak >nul

:: Ouvrir frontend dans une nouvelle fenêtre
start "BTC Advisor — Frontend" cmd /k "cd /d "%FRONTEND%" && npx serve -s build -l 3000"

:: Attendre que le frontend démarre puis ouvrir le navigateur
timeout /t 3 /nobreak >nul
start "" "http://localhost:3000"

echo  Programme lancé avec succès.
echo  Appuie sur une touche pour fermer cette fenêtre de lancement.
pause >nul
