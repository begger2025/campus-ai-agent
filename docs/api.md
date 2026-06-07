# API 文档：Week2 后端接口

基础地址：

```text
http://127.0.0.1:9000
```

业务接口统一使用 `/api` 前缀；`/health` 是非 `/api` 的服务存活检查。

统一成功响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

## 公共接口

### GET /health

服务存活检查。

响应示例：

```json
{
  "status": "ok"
}
```

### GET /api/ping

检查 API 与数据库配置。

响应 `data` 示例：

```json
{
  "pong": true,
  "timestamp": "2026-06-07T12:00:00",
  "database": "campus_ai_agent"
}
```

### GET /api/posts

读取 `raw_posts` 统一原始帖子。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大 100 |

响应 `data` 示例：

```json
{
  "items": [
    {
      "id": 1,
      "platform": "xhs",
      "external_id": "note_001",
      "source_table": "xhs_note",
      "source_raw_id": "note_001",
      "source_keyword": "campus",
      "title": "Campus topic",
      "content": "Post content",
      "author": "author",
      "publish_time": "2026-06-07T10:00:00",
      "url": "https://example.com/post/1",
      "status": "normal"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### GET /api/events

普通用户查看已发布公共舆情事件。该接口始终只返回 `status = published` 的事件。

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页条数，最大 100 |
| status | string | 空 | 保留参数；普通用户接口仍只返回 published |

响应 `data` 示例：

```json
{
  "items": [
    {
      "id": "EVT-1",
      "raw_id": 1,
      "event_key": "public-opinion:campus:001",
      "title": "Campus logistics issue",
      "summary": "Students are discussing a logistics issue.",
      "topic": "logistics",
      "event_type": "public_opinion",
      "sentiment": "negative",
      "status": "published",
      "heat_score": 75.0,
      "risk_level": "medium",
      "risk_score": 0.6,
      "confidence": 0.8,
      "source_count": 3,
      "source_platforms": ["xhs", "weibo"],
      "source_post_ids": [1, 2, 3]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

### GET /api/events/{event_id}

普通用户查看已发布事件详情。`event_id` 使用数据库中的整数 id，不是 `EVT-1` 字符串。

响应 `data` 包含事件基础字段和：

```json
{
  "representative_posts": [],
  "date_range": {},
  "source_keywords": [],
  "top_tags": [],
  "concerns": [],
  "risk_reasons": []
}
```

### POST /api/feedback

普通用户提交反馈。

请求体：

```json
{
  "feedback_type": "content_issue",
  "content": "This event summary is inaccurate.",
  "contact": "user@example.com",
  "user_id": "anonymous",
  "target_type": "public_event",
  "target_id": "1"
}
```

响应 `data` 示例：

```json
{
  "id": 1,
  "status": "pending",
  "feedback_type": "content_issue",
  "created_at": "2026-06-07T12:00:00"
}
```

## 认证接口

### POST /api/auth/login

登录并获取 Bearer token。

请求体：

```json
{
  "username": "admin",
  "password": "password"
}
```

响应 `data` 示例：

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "display_name": "Admin",
    "status": "active"
  }
}
```

### GET /api/auth/me

读取当前登录用户信息。需要请求头：

```text
Authorization: Bearer <access_token>
```

## 管理员接口

以下接口均需要管理员 token。无 token 返回 401，普通用户 token 返回 403。

### GET /api/admin/overview

后台概览。

响应 `data` 包含：

```json
{
  "raw_posts_count": 0,
  "processed_posts_count": 0,
  "events": {},
  "crawl_tasks": {},
  "feedback": {},
  "system_logs": {}
}
```

### GET /api/admin/raw-posts

后台查看原始帖子。

查询参数：

```text
page, page_size, platform, keyword, start_date, end_date
```

### GET /api/admin/events

后台查看所有事件，可按状态过滤。

查询参数：

```text
status=all|draft|published|rejected|archived
keyword
risk_level
page
page_size
```

### GET /api/admin/events/{event_id}

后台查看事件详情。

### PATCH /api/admin/events/{event_id}/status

管理员审核事件并写入审核日志和管理员操作日志。

请求体：

```json
{
  "status": "published",
  "review_comment": "Approved by smoke test"
}
```

合法状态：

```text
draft
published
rejected
archived
```

### GET /api/admin/events/{event_id}/review-logs

查看某个事件的审核记录。

### GET /api/admin/crawl-tasks

查看爬虫、同步、清洗任务记录。

查询参数：

```text
page, page_size, status, platform, task_type
```

### POST /api/agent/public/analyze

管理员触发公共舆情 Agent 分析，并把结果写入 `public_events`、`event_post_links`、`agent_run_logs`。

请求体：

```json
{
  "keyword": "campus",
  "limit": 50,
  "platforms": [],
  "start_time": "",
  "end_time": "",
  "persist": true,
  "created_by": "admin"
}
```

### GET /api/admin/feedback

后台查看用户反馈。

查询参数：

```text
page, page_size, status
```

### PATCH /api/admin/feedback/{feedback_id}/status

管理员处理反馈。

请求体：

```json
{
  "status": "resolved",
  "handle_note": "Handled"
}
```

合法状态：

```text
pending
handling
resolved
ignored
handled
```

### GET /api/admin/system-logs

后台查看系统日志。

查询参数：

```text
page, page_size, level, module
```

### GET /api/admin/operation-logs

后台查看管理员操作日志。

查询参数：

```text
page, page_size, action, target_type
```

## Smoke Test 覆盖接口

`scripts\smoke_backend.ps1` 会覆盖以下接口：

```text
/health
/api/posts
/api/events
/api/auth/login
/api/admin/overview
/api/admin/events/{event_id}/status
/api/admin/events/{event_id}/review-logs
/api/feedback
/api/admin/feedback
/api/admin/system-logs
/api/admin/operation-logs
```
