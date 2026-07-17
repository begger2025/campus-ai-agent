# deploy — 公网部署资产

Aliyun ECS 上的生产部署三件套。完整流程（首次初始化、HTTPS、回滚）见
[docs/deploy-runbook.md](../docs/deploy-runbook.md)。

| 文件 | 作用 | 放到服务器哪里 |
|------|------|----------------|
| `nginx-campus.conf` | Nginx 站点配置：唯一公网入口，直接服务前端 `dist/`，`/api` 与 `/uploads` 反代给本机 uvicorn | `/etc/nginx/sites-available/campus` → 软链到 `sites-enabled/` |
| `campus-backend.service` | systemd 单元：管理后端进程（开机自启、崩溃自动拉起） | `/etc/systemd/system/` |
| `deploy.sh` | 一键更新脚本：拉代码 → 构建前端 → 装依赖 → 幂等建表 → 重启后端 + 重载 Nginx → 健康检查 | 仓库内直接运行 `bash deploy/deploy.sh` |

## 设计要点

- **轻量档部署**：服务器不装 torch，`requirements.txt` 即全部依赖；语义补召回自动降级为
  字面搜索，其余 AI 功能不受影响。
- **同源零 CORS**：前端 axios 用相对路径 `/api`，与站点同源，无需任何跨域配置。
- **失败即停**：`deploy.sh` 带 `set -euo pipefail`，任一步（包括建表）失败立即中止，
  不会带病重启服务；末尾 `/api/ping` 健康检查不过会给出查日志命令。

## 生产安全要求（公网部署前必做）

`.env.example` 中的 `admin/admin123456`、`user/user123456`、`JWT_SECRET_KEY=replace-with-a-random-secret`
是**本地演示默认值**。公网部署必须在服务器的 `.env` 中：

1. 更换 `ADMIN_PASSWORD` 为强口令；
2. 生成随机 `JWT_SECRET_KEY`（如 `openssl rand -hex 32`）；
3. 视情况设 `ENSURE_DEMO_USER=false` 关闭演示用户。
