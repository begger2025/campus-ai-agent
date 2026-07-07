# Compare local project with GitHub team repo (read-only clone).
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\merge_compare.ps1 -RepoUrl "https://github.com/org/repo.git"
#   powershell -ExecutionPolicy Bypass -File scripts\merge_compare.ps1 -RepoUrl "..." -Branch main

param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$LocalRoot = Split-Path $PSScriptRoot -Parent
$UpstreamRoot = Join-Path (Split-Path $LocalRoot -Parent) "campus-ai-agent-upstream"

Write-Host "Local:    $LocalRoot"
Write-Host "Upstream: $UpstreamRoot"
Write-Host "Repo:     $RepoUrl ($Branch)"
Write-Host ""

if (Test-Path $UpstreamRoot) {
    Write-Host "Removing old upstream clone..."
    Remove-Item -Recurse -Force $UpstreamRoot
}

Write-Host "Cloning..."
git clone --depth 1 -b $Branch $RepoUrl $UpstreamRoot 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "Clone failed. Try -Branch master or check URL/access."
    exit 1
}

$skip = @(
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "*.pyc", "campus.db", "campus_db_preview.md"
)

function Get-RelFiles($root) {
    Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = $_.FullName.Substring($root.Length + 1)
            $skipRel = $false
            foreach ($part in @(".venv", "node_modules", "__pycache__", ".git")) {
                if ($rel -like "*$part*") { $skipRel = $true; break }
            }
            if ($rel -eq ".env") { $skipRel = $true }
            if ($rel -like "data\cookies\*") { $skipRel = $true }
            if ($rel -eq "data\campus.db") { $skipRel = $true }
            -not $skipRel
        } |
        ForEach-Object { $_.FullName.Substring($root.Length + 1).Replace("\", "/") }
}

$localFiles = @(Get-RelFiles $LocalRoot)
$remoteFiles = @(Get-RelFiles $UpstreamRoot)
$localSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$localFiles)
$remoteSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$remoteFiles)

$onlyRemote = $remoteFiles | Where-Object { -not $localSet.Contains($_) } | Sort-Object
$onlyLocal = $localFiles | Where-Object { -not $remoteSet.Contains($_) } | Sort-Object
$both = $localFiles | Where-Object { $remoteSet.Contains($_) } | Sort-Object

$diffBoth = @()
foreach ($f in $both) {
    $lp = Join-Path $LocalRoot ($f -replace "/", "\")
    $rp = Join-Path $UpstreamRoot ($f -replace "/", "\")
    if ((Test-Path $lp) -and (Test-Path $rp)) {
        $lh = (Get-FileHash $lp -Algorithm MD5).Hash
        $rh = (Get-FileHash $rp -Algorithm MD5).Hash
        if ($lh -ne $rh) { $diffBoth += $f }
    }
}

Write-Host "========== ONLY ON GITHUB (copy into your project) =========="
$onlyRemote | ForEach-Object { Write-Host "  + $_" }
Write-Host "Count: $($onlyRemote.Count)"
Write-Host ""

Write-Host "========== ONLY LOCAL (your new work, keep for commit) =========="
$onlyLocal | ForEach-Object { Write-Host "  * $_" }
Write-Host "Count: $($onlyLocal.Count)"
Write-Host ""

Write-Host "========== BOTH SIDES MODIFIED (manual merge / conflict risk) =========="
$diffBoth | ForEach-Object { Write-Host "  ! $_" }
Write-Host "Count: $($diffBoth.Count)"
Write-Host ""

Write-Host "Upstream clone kept at: $UpstreamRoot"
Write-Host "See docs/merge-with-team-github.md for push steps."
