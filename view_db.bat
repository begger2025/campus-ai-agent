@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
chcp 65001 >nul
".venv\Scripts\python.exe" scripts\view_db.py
echo.
pause
