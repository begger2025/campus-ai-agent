# One-click deploy to Alibaba Cloud ECS (preserves remote .env)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\deploy_to_ecs.ps1
#        可选参数：-HostIp <服务器IP> -Zip <本机zip路径>（默认值即当前线上环境）
# 前置：本机已能 ssh root@<HostIp>；zip 为排除 .venv/node_modules/.git 的精简包。
# 实操记录见 docs/deploy-ecs.md。
param(
    [string]$HostIp = "8.134.250.107",
    [string]$Zip = "$env:USERPROFILE\Desktop\campus-ai-agent-deploy.zip"
)
$ErrorActionPreference = "Stop"
$RemoteDir = "/opt/campus"
$AppDir = "$RemoteDir/campus-ai-agent-main"

if (-not (Test-Path $Zip)) {
    Write-Host "ERROR: zip not found: $Zip"
    Write-Host "Ask AI to rebuild the deploy zip first."
    exit 1
}

Write-Host "==> Upload $Zip ..."
scp $Zip "root@${HostIp}:${RemoteDir}/campus-ai-agent-deploy.zip"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Remote update (keep .env, reinstall deps if needed, restart) ..."
$remote = @"
set -e
cd $RemoteDir
# backup env
if [ -f $AppDir/.env ]; then cp $AppDir/.env /tmp/campus.env.bak; fi
rm -rf ${AppDir}.old
if [ -d $AppDir ]; then mv $AppDir ${AppDir}.old; fi
unzip -o campus-ai-agent-deploy.zip
# restore env
if [ -f /tmp/campus.env.bak ]; then
  cp /tmp/campus.env.bak $AppDir/.env
else
  echo 'WARNING: no previous .env; create one with APP_HOST=0.0.0.0'
fi
# ensure APP_HOST
if [ -f $AppDir/.env ]; then
  sed -i 's/^APP_HOST=.*/APP_HOST=0.0.0.0/' $AppDir/.env
  grep -q '^APP_HOST=' $AppDir/.env || echo 'APP_HOST=0.0.0.0' >> $AppDir/.env
fi
cd $AppDir
# python venv (reuse old if same major, else recreate)
if [ ! -x .venv/bin/python ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv .venv
  else
    python3 -m venv .venv
  fi
fi
. .venv/bin/activate
pip install -U pip -q
pip install -r requirements.txt -q
# frontend: use packaged dist if present; rebuild only if missing
if [ ! -f frontend/dist/index.html ]; then
  cd frontend && npm install && npm run build && cd ..
fi
# systemd
if [ ! -f /etc/systemd/system/campus-ai.service ]; then
  cat >/etc/systemd/system/campus-ai.service <<'EOF'
[Unit]
Description=Campus AI Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/campus/campus-ai-agent-main
Environment=PATH=/opt/campus/campus-ai-agent-main/.venv/bin
ExecStart=/opt/campus/campus-ai-agent-main/.venv/bin/python backend/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable campus-ai
fi
# stop any foreground leftover on 9000
fuser -k 9000/tcp 2>/dev/null || true
systemctl restart campus-ai
sleep 2
systemctl --no-pager -l status campus-ai | head -n 20
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9000/ || true
echo DONE
"@

ssh "root@$HostIp" $remote
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Deploy finished. Open: http://$HostIp:9000"
Write-Host "URL does not change after redeploy."
