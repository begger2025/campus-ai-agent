@echo off
REM Thin ASCII wrapper; real logic in sync_opinion_core.py (UTF-8 safe paths).
"%~dp0..\.venv\Scripts\python.exe" "%~dp0sync_opinion_core.py"
