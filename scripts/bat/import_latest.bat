@echo off
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" goto find_latest
echo ERROR: Run setup.bat first
pause
exit /b 1

:find_latest
set "LATEST="
for /f "delims=" %%f in ('dir /b /o-d "data\samples\posts_*.json" 2^>nul') do (
    set "LATEST=data\samples\%%f"
    goto found
)

:found
if defined LATEST goto import
echo ERROR: No posts_*.json found. Run crawl.bat first
pause
exit /b 1

:import
echo Importing %LATEST%
".venv\Scripts\python.exe" scripts\import_posts.py "%LATEST%"
echo.
echo Done. Restart run.bat and refresh browser
pause
