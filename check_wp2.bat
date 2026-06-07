@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found.
    echo Please run setup.bat first, or create the virtual environment before checking WP2.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\check_wp2.py
echo.
pause
