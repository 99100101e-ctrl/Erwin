@echo off
title BTC62WR — Setup
echo.
echo =========================================================
echo  BTC62WR — Premiere installation
echo  A lancer UNE SEULE FOIS apres avoir copie le dossier.
echo =========================================================
echo.

set ROOT=%~dp0

:: --- Backend : creer le venv et installer les dependances ---
echo [1/3] Creation de l environnement Python (.venv)...
cd /d %ROOT%backend
python -m venv .venv
if errorlevel 1 (
    echo ERREUR : Python introuvable. Installe Python 3.11+ et relance.
    pause & exit /b 1
)

echo [2/3] Installation des dependances Python...
call %ROOT%backend\.venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo ERREUR : pip install a echoue.
    pause & exit /b 1
)

:: --- Frontend : installer npm et rebuild pour port 8001 ---
echo [3/3] Build frontend (port 8001)...
cd /d %ROOT%frontend
call npm install
set REACT_APP_API_URL=http://localhost:8001/api/state
call npm run build
if errorlevel 1 (
    echo ERREUR : npm build a echoue.
    pause & exit /b 1
)

echo.
echo =========================================================
echo  Setup termine ! Lance maintenant : _lancer_BTC62WR.bat
echo =========================================================
echo.
pause
