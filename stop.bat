@echo off
echo 正在释放 9000 端口...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo 已结束进程 %%a
)
echo 完成，现在可以重新双击 run.bat
pause
