# 校声智枢 · Campus AI Agent

> 面向校园场景的 **AI 深度融合舆情分析平台**：从社交平台采集校园公开讨论，经清洗、
> 语义聚类、LLM 情绪与风险研判自动生成舆情事件，管理员审核后向全校发布；内置
> 对话式舆情 Agent，支持多轮追问、多步推理与引用溯源的舆情简报。
>
> 《软件工程》课程大作业 · 覆盖需求 / 设计 / 实现 / 演化四个工作域。

---

## 目录

- [核心功能](#核心功能)
- [AI 能力地图（答辩重点）](#ai-能力地图答辩重点)
- [目录结构](#目录结构)
- [快速开始](#快速开始windows)
- [数据采集](#数据采集可选)
- [页面一览](#页面一览19-个视图)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [测试与质量](#测试与质量)
- [部署](#部署)
- [文档索引](#文档索引)
- [已知限制](#已知限制评审须知)

---

## 核心功能

**面向学生 / 普通用户**
- **事件浏览**：已发布舆情事件的列表、详情、代表帖溯源（游客免登录可看）
- **舆情助手（对话 Agent）**：热点问答、风险预警、观点分析、简报生成；支持多轮追问
  （"那有什么风险？"自动继承话题）与 ReAct 多步推理（"对比食堂和宿舍哪个风险高"自主调用多个分析工具）
- **舆情工作台 / 舆情分析**：事件筛选研判、帖子浏览、情绪与风险分布统计
- **我要投稿**：提交线索（文字 + 图片），审核通过后写回数据管线
- **舆情关注 / 反馈**：中高风险事件关注与影响评估，一键提交纠错/补充

**面向管理员**
- **后台概览**：数据管线健康度、事件状态分布、今日工作台一屏总览
- **事件审核**：通过 / 驳回 / 归档 + 审核意见，全程留痕（审核历史时间线）；
  支持**按风险优先排序**、**批量审核**、**AI 预审建议**（建议不落库，发布权始终在人）
- **事件修正**：重命名 / 合并 / 增删成员帖 / 剔除帖子，人工修正加锁防自动管线覆盖
- **证据核验**：针对存疑事件联网检索权威信源、抓取核验、人工终审后入库
- **智能选题**：基于用户提问日志等信号推荐下一轮采集关键词，形成数据闭环
- **数据管理 / 运维中心**：原始帖浏览、采集任务记录、系统日志、用户管理、操作审计

---

## AI 能力地图（答辩重点）

本项目 **不是"传统系统 + 一个聊天机器人"**，AI 贯穿数据管线每一环：

| # | AI 能力 | 所在环节 | 技术路线 | 量化验证 |
|---|---------|----------|----------|----------|
| 1 | 语义事件聚类 | 事件生成 | bge-small-zh 嵌入 + 余弦阈值 | 黄金集 **65.7%** vs 规则 23.7% |
| 2 | LLM 聚类精修 / 近重合并 | 事件生成 | LLM 判"是不是一件事"，拆大桶、具体化标题 | 消融实验留档 |
| 3 | 风险 / 情绪 / 生命周期研判 | 事件研判 | LLM + 规则兜底双通道 | 情绪 75% → **100%** |
| 4 | 对话式舆情助手 | 用户交互 | 意图路由 + 语义检索 + ReAct 多步推理 | 26 题基准 **63/63** |
| 5 | 引用溯源 + Critic 复核 | 可信生成 | 结论强制标注 `[来源:eN]` + 二次核查 | 引用合法率 **100%** |
| 6 | 提示注入防御 | AI 安全 | 爬取内容进 LLM 前对抗性净化 | 对抗测试覆盖 |
| 7 | 智能选题 | 采集闭环 | 用户提问等信号 → 下轮采集关键词 | 数据飞轮 |
| 8 | 联网证据核验 | 事实核查 | 多提供方检索 + 抓取核验 + 人工终审 | SSRF 防护 |
| 9 | LLM 容灾备胎链 | 可靠性 | 主通道失败自动切换备用模型 | 端到端演练 |

**三条 AI 工程治理原则**：
1. **可测量的用算术，需要判断的用 AI**——热度/衰减用确定性算法，"像不像/是不是一件事"才交给 embedding/LLM；
2. **LLM 优先、规则兜底**——9 处 AI 环节全有降级通道，**断网 / 无 API Key 时功能完整**；
3. **AI 产出必须可验证**——金标数据集 + 消融实验 + 引用溯源，拒绝黑盒。

---

## 目录结构

```
campus-ai-agent-main/
├── backend/                后端 FastAPI 应用
│   ├── routers/            9 组路由（auth/api/agent_public/admin/admin_events/
│   │                       admin_evidence/comments/submissions/feedback）
│   ├── services/           业务层（30+ 服务：对话编排/事件修正/证据/LLM 客户端…）
│   ├── agent/
│   │   └── public_opinion_core/   舆情核心算法包（纯标准库，可移植）
│   ├── models*.py          SQLAlchemy 数据模型（业务/审计/证据三域）
│   └── tests/              109 个测试文件、约 1180 个后端测试用例
├── frontend/               Vue 3 + Vite 前端（19 个页面）
│   └── src/{views,components,api,router,auth}/
├── MediaCrawler/           采集子系统（Playwright，5 平台）
├── crawler/                备用简化采集链路（微博/贴吧，输出 JSON）
├── scripts/                数据管线与运维脚本（同步/清洗/事件生成/评测/迁移）
├── deploy/                 公网部署资产（Nginx / systemd / 一键部署脚本）
├── data/                   运行时数据（向量/缓存/演示快照，多数 gitignore）
├── docs/
│   ├── coursework/         《软件工程》9 份正式交付物 + 缺陷台账
│   ├── architecture.md · api.md · database.md · dev-guide.md …   核心参考文档
│   ├── deploy-runbook.md   公网部署操作手册
│   └── archive/            开发过程历史记录（周迭代/爬取交接等，非当前状态）
├── .github/workflows/      GitHub Actions CI（后端/爬虫/前端三任务）
├── check.ps1               一键全量回归（三套测试 + 前端构建）
└── run.bat / dev.bat / stop.bat / demo.bat   本地启停脚本
```

---

## 快速开始（Windows）

```text
1. 双击 setup.bat            # 仅首次：venv + 依赖 + 前端构建
2. 双击 run.bat              # 打开 http://127.0.0.1:9000
```

**演示账号**：管理员 `admin / admin123456`，普通用户 `user / user123456`（也可在登录页注册）。

其他运行方式：

| 脚本 | 用途 |
|------|------|
| `dev.bat` | 开发模式：后端 9000 + Vite 前端 5173（热更新） |
| `demo.bat` | **离线演示**：共享 MySQL 不可用时用本地 SQLite 快照跑全功能（快照先跑 `scripts\make_demo_snapshot.py`） |
| `stop.bat` | 释放 9000 端口 |
| `check.ps1` | 一键全量回归（后端 + 爬虫 + 子仓测试 + 前端构建，约 1 分钟） |

**公网部署**见 [docs/deploy-runbook.md](docs/deploy-runbook.md)（阿里云轻量服务器 + Nginx + systemd）。

---

## 数据采集（可选）

共享库已有 **866 条**真实语料（5 平台：微博 / 贴吧 / 知乎 / 快手 / 小红书）。补采流程：

```text
# 主链路（推荐）：MediaCrawler 写共享库原生表，再映射进 raw_posts
cd MediaCrawler && .venv\Scripts\python.exe main.py --keywords "宿舍 空调" --get_comment yes --fresh yes
cd .. && .venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --limit 0 --refresh
# --limit 0 必须写：默认只同步最新 100 条/平台，超出部分会被静默跳过

# 一键跑通处理管线（同步 → 清洗 → 向量 → 事件生成）
.venv\Scripts\python.exe scripts\run_pipeline.py

# 多机协同采集：从共享队列认领关键词，多台机器互不冲突
.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform ks --from-recommendations --top 20
```

---

## 页面一览（19 个视图）

| 页面 | 路由 | 权限 |
|------|------|------|
| 登录 / 注册 | `/login` | 公开 |
| 首页仪表盘 | `/` | 登录用户 |
| 事件列表 / 详情 | `/events`、`/events/:id` | 公开（游客可看） |
| 舆情助手（对话 Agent） | `/agent-chat` | 登录用户 |
| 舆情工作台 | `/opinion` | 登录用户 |
| 舆情分析 | `/sentiment` | 登录用户 |
| 舆情关注 | `/personal` | 登录用户 |
| 我要投稿 | `/submissions` | 登录用户 |
| 后台概览 | `/admin` | 管理员 |
| 事件审核 | `/admin/events` | 管理员 |
| 数据管理 | `/admin/raw-posts` | 管理员 |
| 智能选题 | `/admin/keywords` | 管理员 |
| 证据采集 | `/admin/evidence` | 管理员 |
| 投稿审核 | `/admin/submissions` | 管理员 |
| 评论管控 | `/admin/comments` | 管理员 |
| 运维中心 | `/admin/ops` | 管理员 |
| 403 无权限 / 404 未找到 | — | — |

---

## 系统架构

```
数据接入层          数据存储层          后端服务层            Agent 核心层           前端展示层
┌──────────┐      ┌──────────┐      ┌──────────────┐     ┌────────────────┐     ┌────────────┐
│MediaCrawler│──→ │ MySQL /  │──→  │ FastAPI      │──→  │ 意图路由/ReAct │──→  │ Vue 3      │
│ 5 平台采集 │     │ SQLite   │      │ REST + JWT   │     │ 聚类/研判/简报 │     │ Element+   │
└──────────┘      └──────────┘      └──────────────┘     └────────────────┘     └────────────┘
                        ↑                                          │
                        └──── 证据核验子系统 · 联网检索 ←───────────┘
```

**数据主链路（闭环）**：爬虫 → `raw_posts` → 清洗 `processed_posts` → Agent 聚类研判
→ `public_events`（草稿）→ 管理员审核发布 → 用户查看/反馈/提问 → 提问日志回流智能选题 → 下一轮采集。

**分层原则**：`routers`（接口）→ `services`（业务编排）→ `public_opinion_core`（纯标准库算法），
依赖单向向下；核心算法层不 import 框架，可独立测试与移植。

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · MySQL（SQLite 兜底）· JWT（PBKDF2 口令哈希） |
| 前端 | Vue 3 · Element Plus · Vue Router · Axios · Vite · GSAP |
| 爬虫 | Python · Playwright（MediaCrawler，5 平台） |
| AI | OpenAI 兼容 LLM（含备胎链）· 智谱 GLM 联网检索 · sentence-transformers 语义嵌入（可选）· 规则引擎兜底 |
| 工程 | Git + GitHub · GitHub Actions CI · Nginx + systemd 部署 |

---

## 测试与质量

- **约 1180 个后端单元/接口测试**，零网络依赖：
  `.venv\Scripts\python.exe -m unittest discover -s backend/tests -t .`
- 爬虫定制层 **181 个 pytest**：`cd MediaCrawler && .venv\Scripts\python.exe -m pytest tests`
- Agent 算法子仓 **305 个测试**（回归镜像）
- **一键全量回归**：`check.ps1`（三套测试 + 前端构建，约 1 分钟全绿）
- **对抗测试战役**：5 个攻击面（越权矩阵 / 输入边界 / 并发竞态 / AI 对抗 / 数据一致性）
  共 30 个用例，主动证伪、发现并修复真实缺陷
- **AI 质量度量**：26 题金标基准（63/63）+ 6 组消融实验（可复现）+ 引用合法率 100%
- **CI**：GitHub Actions，push / PR 自动跑后端 + 爬虫 + 前端三任务
- 全局异常处理（统一 JSON 500 + `system_logs` 落库）、LLM 用量监控、日志轮转

> 舆情 Agent 核心的**唯一源是本仓** `backend/agent/public_opinion_core/`；子仓
> `campus-opinion-agent` 是算法参考 / 回归镜像，改动由 `scripts/sync_opinion_core.py`
> **单向反向移植（主 → 子）**，默认 dry-run，脚本永不写主项目。

---

## 部署

公网部署方案：**阿里云轻量服务器 + Nginx 反代 + systemd 托管**，前端 dist 静态服务、
`/api` 反代本机 uvicorn（仅监听 127.0.0.1）。完整操作手册见
[docs/deploy-runbook.md](docs/deploy-runbook.md)，配置资产在 [`deploy/`](deploy/)。

---

## 文档索引

**课程正式交付物**（[docs/coursework/](docs/coursework/)）：
需求分析 · 系统建模 · 架构设计 · 软件工程化 · 测试与质量保证 · 配置与运维 · 团队报告 ·
演示视频脚本 · 缺陷跟踪台账（9 份）。

**核心参考文档**（docs/）：
[architecture.md](docs/architecture.md) · [api.md](docs/api.md) · [database.md](docs/database.md) ·
[data-sources.md](docs/data-sources.md) · [field-spec.md](docs/field-spec.md) ·
[dev-guide.md](docs/dev-guide.md)（团队开发规范）· [deploy-runbook.md](docs/deploy-runbook.md)

**开发过程历史记录**：见 [docs/archive/](docs/archive/)（周迭代、爬取交接等，**反映历史状态，以当前文档与代码为准**）。

---

## 已知限制（评审须知）

- **帖子"原帖直链"可能无法打开**：小红书等平台的站外直链依赖采集时生成的访问凭证
  （URL 中的 `xsec_token`），会随时间自然过期——平台侧反爬机制，非本系统缺陷。
  界面以"站内搜索"为主入口（不依赖凭证、长期有效），直链为次入口并附失效说明；重新采集后恢复。
- 演示数据为离线快照，首页趋势图等以"最近数据日"为时间锚点，界面有标注。
- 复杂对比类问题走 ReAct 多步推理，耗时约 15 秒~2 分钟，对话页有进度提示。
- 会话记忆存于进程内 + 本地 SQLite，服务重启后多轮上下文清空（重新提问即可）。
- 部署实例默认轻量档（不装 torch）：语义补召回降级为字面搜索，其余 AI 功能全在。
