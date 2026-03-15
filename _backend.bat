@echo off
cd /d "%~dp0backend"
call "%~dp0backend\.venv\Scripts\activate.bat"
python main.py
pause
