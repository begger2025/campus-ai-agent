# 后端工作包2验收记录：确定数据库表结构

检查时间：2026-06-05

## 1. 本次补齐内容

本次补齐的是“主项目代码与共享 MySQL 表结构不一致”的部分。共享数据库本身已经存在工作包2要求的大部分表和字段，主要缺口在主项目代码侧：

- 补齐 `backend/models.py` 中公共舆情业务表 ORM：
  - `raw_posts`
  - `processed_posts`
  - `public_events`
  - `event_post_links`
  - `user_tasks`
  - `user_schedules`
- 补齐 `backend/admin_models.py` 中后台管理与审计表 ORM：
  - `users`
  - `crawl_tasks`
  - `agent_run_logs`
  - `event_review_logs`
  - `admin_operation_logs`
  - `system_logs`
  - `user_feedback`
  - `system_configs`
- 更新 `backend/schemas.py`，让 `/api/posts` 的返回模型能覆盖 `raw_posts` 的新增字段。
- 更新 `backend/routers/api.py`，让 `/api/events` 支持通过 `event_post_links` 返回事件关联帖子。
- 更新 `scripts/sql/wp1_create_tables_mysql.sql`，作为空数据库初始化时的完整 MySQL 建表脚本。
- 更新 `docs/database.md` 和 `docs/api.md`，使文档从第一周 SQLite/简化表结构调整为第二周共享 MySQL/完整业务表结构。
- 新增 `scripts/check_wp2.py` 和 `check_wp2.bat`，用于一键验收工作包2。

## 2. 共享数据库实际状态

共享数据库连接目标为：

- 数据库类型：MySQL
- 数据库名：`campus_ai_agent`
- 当前表数量：37

本次验收确认以下工作包2要求的表已经存在：

- `raw_posts`
- `processed_posts`
- `public_events`
- `event_post_links`
- `users`
- `crawl_tasks`
- `agent_run_logs`
- `event_review_logs`
- `admin_operation_logs`
- `system_logs`
- `user_feedback`

同时确认可选表 `system_configs` 已存在。

本次验收确认以下第二周不应提前建设的表未出现：

- `personal_advices`
- `roles`
- `permissions`
- `notifications`
- `user_login_logs`

## 3. 关键约束验收结果

验收脚本已确认：

- `raw_posts` 存在唯一约束：`UNIQUE(platform, external_id)`
- `public_events` 存在唯一约束：`UNIQUE(event_key)`
- `event_post_links` 存在指向事件、处理后帖子、原始帖子的外键
- MediaCrawler 样例表已存在：
  - `xhs_note`
  - `xhs_note_comment`
  - `weibo_note`
  - `weibo_note_comment`
  - `tieba_note`

## 4. 当前数据量

核心业务表当前仍为空，说明表结构已经具备，但公共舆情 agent 的归一化、分析、事件生成流程还没有正式写入业务表：

- `raw_posts`: 0
- `processed_posts`: 0
- `public_events`: 0
- `event_post_links`: 0
- `users`: 0
- `crawl_tasks`: 0
- `agent_run_logs`: 0
- `event_review_logs`: 0
- `admin_operation_logs`: 0
- `system_logs`: 0
- `user_feedback`: 0

这不代表工作包2失败。工作包2的目标是确定并补齐数据库表结构；数据写入属于后续爬虫同步、agent 清洗分析、后台管理接口等工作包。

## 5. 验收命令

在主项目根目录运行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\check_wp2.bat
```

或者直接运行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\check_wp2.py
```

验收通过标志：

```text
WP2 schema checks PASSED.
```

## 6. 结论

后端工作包2的数据库表结构要求目前已经补齐到主项目代码、SQL 脚本、接口模型和验收脚本中。当前剩余工作不是表结构本身，而是后续流程：

- 将 MediaCrawler 原生表中的数据同步/归一化到 `raw_posts`
- 由公共舆情 agent 生成 `processed_posts`
- 聚合生成 `public_events`
- 写入 `event_post_links`
- 后台管理端继续补全用户、审核、日志、反馈相关接口
