# Week2 后端工作包 5：公共舆情 Agent 状态与对接指南

> **用途：** 给后端负责人完成“公共舆情 Agent 分析结果入库与事件审核接口”使用。  
> **审查时间：** 2026-06-05  
> **审查范围：**
>
> - `D:\桌面文件\软件工程大作业\week2 后端工作包 5：公共舆情 Agent 分析结果入库与事件审核接口.md`
> - `D:\桌面文件\软件工程大作业\campus-opinion-agent`
> - `D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`

---

## 1. 总结结论

### 1.1 Agent 子项目当前状态

`campus-opinion-agent` 已经完成到 **Task 5：迁移和改造分析规则**。

当前已经具备：

```text
processed_posts rows/dicts
-> processed_posts_to_notes
-> list[OpinionNote]
-> score_notes
-> analyze_notes_sentiment_and_risk
-> cluster_notes
-> list[OpinionEvent]
```

也就是说，Agent 本体已经能离线完成：

- 输入适配：`processed_posts` dict 转 `OpinionNote`
- 热度评分
- 情绪判断
- 风险判断
- 事件聚类
- 规则版摘要和处置建议

当前尚未完成：

- `PublicOpinionAgentService.analyze_from_rows(...)`
- `OpinionEvent -> public_events` payload builder
- `OpinionEvent.representative_notes -> event_post_links` payload builder
- `AnalyzeResult -> agent_run_logs` payload builder
- 主项目数据库写入
- 主项目 `POST /api/agent/public/analyze`
- 主项目管理员审核接口

### 1.2 主项目当前状态

主项目 `campus-ai-agent_v3\campus-ai-agent-main` 已经具备部分工作包 5 的基础：

- `processed_posts` ORM 已有。
- `public_events` ORM 已有。
- `event_post_links` ORM 已有。
- `agent_run_logs` ORM 已有。
- `event_review_logs` ORM 已有。
- `agent/opinion_input.py` 已经能从 `processed_posts` 读取并转换成一个主项目自定义的 `OpinionNote`。

但主项目还没有完成工作包 5：

- 没有 `POST /api/agent/public/analyze`。
- 没有 `GET /api/events/{event_id}`。
- 没有 `GET /api/admin/events`。
- 没有 `GET /api/admin/events/{event_id}`。
- 没有 `PATCH /api/admin/events/{event_id}/status`。
- 现有 `GET /api/events` 如果不传 `status`，会返回全部状态，不符合“普通用户默认只能看 published”。
- 还没有把 `campus-opinion-agent` 的 `public_opinion_core` 迁入主项目。
- 还没有把 Agent 结果写入 `public_events` 和 `event_post_links`。

### 1.3 后端负责人最短完成路径

不要重写 Agent 规则。建议按下面路径做：

```text
1. 把 campus-opinion-agent/backend/app/public_opinion_core 复制到主项目
2. 在主项目写 public_opinion_adapter/service
3. 从 processed_posts 查询并转成 public_opinion_core 的 OpinionNote
4. 调用 score_notes + analyze_notes_sentiment_and_risk + cluster_notes
5. 把 OpinionEvent 写入 public_events(status=draft)
6. 把 representative_notes 写入 event_post_links
7. 写 agent_run_logs
8. 补 POST /api/agent/public/analyze
9. 补普通用户事件详情接口
10. 补管理员事件列表、详情、状态审核接口
```

---

## 2. 工作包 5 要求提取

工作包 5 的核心数据流是：

```text
processed_posts
-> 转换为 OpinionNote
-> 公共舆情 Agent 分析
-> OpinionEvent
-> public_events + event_post_links
-> 管理员审核
-> 普通用户查看 published 事件
```

后端需要新增三个核心能力：

```text
load_opinion_notes_from_db()
run_public_opinion_analysis()
save_opinion_events()
```

接口要求：

```text
POST  /api/agent/public/analyze
GET   /api/events
GET   /api/events/{event_id}
GET   /api/admin/events
GET   /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
```

状态要求：

```text
draft       Agent 生成，等待管理员审核
published   管理员发布，普通用户可见
rejected    管理员驳回，普通用户不可见
archived    归档，普通用户默认不可见
```

---

## 3. Agent 子项目详细状态

### 3.1 可迁移核心目录

当前可迁移目录：

```text
D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\app\public_opinion_core
```

文件：

```text
adapter.py
clustering.py
normalizer.py
schemas.py
scoring.py
sentiment_risk.py
__init__.py
```

建议复制到主项目：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\backend\agent\public_opinion_core
```

复制后相对导入仍可用，因为这些文件内部主要使用：

```python
from .schemas import ...
from .normalizer import ...
```

### 3.2 当前核心数据结构

文件：

```text
campus-opinion-agent\backend\app\public_opinion_core\schemas.py
```

#### `OpinionNote`

当前字段：

```text
note_id
title
content
processed_post_id
raw_post_id
platform
author_name
publish_time
publish_date
url
raw_url
source_keyword
keywords
tags
like_count
collect_count
comment_count
share_count
heat_score
sentiment
sentiment_score
risk_level
risk_score
risk_reasons
concerns
extra
```

后端入库时一定要保留：

- `processed_post_id`：写入 `event_post_links.processed_post_id`
- `raw_post_id`：写入 `event_post_links.raw_post_id`
- `heat_score`：代表帖子排序使用
- `risk_reasons/concerns`：写入事件风险依据

#### `OpinionEvent`

当前字段：

```text
event_key
title
summary
category
risk_level
sentiment
heat_score
source_count
risk_score
first_seen_at
last_seen_at
source_keywords
top_tags
concerns
risk_reasons
representative_notes
agent_summary
extra
```

这些字段足够映射到 `public_events` 和 `event_post_links`。

### 3.3 当前可直接调用的函数

从 `processed_posts` dict 转成 Agent 输入：

```python
from app.public_opinion_core.adapter import processed_posts_to_notes

warnings: list[str] = []
notes = processed_posts_to_notes(rows, warnings=warnings)
```

规则分析链路：

```python
from app.public_opinion_core.scoring import score_notes
from app.public_opinion_core.sentiment_risk import analyze_notes_sentiment_and_risk
from app.public_opinion_core.clustering import cluster_notes

notes = score_notes(notes)
notes = analyze_notes_sentiment_and_risk(notes)
events = cluster_notes(notes)
```

迁移到主项目后，导入路径建议改为：

```python
from backend.agent.public_opinion_core.adapter import processed_posts_to_notes
from backend.agent.public_opinion_core.scoring import score_notes
from backend.agent.public_opinion_core.sentiment_risk import analyze_notes_sentiment_and_risk
from backend.agent.public_opinion_core.clustering import cluster_notes
```

### 3.4 Agent 子项目已验证结果

在 `campus-opinion-agent\backend` 下运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m unittest tests.test_public_opinion_core_schemas tests.test_processed_posts_fixture tests.test_public_opinion_core_adapter tests.test_public_opinion_core_analysis
```

审查时结果：

```text
Ran 22 tests in 0.019s
OK
```

离线 smoke test 结果：

```text
events 4
campus_safety 8 high 1024.5 校园安全与防诈骗提醒
canteen_life 7 medium 634.5 食堂排队与价格反馈
course_schedule 8 medium 511.0 课程安排与教务反馈
dorm_life 7 medium 474.5 宿舍热水与后勤维修反馈
```

### 3.5 Agent 子项目还缺什么

工作包 5 不能直接等 Agent 子项目继续做完全部 Task。后端负责人可以自己在主项目补集成层。

缺口：

```text
service.py          未完成
payload_builder.py  未完成
cli.py              未完成
```

这意味着后端负责人需要在主项目实现：

- `run_public_opinion_analysis(...)`
- `save_opinion_events(...)`
- `build_public_event_payload(...)`
- `build_event_post_links(...)`
- `write_agent_run_log(...)`

---

## 4. 主项目详细状态

主项目路径：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
```

### 4.1 后端入口

文件：

```text
backend\main.py
```

当前只 include 一个 router：

```python
app.include_router(api_router, prefix="/api")
```

后端负责人可以继续在 `backend\routers\api.py` 加接口，也可以新建：

```text
backend\routers\public_agent.py
backend\routers\events_admin.py
```

如果新建 router，需要在 `main.py` include。

### 4.2 当前 API 路由

文件：

```text
backend\routers\api.py
```

当前实际路由只有：

```text
GET /api/ping
GET /api/posts
GET /api/events
GET /api/admin/overview
```

缺少工作包 5 要求的：

```text
POST  /api/agent/public/analyze
GET   /api/events/{event_id}
GET   /api/admin/events
GET   /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
```

### 4.3 `GET /api/events` 当前问题

当前代码逻辑：

```python
query = db.query(PublicEvent)
if status:
    query = query.filter(PublicEvent.status == status)
```

问题：

- 如果普通用户不传 `status`，会返回所有事件，包括 `draft/rejected/archived`。
- 工作包 5 要求普通用户默认只能看到 `published`。

建议修改为：

```python
@router.get("/events")
def list_events(...):
    query = db.query(PublicEvent).filter(PublicEvent.status == "published")
```

管理员查看全部状态应走：

```text
GET /api/admin/events
```

不要让普通用户接口兼顾管理员能力。

### 4.4 主项目 ORM 表状态

文件：

```text
backend\models.py
backend\admin_models.py
```

#### `ProcessedPost`

已具备工作包 5 所需主要字段：

```text
id
raw_post_id
platform
note_id
title
content
source_keyword
publish_date
publish_time_raw
author_name
tags_json
note_url
raw_note_url
images_json
like_count
collect_count
comment_count
share_count
heat_score
sentiment
sentiment_score
risk_level
risk_score
risk_reasons_json
concerns_json
created_at
updated_at
```

#### `PublicEvent`

已具备工作包 5 的主要字段：

```text
id
event_key
title
summary
topic
event_type
sentiment
risk_level
risk_score
heat_score
confidence
source_count
date_range_json
source_keywords_json
top_tags_json
concerns_json
risk_reasons_json
status
reviewed_by
reviewed_at
review_comment
created_at
updated_at
source_post_id
```

注意：

- `source_post_id` 是兼容第一周的单来源字段。
- 工作包 5 新代码应优先使用 `event_post_links`。

#### `EventPostLink`

已具备：

```text
id
event_id
processed_post_id
raw_post_id
rank
role
created_at
```

这能保存每个事件的代表性帖子。

#### `AgentRunLog`

当前表名是：

```text
agent_run_logs
```

工作包 5 文档中建议新增的是：

```text
public_analysis_runs
```

当前主项目没有 `public_analysis_runs`。建议先使用已有 `agent_run_logs` 完成工作包 5，因为它已经覆盖：

```text
agent_type
keyword
input_count
output_count
input_summary
output_summary
status
error_message
duration_ms
created_by
created_at
started_at
finished_at
```

如果老师或后续验收严格要求 `public_analysis_runs` 这个表名，再另建表；否则不要重复建两个运行日志表。

#### `EventReviewLog`

已具备：

```text
event_id
reviewer_id
old_status
new_status
review_comment
created_at
```

管理员修改事件状态时应写入该表。

### 4.5 主项目已有 `agent/opinion_input.py`

文件：

```text
agent\opinion_input.py
```

它已经能从 `processed_posts` 读数据：

```python
load_opinion_notes_from_db(...)
processed_post_to_opinion_note(row)
```

但要注意：

1. 它定义的是主项目自己的 `OpinionNote`，不是 `campus-opinion-agent` 当前 `public_opinion_core.schemas.OpinionNote`。
2. 它缺少 `processed_post_id` 字段，而工作包 5 写 `event_post_links` 时需要这个字段。
3. 它目前只是输入读取器，不包含情绪风险、聚类、入库。

建议：

- 不要继续扩展这个旧 `OpinionNote`。
- 保留它作为工作包 4 验收脚本兼容。
- 工作包 5 新代码使用 `backend.agent.public_opinion_core.schemas.OpinionNote`。

---

## 5. 字段映射建议

### 5.1 `ProcessedPost -> OpinionNote`

后端负责人可以不直接用 Agent 子项目的 `adapter.py`，也可以先从 ORM row 手工构造 dict 再调用 `processed_posts_to_notes`。

推荐构造 dict：

```python
row_dict = {
    "id": row.id,
    "raw_post_id": row.raw_post_id,
    "platform": row.platform,
    "note_id": row.note_id,
    "title": row.title,
    "content": row.content,
    "source_keyword": row.source_keyword,
    "publish_date": row.publish_date,
    "publish_time": row.publish_time_raw or "",
    "author_name": row.author_name,
    "keywords": tags,
    "url": row.note_url,
    "raw_url": row.raw_note_url,
    "like_count": row.like_count,
    "collect_count": row.collect_count,
    "comment_count": row.comment_count,
    "share_count": row.share_count,
    "sentiment": row.sentiment,
    "risk_level": row.risk_level,
}
```

注意：

- Agent 子项目的 adapter 当前读取 `publish_time`，没有直接读取 `publish_time_raw`。
- 所以后端适配层要把 `row.publish_time_raw` 映射成 dict 的 `publish_time`。
- 主项目 `tags_json` 要解析成 list，再传给 `keywords`。

### 5.2 `OpinionEvent -> PublicEvent`

推荐映射：

| `OpinionEvent` | `PublicEvent` | 说明 |
|---|---|---|
| `event_key` | `event_key` | 入库前必须加工成唯一 key |
| `title` | `title` | 事件标题 |
| `summary` | `summary` | 事件摘要 |
| `category` | `topic` | 主题分类 |
| `category` | `event_type` | 类型，先可同 topic |
| `sentiment` | `sentiment` | `positive/neutral/negative/controversial` |
| `risk_level` | `risk_level` | `low/medium/high` |
| `risk_score` | `risk_score` | 风险分 |
| `heat_score` | `heat_score` | 热度分 |
| 固定值 | `confidence` | 可先用 `0.75` |
| `source_count` | `source_count` | 来源数量 |
| `first_seen_at/last_seen_at` | `date_range_json` | JSON 字符串 |
| `source_keywords` | `source_keywords_json` | JSON 字符串 |
| `top_tags` | `top_tags_json` | JSON 字符串 |
| `concerns` | `concerns_json` | JSON 字符串 |
| `risk_reasons` | `risk_reasons_json` | JSON 字符串 |
| 固定值 | `status` | 新生成必须是 `draft` |

### 5.3 关键风险：`event_key` 不能直接用 Agent 的分类名

当前 Agent 生成的 `OpinionEvent.event_key` 是：

```text
campus_safety
canteen_life
course_schedule
dorm_life
```

而主项目 `public_events` 有：

```text
UNIQUE(event_key)
```

如果直接入库，第二次分析同类事件会唯一键冲突。

后端必须生成更细的持久化 key，例如：

```python
stable_key = f"{event.category}:{first_date}:{last_date}:{keyword_hash}:{source_hash}"
```

建议最小实现：

```python
event_key = f"{event.category}:{event.first_seen_at[:10]}:{event.last_seen_at[:10]}:{hash_source_keywords}"
```

其中 `hash_source_keywords` 可对 `event.source_keywords` 排序后做 md5 前 8 位。

### 5.4 `representative_notes -> EventPostLink`

推荐映射：

| `OpinionNote` | `EventPostLink` |
|---|---|
| `processed_post_id` | `processed_post_id` |
| `raw_post_id` | `raw_post_id` |
| list 下标 | `rank` |
| 固定值 `representative` | `role` |

注意：

- 只保存前 5 条代表内容。
- `representative_notes` 已经按 `heat_score` 降序排序。

### 5.5 `AnalyzeResult/运行摘要 -> AgentRunLog`

主项目没有 `public_analysis_runs`，建议先写 `agent_run_logs`。

推荐映射：

| 来源 | `AgentRunLog` |
|---|---|
| 固定值 `public_opinion` | `agent_type` |
| 请求 keyword | `keyword` |
| 查询到的 processed_posts 数 | `input_count` |
| 生成事件数 | `output_count` |
| 输入摘要 | `input_summary` |
| 输出摘要 | `output_summary` |
| `success/failed` | `status` |
| 异常信息 | `error_message` |
| 运行耗时 | `duration_ms` |
| 操作人 | `created_by` |
| 开始时间 | `started_at` |
| 结束时间 | `finished_at` |

---

## 6. 建议后端实现文件

### 6.1 复制 Agent 核心包

源目录：

```text
D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\app\public_opinion_core
```

目标目录：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\backend\agent\public_opinion_core
```

需要复制：

```text
adapter.py
clustering.py
normalizer.py
schemas.py
scoring.py
sentiment_risk.py
__init__.py
```

### 6.2 新增服务层

建议新建：

```text
backend\services\public_opinion_adapter.py
```

职责：

```text
load_opinion_rows_from_db
run_public_opinion_analysis
save_opinion_events
write_agent_run_log
update_event_status
```

如果当前没有 `backend\services` 目录，先新建：

```text
backend\services\__init__.py
```

### 6.3 新增请求响应 schema

建议修改：

```text
backend\schemas.py
```

新增：

```python
class PublicAnalyzeRequest(BaseModel):
    keyword: str = ""
    limit: int = 200
    persist: bool = True
    platforms: list[str] = []


class EventStatusUpdateRequest(BaseModel):
    status: str
    review_comment: str = ""
    reviewer_id: str = "admin"
```

### 6.4 修改 API 路由

建议修改或拆分：

```text
backend\routers\api.py
```

至少新增：

```text
POST  /agent/public/analyze
GET   /events/{event_id}
GET   /admin/events
GET   /admin/events/{event_id}
PATCH /admin/events/{event_id}/status
```

因为 `main.py` 已经挂载了：

```python
app.include_router(api_router, prefix="/api")
```

所以在 `api.py` 里写：

```python
@router.post("/agent/public/analyze")
```

实际访问路径就是：

```text
POST /api/agent/public/analyze
```

---

## 7. 后端实现任务拆分

### Task A：迁移 Agent 核心包

- [ ] 复制 `public_opinion_core` 到主项目 `backend\agent\public_opinion_core`。
- [ ] 确认能导入：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe -c "from backend.agent.public_opinion_core.clustering import cluster_notes; print(cluster_notes)"
```

预期：

```text
<function cluster_notes ...>
```

### Task B：实现 `ProcessedPost -> OpinionNote`

- [ ] 新建 `backend\services\public_opinion_adapter.py`。
- [ ] 写函数 `load_opinion_note_rows(db, keyword, limit, platforms)`。
- [ ] 从 `ProcessedPost` 查询数据。
- [ ] 解析 `tags_json/risk_reasons_json/concerns_json`。
- [ ] 构造 dict 后调用 `processed_posts_to_notes(...)`。

最低验收：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe -c "from backend.database import SessionLocal; from backend.services.public_opinion_adapter import load_opinion_notes_from_db; db=SessionLocal(); notes=load_opinion_notes_from_db(db, limit=5); print(len(notes)); print(notes[0] if notes else 'no data'); db.close()"
```

### Task C：实现分析函数

建议函数：

```python
def run_public_opinion_analysis(notes: list[OpinionNote]) -> list[OpinionEvent]:
    notes = score_notes(notes)
    notes = analyze_notes_sentiment_and_risk(notes)
    return cluster_notes(notes)
```

最低验收：

```powershell
.\.venv\Scripts\python.exe -c "from backend.database import SessionLocal; from backend.services.public_opinion_adapter import load_opinion_notes_from_db, run_public_opinion_analysis; db=SessionLocal(); notes=load_opinion_notes_from_db(db, limit=50); events=run_public_opinion_analysis(notes); print(len(events)); [print(e.category, e.source_count, e.risk_level) for e in events]; db.close()"
```

### Task D：实现 `OpinionEvent -> public_events/event_post_links`

保存事件时：

- `status` 必须默认 `draft`。
- 先写 `public_events`。
- flush 得到 `event.id`。
- 再写 `event_post_links`。
- 最多写 5 条代表帖子。
- 对重复事件执行 upsert 或跳过。

最低验收：

```powershell
.\.venv\Scripts\python.exe -c "from backend.database import SessionLocal; from backend.services.public_opinion_adapter import analyze_and_persist; db=SessionLocal(); result=analyze_and_persist(db, keyword='', limit=50, created_by='admin'); print(result); db.close()"
```

之后用 SQLTools 检查：

```sql
SELECT id, event_key, title, status, source_count, heat_score
FROM public_events
ORDER BY id DESC
LIMIT 10;

SELECT id, event_id, processed_post_id, raw_post_id, `rank`, `role`
FROM event_post_links
ORDER BY id DESC
LIMIT 20;
```

### Task E：实现 `POST /api/agent/public/analyze`

请求：

```json
{
  "keyword": "中山大学",
  "limit": 200,
  "persist": true
}
```

响应建议：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "input_count": 200,
    "event_count": 4,
    "persisted_count": 4,
    "run_log_id": 12,
    "events": [
      {
        "id": 1,
        "event_key": "...",
        "title": "...",
        "status": "draft",
        "risk_level": "medium",
        "source_count": 7
      }
    ],
    "warnings": []
  }
}
```

验收：

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:9000/api/agent/public/analyze" -ContentType "application/json" -Body '{"keyword":"","limit":50,"persist":true}'
```

### Task F：修正普通用户事件接口

修改：

```text
GET /api/events
```

要求：

- 默认只返回 `published`。
- 普通用户不能通过 `status=draft` 看到草稿。

建议：

```python
query = db.query(PublicEvent).filter(PublicEvent.status == "published")
```

验收：

```sql
SELECT status, COUNT(*)
FROM public_events
GROUP BY status;
```

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/events"
```

返回中不能出现：

```text
draft
rejected
archived
```

### Task G：实现普通用户事件详情接口

新增：

```text
GET /api/events/{event_id}
```

要求：

- 只能访问 `published`。
- 返回事件详情和代表性帖子。

返回内容至少包含：

```text
事件摘要
热度
风险等级
风险依据
关注点
代表性帖子
来源关键词
时间范围
```

### Task H：实现管理员事件审核接口

新增：

```text
GET   /api/admin/events?status=draft
GET   /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
```

PATCH 请求：

```json
{
  "status": "published",
  "review_comment": "确认发布",
  "reviewer_id": "admin"
}
```

状态只允许：

```text
draft
published
rejected
archived
```

PATCH 时必须：

- 更新 `public_events.status`
- 更新 `public_events.reviewed_by`
- 更新 `public_events.reviewed_at`
- 更新 `public_events.review_comment`
- 写入 `event_review_logs`
- 建议同时写入 `admin_operation_logs`

### Task I：写运行日志

每次调用 `POST /api/agent/public/analyze` 都写 `agent_run_logs`：

- 成功：`status=success`
- 无数据：`status=failed`，`error_message=processed_posts 数据不足`
- 异常：`status=failed`，记录异常信息

SQLTools 检查：

```sql
SELECT id, agent_type, keyword, input_count, output_count, status, error_message, duration_ms, created_at
FROM agent_run_logs
ORDER BY id DESC
LIMIT 10;
```

---

## 8. 重要风险和处理建议

### 风险 1：`processed_posts` 无数据

工作包 5 依赖工作包 4。

后端负责人在做工作包 5 前应先运行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\check_wp4.bat
```

如果 `processed_posts = 0`，不要硬写假事件，应先完成数据同步和清洗。

### 风险 2：`event_key` 唯一约束冲突

当前 `public_events.event_key` 是唯一字段。

Agent 当前事件 key 只是分类名，必须在入库前扩展成更细 key。

### 风险 3：工作包 5 写的是 `public_analysis_runs`，主项目是 `agent_run_logs`

当前建议：

- 短期使用 `agent_run_logs`。
- 文档或验收说明中注明它承担 `public_analysis_runs` 的作用。
- 若后续老师强制要求表名，再建 `public_analysis_runs`。

### 风险 4：现有 `/api/events` 会泄露 draft

必须改。

普通用户接口默认只能查：

```text
status = published
```

管理员接口才可以看全部状态。

### 风险 5：前端有 `/admin/events` 导航，但路由未实现

前端当前导航配置包含：

```text
/admin/events
```

但 `frontend\src\router\index.js` 没有实际 admin 子路由。

这不阻塞后端工作包 5，但后端完成接口后，前端负责人还需要补管理员页面。

---

## 9. 最小验收流程

后端负责人完成工作包 5 后，按以下流程验收。

### 9.1 数据前置

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\verify_db.bat
.\check_wp2.bat
.\check_wp4.bat
```

要求：

- 使用共享 MySQL。
- `processed_posts >= 1`。
- `processed_posts` 能转换成 OpinionNote。

### 9.2 启动后端

```powershell
.\run.bat
```

### 9.3 调用 Agent 分析入口

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:9000/api/agent/public/analyze" -ContentType "application/json" -Body '{"keyword":"","limit":50,"persist":true}'
```

成功标志：

- 返回 `event_count > 0`。
- 返回事件状态是 `draft`。
- `public_events` 新增 `draft`。
- `event_post_links` 新增代表内容关联。
- `agent_run_logs` 新增运行记录。

### 9.4 管理员审核

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/admin/events?status=draft"
```

选择一个事件 ID 后：

```powershell
Invoke-RestMethod -Method Patch "http://127.0.0.1:9000/api/admin/events/1/status" -ContentType "application/json" -Body '{"status":"published","review_comment":"确认发布","reviewer_id":"admin"}'
```

成功标志：

- `public_events.status` 变成 `published`。
- `reviewed_by/reviewed_at/review_comment` 有值。
- `event_review_logs` 新增记录。

### 9.5 普通用户查看

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/events"
```

成功标志：

- 只能看到 `published`。
- 不能看到 `draft/rejected/archived`。

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/events/1"
```

成功标志：

- 返回事件详情。
- 返回代表性帖子。
- 返回风险依据、关注点、来源关键词、时间范围。

---

## 10. 建议交付清单

后端负责人完成工作包 5 时，至少提交这些文件变化：

```text
backend\agent\public_opinion_core\adapter.py
backend\agent\public_opinion_core\clustering.py
backend\agent\public_opinion_core\normalizer.py
backend\agent\public_opinion_core\schemas.py
backend\agent\public_opinion_core\scoring.py
backend\agent\public_opinion_core\sentiment_risk.py
backend\agent\public_opinion_core\__init__.py
backend\services\__init__.py
backend\services\public_opinion_adapter.py
backend\schemas.py
backend\routers\api.py
```

如果拆路由，则还包括：

```text
backend\routers\public_agent.py
backend\routers\admin_events.py
backend\main.py
```

建议新增验收脚本：

```text
check_wp5.bat
scripts\check_wp5.py
```

`check_wp5.py` 至少检查：

- `/api/agent/public/analyze` 能生成 draft。
- `public_events` 有新增 draft。
- `event_post_links` 有关联。
- `agent_run_logs` 有记录。
- PATCH 发布后普通用户接口能看到。

---

## 11. 给后端负责人的一句话结论

Agent 规则本体已经可用，不要重写。后端工作包 5 的主要工作不是“继续研究 Agent”，而是把 `processed_posts -> OpinionNote -> OpinionEvent` 这条离线链路接入主项目后端，并完成 `public_events/event_post_links/agent_run_logs` 入库和事件审核接口。
