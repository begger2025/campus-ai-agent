# 公网部署实录（ECS 直连方案，已上线）

> 本文由**部署负责人**撰写，记录实际完成的阿里云公网部署过程，供交付与复现。
> 敏感信息一律使用占位符，不写入真实密码、Token、完整连接串。
>
> **当前线上地址：<http://8.134.250.107:9000>**（演示账号见 §9；
> `/api/ping` 已验证返回 `database: campus_ai_agent`，即连通共享 RDS）。
> 后续更新上线用仓库脚本 [`scripts/deploy_to_ecs.ps1`](../scripts/deploy_to_ecs.ps1) 一键完成。
>
> 与 [deploy-runbook.md](deploy-runbook.md)（Nginx 反代方案）的关系：本文是**实际采用**的
> 直连方案；Nginx/HTTPS 为升级路径，对照分析见交付物
> [06-软件配置与运维文档 §5.4](coursework/06-软件配置与运维文档.md)。

---

## 1. 部署架构简述

本项目将 Web 应用部署在阿里云 **ECS** 上：浏览器通过公网 IP 访问服务器 **9000** 端口；同一进程内由 **uvicorn / FastAPI** 提供后端 API，并托管前端构建产物 `frontend/dist`；业务数据连接团队已有的阿里云 **RDS MySQL**（非本机 SQLite）。未使用 Nginx，未绑定域名，未配置 HTTPS。

```text
评审者浏览器
    │  http://<服务器公网IP>:9000
    ▼
阿里云 ECS（Ubuntu 22.04，2 核 2G，华南3·广州）
    │  uvicorn 监听 0.0.0.0:9000
    │  ├─ 静态前端：frontend/dist（SPA）
    │  └─ API：/api/* → FastAPI（backend.main:app）
    ▼
阿里云 RDS MySQL（库名 campus_ai_agent）
    （ECS 公网 IP 已加入 RDS 白名单；跨地域，使用 RDS 外网地址连接）
```

进程由 **systemd** 单元 `campus-ai` 托管，SSH 断开后服务仍保持运行；开机可自启。

---

## 2. 服务器与环境准备

### 2.1 实例规格（实际选用）

| 项 | 实际值 |
|----|--------|
| 产品形态 | 云服务器 ECS（免费试用/个人版路径开通） |
| 规格 | **2 vCPU / 2 GiB**（经济型） |
| 地域可用区 | **华南3（广州）** |
| 系统盘 | ESSD Entry 约 40 GiB |
| 操作系统 | **Ubuntu 22.04**（64 位） |
| 登录方式 | SSH，用户 `root`，自定义密码 |

**说明：** 初次创建时曾误选 **Windows Server 2022**，导致本机 `ssh root@...` 出现 `Connection refused`。后通过控制台 **更换操作系统** 为 Ubuntu 22.04，并重新设置 root 密码，此后 PowerShell 可正常 SSH。

### 2.2 安全组（入方向）

为使外网可访问网站、本机可运维，入方向放行：

| 协议 | 端口 | 来源 | 用途 |
|------|------|------|------|
| 自定义 TCP | `9000/9000` | `0.0.0.0/0` | 网站 HTTP 访问 |
| SSH | `22/22` | `0.0.0.0/0` | 远程登录 |

未额外开放「全部端口」类规则（曾误选后按建议删除）。

**为什么：** 应用直接监听 9000，不经 80/443；列表里没有 9000 预设时，使用「自定义 TCP」手工填写。

### 2.3 本机登录服务器

在 Windows PowerShell：

```powershell
ssh root@<服务器公网IP>
```

首次连接确认指纹后输入 `yes`，再输入实例 root 密码。

### 2.4 安装的基础软件

在服务器上实际执行过（含 `apt` 安装过程中可能出现的 needrestart 对话框：Tab → Ok → Enter 即可）：

```bash
apt update
apt install -y python3 python3-venv python3-pip git curl wget build-essential unzip

# Node.js 20（用于前端构建）
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
```

因系统自带 Python 为 **3.10**，而项目代码使用 `datetime.UTC`（需 **Python ≥ 3.11**），额外安装了 **Python 3.12**：

```bash
apt install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update
apt install -y python3.12 python3.12-venv python3.12-dev
```

实际运行环境版本（部署时）：

| 软件 | 版本 |
|------|------|
| Python（venv 内） | **3.12.x** |
| Node.js | **20.x** |
| npm | 随 Node 20 安装 |

**初期未安装** `sentence-transformers` / `torch`（轻量档，语义补召回降级为字面搜索）；**后经服务器扩容装齐**，语义检索已启用并实测通过（"东校"≈"东校区"、"饭堂"≈"食堂"模糊问法均能命中），线上与本地能力一致。

---

## 3. 数据库连接配置

### 3.1 使用的数据库

- 类型：**阿里云 RDS MySQL**
- 库名：`campus_ai_agent`
- 应用账号：`campus_app`（密码以团队交接为准，本文不写明文）
- 未使用 SQLite 作为线上主库（本地曾临时用过 SQLite 降级，**公网 ECS 线上为 RDS**）

### 3.2 让 ECS 能连上 RDS

1. 在 RDS 控制台 → **白名单设置** → 将 ECS **公网 IP** 加入白名单（形如 `<服务器公网IP>` 或 `<服务器公网IP>/32`）。
2. 因 RDS 与 ECS **不在同一地域**（RDS 在深圳侧、ECS 在广州），连接串使用 RDS **外网地址**，而非内网地址。
3. 团队白名单中曾存在 `0.0.0.0/0`（全网开放）；建议长期应删除该项，仅保留必要 IP。功能上只要 ECS IP 在名单内即可连通。

**验证（公网侧已验证）：** 访问 `/api/ping` 返回中 `database` 字段为 `campus_ai_agent`，说明后端已连上共享库。

### 3.3 `.env` 中的关键项

服务器上 `.env` 至少包含（值为占位）：

```env
APP_HOST=0.0.0.0
APP_PORT=9000
DATABASE_URL=mysql+pymysql://campus_app:<数据库密码>@<RDS外网主机>:3306/campus_ai_agent?charset=utf8mb4
SEED_DEMO_ON_START=false
```

**为什么 `APP_HOST=0.0.0.0`：** 若保持 `127.0.0.1`，服务只监听本机，公网 IP 无法访问。

---

## 4. 后端部署

### 4.1 代码如何上到服务器

1. 本机将项目打成**精简压缩包**（排除 `.venv`、`node_modules`、`.git`、爬虫大数据等），避免整目录 `scp` 传数小时。
2. 使用 `scp` 上传 zip 到服务器目录，例如 `/opt/campus/`。
3. 服务器上 `unzip` 解压到 `/opt/campus/campus-ai-agent-main`。

后续更新一律使用仓库内脚本 [`scripts/deploy_to_ecs.ps1`](../scripts/deploy_to_ecs.ps1)：上传 zip、保留远端 `.env`、按需重建依赖、重启服务、健康检查。

**踩坑：** 首次直接 `scp -r` 整个项目时，把本机 `.venv` 下大量 `.pyc` 一并传输，进度极慢；中断后改为精简 zip（约数十 MB 量级）再传。

### 4.2 虚拟环境与依赖

```bash
cd /opt/campus/campus-ai-agent-main
# 删除错误的旧 venv（若有）
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

**为什么用 3.12 重建：** 在 Python 3.10 下启动报错
`ImportError: cannot import name 'UTC' from 'datetime'`，升级解释器后解决。

### 4.3 进程托管（systemd）

使用 systemd 服务名：**`campus-ai`**。

单元文件要点（路径以实际为准）：

```ini
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
```

常用命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable campus-ai
sudo systemctl start campus-ai    # 或 restart
sudo systemctl status campus-ai
```

启动入口对应代码：`python backend/main.py`（内部 uvicorn，app 为 `backend.main:app`，端口由 `.env` 的 `APP_PORT` 控制，默认 9000）。

**效果：** 关闭 SSH 后网站仍可访问；支持开机自启。

---

## 5. 前端部署

1. 服务器上进入 `frontend` 目录执行构建：

```bash
cd /opt/campus/campus-ai-agent-main/frontend
npm install
npm run build
```

2. 构建产物目录：`frontend/dist`（含 `index.html` 与 `assets/*`）。
3. **未单独安装 Nginx**。前端静态文件由 FastAPI 在同一 9000 端口托管；前端请求 API 使用相对路径 `/api`，与同源部署一致。

构建时可能出现 Rollup/chunk 体积警告，不影响上线使用。

---

## 6. 对外访问配置

| 项 | 实际情况 |
|----|----------|
| 访问 URL | `http://<服务器公网IP>:9000` |
| 域名 | **无** |
| HTTPS | **未配置**（仅 HTTP） |
| 反向代理 | **无 Nginx**；直连 uvicorn |
| 备案 | **未涉及**（无域名） |

评审者在浏览器输入上述地址即可打开登录页并使用系统。

---

## 7. 上线验证

实际采用的检查方式包括：

1. 服务器日志出现：`Uvicorn running on http://0.0.0.0:9000` 且 `Application startup complete`。
2. 浏览器访问：`http://<服务器公网IP>:9000`，首页可打开。
3. 接口：`http://<服务器公网IP>:9000/api/ping` 返回成功，且数据源指向共享库 `campus_ai_agent`。
4. 关闭 SSH 后再次访问公网地址，页面仍可用（验证 systemd 常驻）。
5. 使用演示账号登录，确认功能可用。

---

## 8. 遇到的问题与解决

| 问题 | 原因 | 解决 |
|------|------|------|
| `ssh: Connection refused` | 实例系统为 Windows，默认无可用 SSH 服务 | 更换操作系统为 Ubuntu 22.04 |
| 误用阿里云账号昵称/账号 ID 当 SSH 密码 | 账号 ID ≠ 实例 root 密码 | 使用「自定义密码」或「重置实例密码」 |
| 安全组快捷项无 9000 | 预设只有 80/443/22 等 | 选「自定义 TCP」，端口填 `9000/9000` |
| `scp` 传项目半小时仍未完 | 上传了本机 `.venv` 等大目录 | Ctrl+C 中断；改传排除 `.venv`/`node_modules` 的 zip |
| `cannot import name 'UTC' from 'datetime'` | 系统 Python 3.10 过旧 | 安装 Python 3.12 并重建 venv |
| `APP_HOST=127.0.0.1` | 默认只绑本机 | 改为 `0.0.0.0` |
| RDS 与 ECS 不同城 | 深圳 RDS + 广州 ECS | 白名单加 ECS 公网 IP，连接串用 RDS **外网**地址 |
| SSH 会话 `Connection reset` | 网络中断 | 重新 `ssh` 登录，环境一般仍保留 |

（本地开发阶段还曾使用 cpolar 做临时穿透；**公网正式方案以 ECS 直连为准，不再依赖本机开机 + cpolar。**）

---

## 9. 演示账号

与项目 README 一致的默认演示账号（部署后若未修改则可用）：

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | `admin` | `admin123456` |
| 普通用户 | `user` | `user123456` |

---

## 附录 A：目录与关键路径

| 路径 | 说明 |
|------|------|
| `/opt/campus/campus-ai-agent-main` | 应用根目录 |
| `/opt/campus/campus-ai-agent-main/.env` | 环境配置（勿提交公开仓库） |
| `/opt/campus/campus-ai-agent-main/.venv` | Python 虚拟环境 |
| `/opt/campus/campus-ai-agent-main/frontend/dist` | 前端构建产物 |
| `/etc/systemd/system/campus-ai.service` | systemd 单元文件 |

## 附录 B：更新代码后的建议流程

即 [`scripts/deploy_to_ecs.ps1`](../scripts/deploy_to_ecs.ps1) 自动化的内容：

1. 本机准备精简 zip（排除 `.venv`/`node_modules`/`.git`）。
2. 上传到服务器并解压/覆盖代码（**保留**服务器已有 `.env`）。
3. 如有前端变更：重新 `npm run build`。
4. `systemctl restart campus-ai`。
5. 公网地址通常**不变**，仍为 `http://<服务器公网IP>:9000`。
