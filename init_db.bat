@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
echo Work package 1: backend lead runs ONCE on shared MySQL.
echo Creates EMPTY business tables (no demo seed).
echo.
".venv\Scripts\python.exe" scripts\init_db.py
echo.
pause
