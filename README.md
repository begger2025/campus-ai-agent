# 校声智枢 · Campus AI Agent

面向校园场景的舆情分析与事务助理平台：从社交平台采集校园公开讨论，经清洗、
语义聚类、LLM 情绪与风险研判生成舆情事件，管理员审核后向全校发布；内置
对话式舆情 Agent，支持多轮追问、多步推理和引用溯源的舆情简报。

## 核心功能

**面向学生/普通用户**
- 事件浏览：已发布舆情事件的列表、详情、代表帖溯源（游客免登录可看）
- 舆情助手（对话 Agent）：热点问答、风险预警、观点分析、简报生成；
  支持多轮追问（"那有什么风险？"自动继承话题）与 ReAct 多步推理
  （"对比食堂和宿舍哪个风险高"会自主调用多个分析工具）
- 舆情工作台/舆情分析：事件筛选研判、帖子浏览、风险分布统计
- 个人事项：本地待办管理 + 与自己相关的中高风险舆情提示与影响评估
- 事件反馈：一键提交纠错/补充，进入管理员处理队列

**面向管理员**
- 后台概览：数据量、事件状态分布、待办事项一屏总览
- 事件审核：通过/驳回/归档 + 审核意见，全程留痕（审核历史时间线）
- 数据管理：原始帖子多维筛选与详情查看
- 运维中心：用户反馈处理、采集任务记录、系统日志、用户管理、操作审计

**AI 层亮点（答辩重点）**
- LLM 优先 + 规则兜底的双通道架构：断网/无 API Key 时全功能降级可用
- 语义事件聚类（bge-small-zh 嵌入），配套 66 条人工标注黄金集与
  纯度/成对 F1 评测框架，消融实验量化每个模块贡献
- 引用溯源简报：LLM 论断句末强制标注 `[来源:pN]`，确定性校验抓幻觉引用，
  Critic 二次审校对照数据核查
- 提示注入防御、LLM 用量监控、磁盘缓存与重试

## 快速开始（Windows）

```text
1. 双击 setup.bat            # 仅首次：venv + 依赖 + 前端构建
2. 双击 run.bat              # 打开 http://127.0.0.1:9000
```

**演示账号**：管理员 `admin / admin123456`，普通用户 `user / user123456`
（也可在登录页注册新账号）。

其他运行方式：

| 脚本 | 用途 |
|------|------|
| `dev.bat` | 开发模式：后端 9000 + Vite 前端 5173 |
| `demo.bat` | **离线演示**：共享 MySQL 不可用时用本地 SQLite 快照跑全功能（快照先跑 `scripts\make_demo_snapshot.py` 生成） |
| `stop.bat` | 释放 9000 端口 |

采集真实数据（可选，共享库已有 182 条历史数据）：

```text
# 主链路（推荐）：MediaCrawler 直接写共享库原生表，再映射进 raw_posts
cd MediaCrawler && .venv\Scripts\python.exe main.py        # 按 config/base_config.py 的关键词采集
cd .. && .venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs
# 首次或新平台建议先加 --dry-run 验证字段映射，再正式入库

# 备用链路（微博/贴吧简化爬虫，输出 JSON）
save_weibo_login.bat / save_tieba_login.bat   # 保存登录态，仅首次
crawl.bat                                     # 采集 → data/samples/（不足时默认不补 demo 假数据）
import_latest.bat                             # 导入 raw_posts（按 external_id 去重）
```

## 页面一览（14 个视图）

| 页面 | 路由 | 权限 |
|------|------|------|
| 登录/注册 | `/login` | 公开 |
| 首页仪表盘 | `/` | 公开（游客可看） |
| 事件列表 / 详情 | `/events`、`/events/:id` | 公开（游客可看） |
| 舆情助手（对话 Agent） | `/agent-chat` | 登录用户 |
| 舆情工作台 | `/opinion` | 登录用户 |
| 舆情分析 | `/sentiment` | 登录用户 |
| 个人事项 | `/personal` | 登录用户 |
| 后台概览 / 事件审核 / 数据管理 / 运维中心 | `/admin`、`/admin/events`、`/admin/raw-posts`、`/admin/ops` | 管理员 |
| 403 / 404 | — | — |

## 系统架构

```
数据接入层         数据存储层         后端服务层            Agent 层             前端展示层
┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌────────────────┐     ┌────────────┐
│MediaCrawler│──→│ MySQL /  │──→ │ FastAPI      │──→ │ 意图路由/ReAct │──→ │ Vue 3      │
│ 小红书等   │    │ SQLite   │     │ REST + JWT   │     │ 聚类/情绪/简报 │     │ Element+   │
└──────────┘     └──────────┘     └──────────────┘     └────────────────┘     └────────────┘
```

数据主链路：爬虫 → `raw_posts` → 清洗 `processed_posts` → Agent 分析
→ `public_events`（草稿）→ 管理员审核发布 → 用户查看/反馈 → 审计日志。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy · MySQL（SQLite 兜底）· JWT（PBKDF2 口令哈希） |
| 前端 | Vue 3 · Element Plus · Vue Router · Axios · Vite · GSAP |
| 爬虫 | Python · Playwright（MediaCrawler） |
| AI | OpenAI 兼容 LLM API · sentence-transformers 语义嵌入（可选）· 规则引擎兜底 |

## 测试与质量

- 后端 54 个单元/接口测试，零网络依赖：
  `.venv\Scripts\python.exe -m unittest discover -s backend/tests -t .`
- 全局异常处理（统一 JSON 500 + `system_logs` 落库，后台可视）、
  Python 日志（`data/logs/app.log` 轮转）
- 舆情 Agent 核心的**唯一源是本仓** `backend/agent/public_opinion_core/`；
  子项目 `campus-opinion-agent` 是算法参考 / 回归测试镜像，改动由
  `scripts/sync_opinion_core.py` **单向反向移植（主项目 -> 子项目）**，
  默认 dry-run，且脚本永不写入主项目

## 文档索引

- 产品化历程：`docs/week7-p0-auth-hardening.md`（真实登录与安全整改）、
  `docs/week7-p1-admin-pages-and-user-loop.md`（管理后台与用户体系，含
  8 步验收清单）、`docs/week7-p2-engineering-quality.md`（工程质量与演示降级）
- Agent 集成：`docs/week6-public-opinion-agent-integration.md`、
  `docs/week6-public-opinion-agent-chat.md`
- 基础设计：`docs/architecture.md` · `docs/api.md` · `docs/database.md` ·
  `docs/data-sources.md` · `docs/field-spec.md`
- 爬虫：`docs/crawl-handoff.md` · `docs/crawl-issues.md`

## 已知限制（评审须知）

- **帖子"原帖直链"可能无法打开**：小红书等平台的站外直链依赖采集时生成的
  访问凭证（URL 中的 `xsec_token`），会随时间自然过期——这是平台侧反爬机制，
  非本系统缺陷。界面以"站内搜索"为主入口（不依赖凭证、长期有效），直链为
  次入口并附失效说明；重新采集后直链恢复。
- 演示数据为离线快照，首页趋势图等以"最近数据日"为时间锚点，界面有标注。
- 复杂对比类问题走 ReAct 多步推理，耗时约 1~2 分钟，对话页有进度提示。
- 会话记忆存于进程内存，服务重启后多轮上下文清空（重新提问即可）。
