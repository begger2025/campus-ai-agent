param(
    [int]$Limit = 200,
    [int]$Port = 9010,
    [string]$Keyword = "campus",
    [string]$AdminUsername = "smoke_admin",
    [string]$AdminPassword = "smoke_admin_password",
    [string]$UserUsername = "smoke_user",
    [string]$UserPassword = "smoke_user_password"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}

& $Python "scripts\smoke_backend.py" `
    --limit $Limit `
    --port $Port `
    --keyword $Keyword `
    --admin-username $AdminUsername `
    --admin-password $AdminPassword `
    --user-username $UserUsername `
    --user-password $UserPassword

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

exit 0
