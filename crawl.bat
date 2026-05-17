@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" crawler\run_once.py %*
pause
