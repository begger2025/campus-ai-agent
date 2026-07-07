@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto check_frontend
echo ERROR: Run setup.bat first
pause
exit /b 1

:check_frontend
echo Checking frontend build...
if exist "frontend\dist\index.html" goto start_server

where npm >nul 2>&1
if errorlevel 1 goto no_npm_no_dist

echo Building frontend dist...
pushd frontend
call npm install
if errorlevel 1 goto npm_failed
call npm run build
popd
if exist "frontend\dist\index.html" goto start_server
echo ERROR: frontend build failed
pause
exit /b 1

:no_npm_no_dist
echo ERROR: npm missing and no frontend\dist. Run setup.bat
pause
exit /b 1

:npm_failed
popd
echo ERROR: npm install failed
pause
exit /b 1

:start_server
echo.
echo Starting http://127.0.0.1:9000
echo Press Ctrl+C or close this window to stop
echo.

".venv\Scripts\python.exe" backend\main.py

echo.
echo Server stopped. If port busy, run stop.bat first
pause
