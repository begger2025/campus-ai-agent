@echo off
REM Thin ASCII wrapper; real logic in sync_opinion_core.py (UTF-8 safe paths).
REM Direction is MAIN -> SUB (back-port). MAIN is the single source of truth and is never written.
REM No args = dry-run (safe). Pass --apply to actually write into the subproject.
"%~dp0..\.venv\Scripts\python.exe" "%~dp0sync_opinion_core.py" %*
