@echo off
rem Demo fallback: run backend on local SQLite snapshot (no shared MySQL needed).
rem Build snapshot first: .venv\Scripts\python.exe scripts\make_demo_snapshot.py
cd /d "%~dp0"

if not exist "data\campus_demo.db" (
    echo [demo] data\campus_demo.db not found. Run: .venv\Scripts\python.exe scripts\make_demo_snapshot.py
    pause
    exit /b 1
)

set CAMPUS_DEMO_MODE=1
set PYTHONIOENCODING=utf-8
echo [demo] serving on http://127.0.0.1:9000 with local SQLite snapshot
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 9000
