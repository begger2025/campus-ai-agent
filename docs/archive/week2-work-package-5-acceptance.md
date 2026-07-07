# Week2 后端工作包 5 验收记录：公共舆情 Agent 分析结果入库与事件审核接口

生成时间：2026-06-06

## 1. 工作包目标

本工作包完成主项目后端与 `campus-opinion-agent` 公共舆情 Agent 的接入，打通以下链路：

```text
processed_posts
-> PublicOpinionAgentService
-> public_events + event_post_links
-> agent_run_logs
-> 管理员审核
-> 普通用户只查看 published 事件
```

## 2. 实现结果

已完成内容：

- 已将 Agent 子工程纯业务核心包迁移到主项目：`backend/agent/public_opinion_core`。
- 已新增主项目适配层：`backend/services/public_opinion_adapter.py`。
- 已新增 Agent 分析入口：`POST /api/agent/public/analyze`。
- 已新增管理员事件审核接口：
  - `GET /api/admin/events`
  - `GET /api/admin/events/{event_id}`
  - `PATCH /api/admin/events/{event_id}/status`
- 已收紧普通用户事件接口：
  - `GET /api/events` 只返回 `published`
  - `GET /api/events/{event_id}` 只允许访问 `published`
- 已新增验收脚本：`scripts/check_wp5.py`。

本次没有新增 `public_analysis_runs` 表。原因是主项目已有 `agent_run_logs`，且 Agent 子工程指导文档也提供了 `build_agent_run_log_payload()`，因此复用 `agent_run_logs` 记录公共舆情 Agent 运行情况，避免分析日志分裂成两套表。

## 3. 修改文件

新增：

- `backend/agent/__init__.py`
- `backend/agent/public_opinion_core/*.py`
- `backend/services/__init__.py`
- `backend/services/public_opinion_adapter.py`
- `backend/routers/agent_public.py`
- `backend/routers/admin_events.py`
- `scripts/check_wp5.py`
- `docs/week2-work-package-5-acceptance.md`

修改：

- `backend/main.py`
- `backend/routers/api.py`

## 4. 接口说明

### 4.1 触发公共舆情 Agent 分析

```http
POST /api/agent/public/analyze
```

请求示例：

```json
{
  "keyword": "",
  "limit": 50,
  "platforms": [],
  "persist": true,
  "created_by": "admin"
}
```

结果：

- 从 `processed_posts` 读取数据。
- 调用 `PublicOpinionAgentService`。
- 生成 `draft` 状态的事件 payload。
- 写入 `public_events`。
- 写入 `event_post_links`。
- 写入 `agent_run_logs`。

### 4.2 普通用户事件接口

```http
GET /api/events
GET /api/events/{event_id}
```

规则：

- 只返回 `status = published` 的事件。
- `draft`、`rejected`、`archived` 对普通用户不可见。

### 4.3 管理员审核接口

```http
GET   /api/admin/events?status=all
GET   /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
```

支持状态：

```text
draft
published
rejected
archived
```

管理员修改事件状态时，会写入 `event_review_logs`。

## 5. 验收命令与结果

### 5.1 WP5 验收

执行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\check_wp5.py --limit 50
```

关键结果：

```text
[OK] portable Agent core importable
[OK] using shared MySQL
[OK] WP5 routes registered
[OK] processed_posts row count >= 1 (100)
[OK] Agent preview generated 4 events
[OK] new Agent event payloads default to draft
[OK] Agent persisted 4 events
[OK] public_events available (4)
[OK] event_post_links available (11)
[OK] agent_run_logs recorded this analysis run
[OK] admin status patch published event 1
[OK] event_review_logs recorded the status change
[OK] public events list only returns published events
[OK] public event detail returns published event with representative_posts
[OK] admin events list can see reviewed events

WP5 public opinion Agent checks PASSED.
```

### 5.2 WP4 回归验收

执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py --min-raw 1 --min-processed 1 --min-notes 1
```

关键结果：

```text
[OK] Using shared MySQL
[OK] MediaCrawler and main project tables present
[INFO] raw_posts: 100 rows
[INFO] processed_posts: 100 rows
[OK] processed_posts can be loaded as OpinionNote

WP4 data pipeline checks PASSED.
```

## 6. 共享数据库验收后状态

```text
public_events: 4
draft_events: 3
published_events: 1
event_post_links: 11
public_opinion_agent_logs: 1
event_review_logs: 1
```

说明：

- `scripts/check_wp5.py` 已将一个 `draft` 事件通过管理员审核接口改为 `published`。
- 因此普通用户接口当前至少能查到 1 个已发布事件。
- 其余 3 个事件仍为 `draft`，用于后续后台审核页面继续验收。

## 7. 验收结论

工作包 5 的最小闭环已经完成：

```text
真实 processed_posts 数据
-> 后端接口触发公共舆情 Agent
-> public_events draft 入库
-> event_post_links 关联代表帖
-> agent_run_logs 记录运行
-> 管理员把 draft 改为 published
-> 普通用户接口只能看到 published
```

后续可继续完善：

- 接入真实管理员登录身份，替代请求体里的 `created_by`、`reviewed_by`。
- 在后台管理前端增加事件审核页面。
- 增加更细的筛选条件，例如风险等级、平台、关键词、时间范围。
- 后续如引入大模型摘要，可在当前 `PublicOpinionAgentService` 之后增加增强层，不需要改变本次入库闭环。
