@echo off
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" goto run
echo ERROR: Run setup.bat first
pause
exit /b 1

:run
".venv\Scripts\python.exe" scripts\save_tieba_login.py
pause
