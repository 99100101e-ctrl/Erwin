@echo off
:: BTC Trading Advisor — Lanceur Windows
:: Double-cliquer sur ce fichier pour démarrer le programme
setlocal

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend

echo.
echo ============================================================
echo   BTC Trading Advisor — Démarrage...
echo ============================================================

:: ---------- Backend ----------
echo.
echo [1/3] Préparation du backend Python...
cd /d "%BACKEND%"

if not exist ".venv" (
    echo   Création de l'environnement virtuel...
    python -m venv .venv
    if errorlevel 1 (
        echo ERREUR : Python n'est pas installé ou introuvable.
        echo Télécharge Python sur https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo   Backend prêt.

:: ---------- Frontend ----------
echo.
echo [2/3] Préparation du frontend React...
cd /d "%FRONTEND%"

if not exist "node_modules" (
    echo   Installation des packages npm (première fois, ~1 minute)...
    npm install --silent
    if errorlevel 1 (
        echo ERREUR : Node.js n'est pas installé ou introuvable.
        echo Télécharge Node.js sur https://nodejs.org/
        pause
        exit /b 1
    )
)

if not exist "build" (
    echo   Build de production en cours...
    npm run build
)

echo   Frontend prêt.

:: ---------- Lancement ----------
echo.
echo [3/3] Lancement des services...
echo.
echo   Backend  ^-^> http://localhost:8000
echo   Frontend ^-^> http://localhost:3000
echo   API docs ^-^> http://localhost:8000/docs
echo.
echo   Fermer les deux fenêtres noires pour arrêter le programme.
echo ============================================================
echo.

:: Démarrer le backend dans une nouvelle fenêtre
start "BTC Advisor - Backend" cmd /k "cd /d "%BACKEND%" && call .venv\Scripts\activate.bat && python main.py"

:: Attendre que le backend soit prêt
timeout /t 3 /nobreak >nul

:: Démarrer le frontend dans une nouvelle fenêtre
start "BTC Advisor - Frontend" cmd /k "cd /d "%FRONTEND%" && npx serve -s build -l 3000"

:: Attendre que le frontend soit prêt puis ouvrir le navigateur
timeout /t 3 /nobreak >nul
start http://localhost:3000

echo   Programme lancé. Appuie sur une touche pour fermer cette fenêtre.
pause >nul
