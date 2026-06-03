@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto check_npm
echo ERROR: Run setup.bat first
pause
exit /b 1

:check_npm
where npm >nul 2>&1
if errorlevel 1 goto no_npm
goto start_dev

:no_npm
echo ERROR: npm not found. Install Node.js 18
pause
exit /b 1

:start_dev
if exist "frontend\node_modules" goto launch
echo Installing frontend deps...
pushd frontend
call npm install
popd

:launch
echo Backend: http://127.0.0.1:9000
echo Frontend: http://localhost:5173
echo.

start "Backend9000" cmd /k "cd /d "%~dp0" & .venv\Scripts\python.exe backend\main.py"
timeout /t 2 /nobreak >nul
start "Frontend5173" cmd /k "cd /d "%~dp0frontend" & npm run dev"

echo Two windows opened. Close them to stop.
pause
