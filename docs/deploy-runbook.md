# 校声智枢 公网部署操作手册（Runbook）

> 目标：把本地运行的项目部署到阿里云轻量应用服务器，评审者输入网址即可在浏览器访问三类角色功能。
> 方案定档：**阿里云轻量服务器（同 RDS 地域）+ Nginx 反代 + systemd 托管 + 轻量档（不装 torch）+ 同区连 RDS**。
> 配套文件：`deploy/nginx-campus.conf`、`deploy/campus-backend.service`、`deploy/deploy.sh`。

---

## 0. 部署架构一图

```
浏览器 ──HTTP──> [阿里云轻量服务器]
                    Nginx :80
                    ├── /            → frontend/dist（静态，vue-router 兜底）
                    ├── /api/        → 反代 127.0.0.1:9000（uvicorn，仅本地监听）
                    └── /uploads/    → 反代 127.0.0.1:9000（投稿图片）
                                            │
                                     uvicorn (systemd 托管，单进程)
                                            │
                                     ├── 阿里云 RDS MySQL（同地域内网/公网）
                                     └── 出网 → 中转站 LLM / 智谱 GLM
```

安全边界：**只有 Nginx 对公网开放**（80 端口）；后端 uvicorn 只监听 127.0.0.1，外网碰不到；SSH 22 端口限来源。

---

## 1. 前置准备（约 10 分钟）

1. **购买服务器**：阿里云「轻量应用服务器」，规格 **2 核 2G**（轻量档够用），系统镜像 **Ubuntu 22.04**。
   - **地域必须与 RDS 同区**：登录 RDS 控制台看实例地域（本项目 RDS 主机名 `rm-wz98...`），服务器选同一地域，内网互通、延迟最低、抖动消失。
2. **记录服务器公网 IP**（下文记作 `<SERVER_IP>`）。
3. **放行端口**：轻量服务器「防火墙」放行 **80/TCP**（HTTP）与 **22/TCP**（SSH，建议限你自己的 IP）。**不要**放行 9000（后端不对公网暴露）。

---

## 2. ⚠️ 最关键的一步：RDS 白名单

**九成"连不上数据库"都栽在这里。** RDS 默认拒绝陌生 IP。

1. RDS 控制台 → 数据安全性 → 白名单设置；
2. 把**服务器的内网 IP**（同地域优先走内网）或**公网 IP** 加入白名单；
3. 若用内网连接，`.env` 里 `DATABASE_URL` 的主机换成 RDS 的**内网地址**（控制台可查），更快更稳。

验证（在服务器上，第 5 步装好 venv 后）：
```bash
./.venv/bin/python scripts/verify_db_connection.py
# 期望：[OK] SELECT 1 succeeded / raw_posts row count: ...
```

---

## 3. 安装系统环境（约 5 分钟）

```bash
# 以 root 或 sudo 用户执行
sudo apt update
sudo apt install -y nginx python3.11 python3.11-venv git curl
# Node.js 20（前端构建）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
# 创建部署用户与目录
sudo useradd -m -s /bin/bash campus || true
sudo mkdir -p /opt/campus-ai-agent
sudo chown -R campus:campus /opt/campus-ai-agent
```

---

## 4. 拉代码 + 传凭据

```bash
# 切到部署用户
sudo -iu campus
cd /opt
git clone <你的GitHub仓库地址> campus-ai-agent   # 或 git clone 后 checkout 目标分支
cd campus-ai-agent
```

**`.env` 绝不进 git，单独安全传输**（在你本地电脑执行）：
```bash
# Windows 本地 → 服务器（scp）
scp .env campus@<SERVER_IP>:/opt/campus-ai-agent/.env
```
上服务器后收紧权限：
```bash
chmod 600 /opt/campus-ai-agent/.env
```
`.env` 里确认部署相关项：`APP_HOST=127.0.0.1`、`APP_PORT=9000`、`DATABASE_URL=<RDS内网连接串>`、LLM 三组 key、`LLM_FALLBACK_*`。

---

## 5. 后端环境（轻量档，约 5 分钟）

```bash
cd /opt/campus-ai-agent
python3.11 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt   # 不含 torch，自动走规则降级
# 验证连库（见第 2 步）
./.venv/bin/python scripts/verify_db_connection.py
```

> 轻量档说明：不装 `sentence-transformers`，语义"补召回"降级为字面搜索；**对话助手、事件、风险、预审等核心 AI 全部正常**（走中转站 LLM，不依赖本地 torch）。

---

## 6. 构建前端

```bash
cd /opt/campus-ai-agent/frontend
npm ci
npm run build          # 产出 frontend/dist
```

> 若服务器内存紧（2G）构建被 OOM 杀掉：可在**本地 build 好 dist 再 scp 上去**，或临时加 swap。

---

## 7. 部署 Nginx + systemd

```bash
# Nginx 站点
sudo cp /opt/campus-ai-agent/deploy/nginx-campus.conf /etc/nginx/sites-available/campus
sudo ln -sf /etc/nginx/sites-available/campus /etc/nginx/sites-enabled/campus
sudo rm -f /etc/nginx/sites-enabled/default      # 去掉默认站点
sudo nginx -t && sudo systemctl reload nginx

# 后端 systemd
sudo cp /opt/campus-ai-agent/deploy/campus-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now campus-backend
```

---

## 8. 验证上线

```bash
# 后端本地健康
curl --noproxy '*' http://127.0.0.1:9000/api/ping        # 期望 {"code":0,...}
# 进程状态
sudo systemctl status campus-backend --no-pager
```
浏览器打开 **http://\<SERVER_IP\>/** —— 应看到登录页；用演示账号登录走一遍三类角色。

**演示账号**（`.env` 里配置的，或库里已有）：
- 普通用户：`user` / `user123456`
- 管理员：`admin` / `admin123456`

> 答辩前建议在库里保留干净的演示账号，删掉 wp8/wp9/smoke 等验收测试号。

---

## 9. 关于 HTTPS / 域名 / 备案（诚实说明 + 路线图）

| 形态 | 能否明天就用 | 说明 |
|------|:---:|------|
| **http://\<IP\> 直连**（本手册主路径） | ✅ 立即 | 裸 IP 访问**不需要备案**，最快上线 |
| https + 域名（境内服务器） | ❌ 需数天 | 境内服务器域名走 80/443 **必须 ICP 备案**，周期数天，赶不上 |
| https + 域名（阿里云香港/海外） | ✅ 可选 | 海外服务器免备案，certbot 一键 HTTPS；代价是连境内 RDS 跨地域、需加香港 IP 白名单 |

**结论**：明天用 **http://\<IP\> 直连**跑通演示（功能 100% 满足）；**HTTPS + 域名 + 备案**作为「运维路线图」的下一步写进运维文档——主动说明这个真实约束，本身就是运维成熟度的体现。若要演示 HTTPS，改用香港轻量服务器 + certbot（见 `nginx-campus.conf` 底部附录）。

---

## 10. 日常运维手册

| 场景 | 命令 |
|------|------|
| 看后端实时日志 | `journalctl -u campus-backend -f` |
| 重启后端 | `sudo systemctl restart campus-backend` |
| **更新上线**（拉新代码重新部署） | `cd /opt/campus-ai-agent && bash deploy/deploy.sh` |
| 重载 Nginx（改配置后） | `sudo nginx -t && sudo systemctl reload nginx` |
| 数据库连通性自检 | `./.venv/bin/python scripts/verify_db_connection.py` |
| 演示快照兜底（RDS 挂时） | 见下「降级预案」 |

### 更新流程（deploy.sh 做了什么）
拉代码 → 构建前端 → 装依赖 → 幂等校验表结构 → 重启后端 → 重载 Nginx → `/api/ping` 健康检查。任一步失败即停并提示查日志。

### 备份与回滚
- **代码回滚**：`git log` 找上一个好版本 → `git checkout <hash>` → `bash deploy/deploy.sh`；
- **数据备份**：RDS 控制台已有自动备份；重要节点可 `mysqldump` 手动导出；
- **配置回滚**：Nginx/systemd 配置在 git 里（`deploy/`），改坏了 `git checkout` 复原。

### 降级预案（运维成熟度体现）
1. **RDS 抖动**：本项目支持 SQLite 演示快照 —— `python scripts/make_demo_snapshot.py` 生成本地库，`.env` 切 `DATABASE_URL` 到 SQLite，`systemctl restart campus-backend` 即切换，演示不中断；
2. **LLM 主通道故障**：已内建备胎链（gpt-5.4 失败自动切 GLM），无需人工干预；
3. **云部署整体故障**：保底可在本地机跑 + 内网穿透（cpolar/frp）临时出一个公网址，`docs/` 另附。

---

## 11. 安全检查清单（上线前逐项确认）

- [ ] `.env` 权限 600，不在 git 里（`git status` 不显示）
- [ ] 后端只监听 127.0.0.1（systemd 里 `--host 127.0.0.1`），9000 端口未对公网放行
- [ ] 防火墙只开 80 + 22（22 限来源 IP）
- [ ] RDS 白名单只加了服务器 IP，未开 `0.0.0.0/0`
- [ ] 演示账号密码非弱口令（答辩后连同 3 个 API key 一并轮换）
- [ ] 删除库里的测试验收账号（wp8/wp9/smoke 等）

---

*本手册配套 `deploy/` 下三个配置文件；执行遇阻把报错发我，我帮你定位。*
