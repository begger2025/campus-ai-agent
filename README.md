# campus-ai-agent

## 第二周后端 Smoke Test

工作包 10 提供了一键后端 smoke test，用于复现公共舆情主链路：

```text
MediaCrawler 数据 -> raw_posts -> processed_posts -> public_events -> 管理员审核 -> 用户查看 published 事件 -> 用户反馈 -> 管理员日志
```

在主项目目录运行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_backend.ps1 -Limit 200 -Port 9010
```

验收说明见 [docs/backend-smoke-test.md](docs/backend-smoke-test.md)。

第二周 smoke test 不覆盖个人事项 Agent，不检查 `personal_advices`、`/api/agent/personal/impact`、`/api/users/{user_id}/advices`。

> **请在本目录 `campus-ai-agent-main` 下开发。**  
> 桌面上的 `campus-ai-agent` 为旧版（仅 HTML 占位前端），功能已合并到本仓库，请勿混用。

一个面向校园场景的 AI Agent 项目，主要包括：

- **公共校园舆情分析 Agent** — 采集、清洗、分析校园公开舆情，输出风险预警
- **个人事项安排 Agent** — 结合课表、DDL、活动推送个性化日程建议
- 数据采集、后端服务、前端展示等模块

# 第二周：工作包 1（统一共享 MySQL + 历史数据规则）

在 [工作包 0](docs/work-package-0-shared-mysql.md) 基础上升级，详见 [工作包 1](docs/work-package-1-shared-mysql.md)。

| 命令 | 用途 |
|------|------|
| `init_db.bat` | 后端负责人执行一次（空表） |
| `verify_db.bat` | 连接检查 |
| `check_wp1.bat` | 工作包 1 验收 |

**GitHub 仓库：** https://github.com/begger2025/campus-ai-agent

## 项目目标（第一阶段）

1. 搭建协作基础设施（仓库、任务看板）
2. 确定技术栈并统一开发环境
3. 跑通最小闭环：爬虫采集样本 → 后端存储 → 前端展示 → Agent 分析

## 系统架构概览

```
数据接入层        数据存储层        后端调度层        Agent 层         前端展示层
  ┌─────┐         ┌────────┐        ┌──────────┐     ┌──────────┐     ┌──────────┐
  │爬虫  │ ──→    │MySQL/  │ ──→   │FastAPI   │──→  │舆情 Agent │──→ │Vue 3     │
  │样本  │        │SQLite  │        │ REST API │     │个人 Agent │    │Element+ │
  └─────┘         └────────┘        └──────────┘     └──────────┘     └──────────┘
```

## 目录结构

```text
campus-ai-agent/
├─ README.md              # 本文件
├─ docs/                  # 项目文档
│   ├─ api.md             # 接口文档
│   ├─ architecture.md    # 系统架构
│   ├─ database.md        # 数据库设计
│   ├─ dev-guide.md       # 开发规范
│   ├─ data-sources.md    # 数据源说明
│   └─ field-spec.md      # 字段说明
├─ backend/               # FastAPI 后端
│   ├─ main.py            # 应用入口
│   ├─ models.py          # ORM 数据模型
│   ├─ schemas.py         # Pydantic Schema
│   ├─ database.py        # 数据库连接
│   ├─ seed.py            # 样本数据导入
│   └─ routers/
│       └─ api.py         # /ping、/posts 接口
├─ frontend/              # Vue 3 前端（见 frontend/README.md）
│   ├─ src/
│   │   ├─ views/         # 首页、舆情分析页、个人事项页
│   │   ├─ components/    # 通用组件
│   │   ├─ api/           # 后端接口封装
│   │   └─ mock/          # 演示用 mock 数据
│   └─ README.md
├─ crawler/               # 数据采集脚本
├─ agent/                 # AI Agent 分析模块
├─ data/                  # 样本数据（JSON）
├─ scripts/               # 工具脚本
├─ .env.example           # 环境变量模板
├─ requirements.txt       # Python 依赖
├─ setup.bat              # 首次安装（venv + 依赖 + 前端构建）
├─ run.bat                # 启动 http://127.0.0.1:9000（API + 前端一体）
├─ dev.bat                # 开发模式（9000 后端 + 5173 前端）
├─ crawl.bat              # 运行爬虫
├─ import_latest.bat      # 将最新 samples JSON 导入数据库
├─ save_weibo_login.bat   # 保存微博登录态
└─ stop.bat               # 释放 9000 端口
```

## 与旧版 `campus-ai-agent` 的区别

| 项目 | 旧版 `campus-ai-agent` | 本目录 `campus-ai-agent-main` |
|------|------------------------|-------------------------------|
| 前端 | 单页占位 HTML | 完整 Vue 3 + Element Plus |
| `run.bat` 打开页面 | 显示「后端正常」卡片 | 完整仪表盘 / 舆情 / 个人事项 |
| 爬虫 / 后端代码 | 基本相同 | 相同，并增加批处理工具链 |
| 数据 | 可迁移 `data/campus.db`、cookies | 以本目录 `data/` 为准 |

详见 [docs/architecture.md](docs/architecture.md)、[data/README.md](data/README.md)。

## Windows 快速开始

```text
1. 双击 setup.bat          # 仅首次
2. 双击 save_weibo_login.bat  # 微博真实爬取，仅首次
3. 双击 save_tieba_login.bat  # 贴吧真实爬取，仅首次
4. 双击 crawl.bat          # 采集 → data/samples/
5. 双击 import_latest.bat  # 导入 → data/campus.db
6. 双击 run.bat              # 浏览器打开 http://127.0.0.1:9000
```

开发联调可改用 `dev.bat`（后端 9000 + 前端 5173，Vite 已代理 `/posts`）。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · SQLite / MySQL |
| 前端 | Vue 3 · Element Plus · Vue Router · Axios · Vite |
| 爬虫 | Python · Playwright（参考 MediaCrawler） |
| Agent | Python · LLM API · JSON 输入输出 |
| 文档 | Markdown |

## 本地启动方式

### 一键（Windows）

| 脚本 | 作用 |
|------|------|
| `setup.bat` | 创建 `.venv`、安装依赖、Playwright、`npm run build` |
| `run.bat` | 生产/演示：单端口 9000（需已 build） |
| `dev.bat` | 开发：9000 + 5173 双窗口 |
| `crawl.bat` | 爬虫采集 |
| `import_latest.bat` | 导入最新 `data/samples/posts_*.json` |

### 命令行

```bash
# 后端（端口 9000）
.venv\Scripts\python.exe backend\main.py

# 前端开发（端口 5173，需后端已启动）
cd frontend && npm run dev

# 爬虫与导入
.venv\Scripts\python.exe crawler\run_once.py
.venv\Scripts\python.exe scripts\import_posts.py data\samples\posts_xxx.json
```

前端开发服务器代理 `/health`、`/ping`、`/posts` 到 `http://127.0.0.1:9000`。  
后端未启动时，帖子列表自动降级为 mock 数据。

## 相关文档

- [系统架构](docs/architecture.md) — 模块划分、数据流、与旧版对比
- [data 目录说明](data/README.md) — 数据库、样本、Cookie
- [前端说明](frontend/README.md) — Vue 3 前端结构、页面说明、启动方式
- [开发规范](docs/dev-guide.md) — 分支、提交、命名、接口格式
- [接口文档](docs/api.md) — 后端 REST 接口
- [数据库设计](docs/database.md) — 表结构说明
- [数据源说明](docs/data-sources.md) · [字段说明](docs/field-spec.md)
- [爬虫交付/对接](docs/crawl-handoff.md) · [爬虫异常记录](docs/crawl-issues.md)

## 分工说明（第一周）

| 角色 | 主要职责 |
|------|----------|
| 1号 后端协调 | 仓库搭建、FastAPI 骨架、数据库设计、团队规范 |
| 2号 数据接入 | 爬虫脚本、样本 JSON、字段文档、异常记录 |
| 3号 Agent 算法 | 输入输出设计、Prompt 初稿、最小分析脚本 |
| 4号 前端展示 | Vue 3 骨架、三页面、mock 数据展示 ✅ |

## 第一周验收状态

- [x] GitHub 仓库与目录结构
- [x] FastAPI 后端骨架（`/ping`、`/posts`）
- [x] Vue 3 前端骨架（首页、舆情分析页、个人事项页）
- [x] Mock 数据 + 后端接口对接（含降级）
- [x] 数据库设计初稿（`raw_posts`、`processed_posts`、`public_events`、`user_tasks`、`user_schedules`）
- [x] 爬虫样本数据（`data/samples/`）
- [ ] Agent 分析脚本（`agent/` 目录已预留，见 `agent/README.md`）
- [x] README 与相关文档
