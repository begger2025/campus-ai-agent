# 一键全量回归：三套测试 + 前端构建，一条命令看全绿。
#
# 用法（仓库根目录，Windows PowerShell 5.1+）：
#   .\check.ps1                 # 全部四步
#   .\check.ps1 -SkipFrontend   # 跳过前端构建
#   .\check.ps1 -SkipSubrepo    # 跳过子仓（机器上没有子仓时）
#   .\check.ps1 -SkipCrawler    # 跳过爬虫测试
#
# 设计约定：
# - 四步各自独立计时与判绿，全部跑完再汇总（不 fail-fast，一次看清所有红灯）；
# - 退出码 = 失败步数，CI/脚本可直接消费；
# - 测试均零网络依赖（项目纪律），本脚本不需要外网。

param(
    [switch]$SkipCrawler,
    [switch]$SkipSubrepo,
    [switch]$SkipFrontend
)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'

$Root = $PSScriptRoot
$SubrepoBackend = 'D:\桌面文件\软件工程大作业\campus-opinion-agent\backend'
$Results = @()
$TotalWatch = [System.Diagnostics.Stopwatch]::StartNew()

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "=== [$Name] ===" -ForegroundColor Cyan
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    & $Body
    $code = $LASTEXITCODE
    $watch.Stop()
    $status = 'OK'
    if ($code -ne 0) { $status = "FAILED($code)" }
    $script:Results += [pscustomobject]@{
        Step = $Name; Status = $status; Seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    }
}

# 1. 主仓后端 unittest（backend/tests，零网络）
Invoke-Step '后端 unittest' {
    Set-Location $Root
    & "$Root\.venv\Scripts\python.exe" -m unittest discover -s backend/tests -t . -q
}

# 2. 爬虫 pytest（MediaCrawler 独立 venv）
if (-not $SkipCrawler) {
    Invoke-Step '爬虫 pytest' {
        Set-Location "$Root\MediaCrawler"
        & "$Root\MediaCrawler\.venv\Scripts\python.exe" -m pytest tests -q
    }
}

# 3. 子仓 unittest（Agent 评测子项目）
if (-not $SkipSubrepo) {
    if (Test-Path $SubrepoBackend) {
        Invoke-Step '子仓 unittest' {
            Set-Location $SubrepoBackend
            & "$SubrepoBackend\.venv\Scripts\python.exe" -m unittest discover -s tests -q
        }
    } else {
        Write-Host "子仓目录不存在，跳过：$SubrepoBackend" -ForegroundColor Yellow
        $Results += [pscustomobject]@{ Step = '子仓 unittest'; Status = 'SKIPPED(无子仓)'; Seconds = 0 }
    }
}

# 4. 前端构建（构建通过 = 模板/脚本/样式静态检查通过）
if (-not $SkipFrontend) {
    Invoke-Step '前端构建' {
        Set-Location "$Root\frontend"
        & npm.cmd run build
    }
}

Set-Location $Root
$TotalWatch.Stop()

Write-Host ""
Write-Host "===== 回归汇总 =====" -ForegroundColor Cyan
$Results | ForEach-Object {
    $color = 'Green'
    if ($_.Status -like 'FAILED*') { $color = 'Red' }
    elseif ($_.Status -like 'SKIPPED*') { $color = 'Yellow' }
    Write-Host ("  {0,-14} {1,-14} {2}s" -f $_.Step, $_.Status, $_.Seconds) -ForegroundColor $color
}
Write-Host ("  总耗时 {0}s" -f [math]::Round($TotalWatch.Elapsed.TotalSeconds, 1))

$failed = @($Results | Where-Object { $_.Status -like 'FAILED*' })
if ($failed.Count -gt 0) {
    Write-Host "[FAIL] $($failed.Count) 步失败。" -ForegroundColor Red
} else {
    Write-Host "[OK] 全绿。" -ForegroundColor Green
}
exit $failed.Count
