#!/usr/bin/env bash
# 校声智枢 一键部署/更新脚本（在服务器上运行）
# 首次部署见 docs/deploy-runbook.md 的初始化步骤；此脚本用于每次「拉新代码 → 重新上线」。
#
# 用法：cd /opt/campus-ai-agent && bash deploy/deploy.sh
set -euo pipefail

APP_DIR="/opt/campus-ai-agent"
cd "$APP_DIR"

echo "==> [1/5] 拉取最新代码"
git pull --ff-only

echo "==> [2/5] 构建前端（vite build → frontend/dist）"
cd frontend
npm ci
npm run build
cd "$APP_DIR"

echo "==> [3/5] 安装后端依赖（轻量档：requirements.txt 不含 torch）"
./.venv/bin/pip install -q -r requirements.txt

echo "==> [4/5] 数据库结构校验（幂等，仅建缺失的表；不动存量数据）"
# 共享 RDS 已建表并有数据时此步为空操作；新库/新表才生效。
# 若不想让部署脚本碰库，注释掉下面一行，改为人工执行迁移。
./.venv/bin/python scripts/init_db.py || echo "  (init_db 跳过或已是最新)"

echo "==> [5/5] 重启后端 + 重载 Nginx"
sudo systemctl restart campus-backend
sudo systemctl reload nginx

echo ""
echo "==> 健康检查"
sleep 2
curl -fsS --noproxy '*' http://127.0.0.1:9000/api/ping && echo "" || {
    echo "!! /api/ping 未通过，查日志：journalctl -u campus-backend -n 50 --no-pager"
    exit 1
}
echo "==> 部署完成 ✅"
