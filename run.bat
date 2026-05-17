@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到虚拟环境，请先安装依赖
    pause
    exit /b 1
)

echo 正在启动服务 http://127.0.0.1:9000
echo 关闭此窗口 = 停止服务
echo.

".venv\Scripts\python.exe" backend\main.py

echo.
echo 服务已停止。若上面报错，常见原因：9000 端口被占用，先双击 stop.bat
pause
