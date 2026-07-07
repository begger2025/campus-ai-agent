@echo off
cd /d "%~dp0"
echo ========================================
echo  Campus AI Agent - Setup
echo  Dir: %CD%
echo ========================================
echo.

if exist ".venv\Scripts\python.exe" goto install_deps
echo [1/5] Creating Python venv...
python -m venv .venv
if errorlevel 1 goto python_missing
goto install_deps

:python_missing
echo ERROR: Python not found. Install Python 3.12 or newer.
pause
exit /b 1

:install_deps
echo [2/5] Installing Python packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 goto pip_failed

echo [3/5] Installing Playwright Chromium...
".venv\Scripts\playwright.exe" install chromium

if exist ".env" goto env_ok
echo [4/5] Copy .env.example to .env
copy /Y ".env.example" ".env" >nul
goto frontend

:env_ok
echo [4/5] .env already exists, skipped

:frontend
where npm >nul 2>&1
if errorlevel 1 goto no_npm
echo [5/5] npm install and build frontend...
pushd frontend
call npm install
if errorlevel 1 goto npm_failed
call npm run build
popd
if exist "frontend\dist\index.html" goto done
echo ERROR: frontend build failed
pause
exit /b 1

:no_npm
echo [5/5] WARN: npm not found, skipped frontend build
echo       Install Node.js 18 then run:
echo       cd frontend
echo       npm install
echo       npm run build
goto done

:npm_failed
popd
echo ERROR: npm install failed
pause
exit /b 1

:pip_failed
echo ERROR: pip install failed
pause
exit /b 1

:done
echo.
echo Setup finished.
echo   setup.bat  - first time only
echo   run.bat    - open http://127.0.0.1:9000
echo   dev.bat    - dev mode port 5173 and 9000
echo   crawl.bat  - run crawler
echo.
pause
