@echo off
echo Stopping process on port 9000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo Killed PID %%a
)
echo Done. You can run run.bat again
pause
