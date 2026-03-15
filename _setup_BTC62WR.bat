@echo off
title BTC62WR — Setup (rebuild frontend pour port 8001)
echo.
echo =========================================================
echo  BTC62WR — Premiere installation
echo  Ce script reconstruit le frontend pour pointer sur
echo  le backend port 8001 au lieu de 8000.
echo  A lancer UNE SEULE FOIS apres avoir copie le dossier.
echo =========================================================
echo.

cd /d "%~dp0frontend"

echo [1/2] Installation des dependances npm (si besoin)...
call npm install

echo.
echo [2/2] Build frontend avec REACT_APP_API_URL=http://localhost:8001/api/state ...
set REACT_APP_API_URL=http://localhost:8001/api/state
call npm run build

echo.
echo =========================================================
echo  Setup termine !
echo  Lance maintenant :
echo    _backend_BTC62WR.bat   (backend  port 8001)
echo    _frontend_BTC62WR.bat  (frontend port 3001)
echo =========================================================
echo.
pause
