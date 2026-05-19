@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 找不到虚拟环境，请先安装依赖
    pause
    exit /b 1
)

:: 自动构建前端（如果 dist 不存在或源码有更新）
echo 正在检查前端构建...
where npm >nul 2>&1
if %errorlevel% equ 0 (
    if not exist "frontend\dist\index.html" (
        echo 首次运行，正在构建前端...
        cd frontend && npm install && npm run build && cd ..
    )
) else (
    echo [警告] 未找到 npm，跳过前端构建
)

echo 正在启动服务 http://127.0.0.1:9000
echo 关闭此窗口 = 停止服务
echo.

".venv\Scripts\python.exe" backend\main.py

echo.
echo 服务已停止。若上面报错，常见原因：9000 端口被占用，先双击 stop.bat
pause
