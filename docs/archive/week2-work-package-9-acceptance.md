# Week2 后端工作包 9 验收记录：日志、反馈、爬虫任务记录

生成时间：2026-06-06

## 1. 工作包目标

本工作包补齐第二周最小可用记录体系，让管理员后台能够解释“系统发生了什么”：

```text
爬虫 / 同步 / 导入任务 -> crawl_tasks
系统异常与关键日志 -> system_logs
普通用户反馈 -> user_feedback
管理员操作 -> admin_operation_logs
事件审核 -> event_review_logs
```

第二周不做完整日志平台、实时告警、复杂检索、用户行为埋点。

## 2. 实现结果

已完成：

- 新增统一日志服务：`backend/services/log_service.py`
- 新增普通用户反馈接口：`POST /api/feedback`
- 新增管理员日志与审核记录接口：
  - `GET /api/admin/system-logs`
  - `GET /api/admin/operation-logs`
  - `GET /api/admin/events/{event_id}/review-logs`
- 新增反馈处理接口：
  - `PATCH /api/admin/feedback/{feedback_id}/status`
- 扩展爬虫任务列表：
  - `GET /api/admin/crawl-tasks` 支持 `task_type`
- 扩展后台概览：
  - `recent_crawl_task`
  - `pending_feedback_count`
  - `recent_system_errors_count`
  - `draft_events_count`
- 改造同步脚本：
  - `scripts/sync_media_to_raw_posts.py`
  - `scripts/process_raw_posts.py`
- 新增验收脚本：
  - `scripts/check_wp9.py`

## 3. 修改文件

新增：

- `backend/services/log_service.py`
- `backend/routers/feedback.py`
- `scripts/check_wp9.py`
- `docs/week2-work-package-9-acceptance.md`

修改：

- `backend/main.py`
- `backend/services/admin_service.py`
- `backend/routers/admin.py`
- `backend/routers/admin_events.py`
- `backend/routers/agent_public.py`
- `scripts/sync_media_to_raw_posts.py`
- `scripts/process_raw_posts.py`

## 4. 数据表使用说明

本次没有新建额外表，因为共享数据库已经具备工作包 9 所需核心表：

- `crawl_tasks`
- `system_logs`
- `user_feedback`
- `admin_operation_logs`
- `event_review_logs`

字段兼容说明：

- 工作包文档中的 `system_logs.detail_json` 使用现有 `system_logs.detail` 承载 JSON。
- 工作包文档中的 `trace_id` 使用现有 `system_logs.request_id` 承载。
- 工作包文档中的 `related_task_id` 当前写入 `system_logs.detail` JSON 内。
- 工作包文档中的 `crawl_tasks.output_path` 使用现有 `crawl_tasks.report_path` 承载。
- 工作包文档中的 `before_json` / `after_json` 使用现有 `admin_operation_logs.detail` JSON 承载。

这样做可以避免破坏已存在的共享数据库表结构。

## 5. 接口说明

### 5.1 普通用户提交反馈

```http
POST /api/feedback
```

请求示例：

```json
{
  "feedback_type": "content_issue",
  "content": "这个事件好像和学校无关",
  "contact": "可选联系方式"
}
```

写入结果：

```text
user_feedback.status = pending
```

### 5.2 管理员查看和处理反馈

```http
GET   /api/admin/feedback
PATCH /api/admin/feedback/{feedback_id}/status
```

反馈状态支持：

```text
pending
handling
resolved
ignored
handled
```

处理反馈时会写入：

```text
admin_operation_logs.action = update_feedback_status
```

### 5.3 管理员查看任务和日志

```http
GET /api/admin/crawl-tasks
GET /api/admin/system-logs
GET /api/admin/operation-logs
GET /api/admin/events/{event_id}/review-logs
```

其中：

- `crawl-tasks` 支持 `platform`、`status`、`task_type`。
- `system-logs` 支持 `level`、`module`。
- `operation-logs` 支持 `action`、`target_type`。
- `review-logs` 按事件返回审核历史。

## 6. 脚本记录接入

### 6.1 MediaCrawler 同步

`scripts/sync_media_to_raw_posts.py` 已支持任务记录：

```python
sync_media_to_raw_posts(
    platforms=["xhs"],
    limit=1,
    dry_run=True,
    record_task=True,
    created_by="wp9_check",
)
```

说明：

- 非 `dry-run` 默认记录任务。
- `dry-run` 默认不记录，除非显式传入 `record_task=True`。
- 任务成功写入 `crawl_tasks`。
- 行级失败时写入 `system_logs` warning。
- 整体异常时写入 `system_logs` error。

### 6.2 raw_posts 清洗

`scripts/process_raw_posts.py` 已支持同样的任务记录逻辑：

```python
process_raw_posts(
    limit=100,
    dry_run=False,
    record_task=True,
    created_by="system",
)
```

## 7. 验收命令与结果

### 7.1 WP9 验收

执行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\check_wp9.py
```

关键结果：

```text
[OK] using shared MySQL
[OK] WP9 feedback/log routes registered
[OK] sync task writes crawl_tasks record
[OK] POST /api/feedback creates pending feedback
[OK] admin feedback list shows submitted feedback
[OK] feedback status update writes admin_operation_logs
[OK] write_system_log creates system_logs record
[OK] admin system-logs list shows system log
[OK] admin operation-logs returns operation records
[OK] public event exists for review-log check
[OK] event review status change is visible in review logs
[OK] admin overview includes WP9 operational indicators

WP9 logs, feedback, crawl task checks PASSED.
```

### 7.2 回归验收

工作包 8：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp8.py
```

结果：

```text
WP8 admin backend API checks PASSED.
```

工作包 5：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp5.py --limit 50
```

结果：

```text
WP5 public opinion Agent checks PASSED.
```

工作包 4：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py --min-raw 1 --min-processed 1 --min-notes 1
```

结果：

```text
WP4 data pipeline checks PASSED.
```

## 8. 共享数据库验收后状态

```text
crawl_tasks: 1
system_logs: 1
user_feedback: 1
pending_feedback: 0
admin_operation_logs: 6
event_review_logs: 6
```

说明：

- `pending_feedback = 0` 是因为验收脚本提交反馈后，又通过管理员接口把该反馈处理为 `resolved`。
- `crawl_tasks = 1` 来自 WP9 验收脚本触发的一次 `xhs` dry-run 同步任务记录。
- `system_logs = 1` 来自 WP9 验收脚本写入的系统错误日志。
- `admin_operation_logs` 和 `event_review_logs` 包含此前工作包 8、工作包 5 与本次工作包 9 的验收记录。

## 9. 验收结论

工作包 9 的最小闭环已经完成：

```text
同步任务可记录
-> 后台可查看 crawl_tasks
-> 用户可提交反馈
-> 后台可查看并处理反馈
-> 系统关键日志可写入 system_logs
-> 后台可查看 system_logs
-> 管理员操作可写入 admin_operation_logs
-> 事件审核可写入并查看 event_review_logs
```

后续可继续完善：

- 真实爬虫运行脚本也统一接入 `create_crawl_task()` / `finish_crawl_task()`。
- 后台页面展示系统日志和操作日志。
- 对日志增加时间范围筛选。
- 对 `system_logs.detail` 做前端 JSON 格式化展示。
- 为反馈处理增加更完整的状态流转和备注历史。
