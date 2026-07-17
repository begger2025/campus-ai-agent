# 系统架构

本文档描述 `campus-ai-agent-main` 的模块划分与数据流。以本目录为**唯一工作副本**（旧版 `campus-ai-agent` 仅含占位前端，已废弃）。

## 分层架构

```text
数据接入层        数据存储层        后端调度层        Agent 层         前端展示层
  ┌─────┐         ┌────────┐        ┌──────────┐     ┌──────────┐     ┌──────────┐
  │爬虫  │ ──→    │SQLite  │ ──→   │FastAPI   │──→  │舆情 Agent │──→ │Vue 3     │
  │crawler│       │campus.db│       │ REST API │     │(规划中)   │    │Element+ │
  └─────┘         └────────┘        └──────────┘     └──────────┘     └──────────┘
       ↑                                  ↑                                    ↑
  crawl.bat                         run.bat / dev.bat                    run.bat / dev.bat
  import_latest.bat                 :9000                                :9000 或 :5173
```

## 目录职责

| 目录 | 职责 |
|------|------|
| `crawler/` | 微博/贴吧采集，输出 `data/samples/posts_*.json` |
| `scripts/` | 登录态保存、JSON 导入、建库工具 |
| `backend/` | FastAPI、`/health` `/ping` `/posts`，并托管 `frontend/dist` |
| `frontend/` | Vue 3 SPA；开发时 Vite 5173 代理 API 到 9000 |
| `backend/agent/` + `backend/services/` | 舆情 Agent（意图路由、ReAct、语义聚类、引用简报，由子项目同步） |
| `data/` | 运行时数据：数据库、Cookie、爬虫 JSON（见 `data/README.md`） |
| `docs/` | 接口、字段、爬虫、开发规范 |

## 数据流（最小闭环）

```text
1. save_weibo_login.bat  →  data/cookies/weibo_state.json
2. crawl.bat             →  data/samples/posts_YYYYMMDD_HHMMSS.json
3. import_latest.bat     →  data/campus.db (raw_posts 表)
4. run.bat               →  GET /posts → 前端首页 & 舆情页展示
```

## 两种启动模式

### 生产/演示（单端口）

- 脚本：`setup.bat`（首次）→ `run.bat`
- 地址：http://127.0.0.1:9000
- 前端为 `frontend/dist` 静态资源，与 API 同源，无需代理

### 开发（双端口）

- 脚本：`dev.bat`（或分别启动 backend + `cd frontend && npm run dev`）
- 后端：http://127.0.0.1:9000
- 前端：http://localhost:5173
- Vite 将 `/health`、`/ping`、`/posts` 代理到 9000

## 与旧版 `campus-ai-agent` 的差异

| 项目 | 旧版 | 本版 (main) |
|------|------|-------------|
| 前端 | 单文件 `frontend/index.html` 占位 | 完整 Vue 3 应用 |
| `backend/main.py` | 仅返回占位页 | SPA + `dist/` 托管 |
| `run.bat` | 只启 Python | 检查并构建 `dist` |
| 批处理 | 无 setup/dev/import | 有完整工具链 |

## 相关文档

- [接口文档](api.md)
- [数据库设计](database.md)
- [爬虫对接](archive/crawl/crawl-handoff.md)
- [真实采集指南](crawl-real-data.md)
