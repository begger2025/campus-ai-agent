@echo off
cd /d "%~dp0"
echo Local SQLite dev only — do NOT use on shared MySQL.
".venv\Scripts\python.exe" scripts\seed_demo.py
pause
