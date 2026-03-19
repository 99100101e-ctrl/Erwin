@echo off
title APEX Bot v2 — Lancement
cd /d "%~dp0"

:: Vérifier que Python est accessible
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERREUR : Python introuvable.
    echo Installe Python 3.11+ depuis https://www.python.org
    echo et coche "Add to PATH" lors de l'installation.
    echo.
    pause
    exit /b 1
)

:: Lancer le script principal
python _lancer_apex.py

if errorlevel 1 (
    echo.
    echo Le bot s'est arrete avec une erreur. Voir le message ci-dessus.
    pause
)
