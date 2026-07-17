@echo off
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" goto run
echo ERROR: Run setup.bat first
pause
exit /b 1

:run
".venv\Scripts\python.exe" crawler\run_once.py %*
echo.
echo Output: data\samples\
echo Next: import_latest.bat
pause
