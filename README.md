# campus-ai-agent

一个面向校园场景的 AI Agent 项目，主要包括：

- **公共校园舆情分析 Agent** — 采集、清洗、分析校园公开舆情，输出风险预警
- **个人事项安排 Agent** — 结合课表、DDL、活动推送个性化日程建议
- 数据采集、后端服务、前端展示等模块

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
├─ run.bat                # Windows 一键启动后端
└─ crawl.bat              # Windows 一键运行爬虫
```

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · SQLite / MySQL |
| 前端 | Vue 3 · Element Plus · Vue Router · Axios · Vite |
| 爬虫 | Python · Playwright（参考 MediaCrawler） |
| Agent | Python · LLM API · JSON 输入输出 |
| 文档 | Markdown |

## 本地启动方式

### 后端

```bash
# 安装依赖
pip install -r requirements.txt

# 启动后端（端口 9000）
python backend/main.py
# 或 Windows 双击
run.bat
```

### 前端

```bash
cd frontend
npm install
npm run dev          # 访问 http://localhost:5173
```

前端开发服务器会自动代理 `/posts`、`/health` 到 `http://127.0.0.1:9000`。  
如后端未启动，前端会自动降级到 mock 数据展示，不影响页面预览。

### 爬虫

```bash
python crawler/run_once.py
# 或 Windows 双击
crawl.bat
# 导入样本数据到数据库
python scripts/import_posts.py data/samples/posts_week1_sample.json
```

## 相关文档

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
- [x] Agent 分析脚本初稿（`agent/`）
- [x] README 与相关文档
