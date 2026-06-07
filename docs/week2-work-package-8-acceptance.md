# Week2 后端工作包 8 验收记录：管理员后台 API

生成时间：2026-06-06

## 1. 工作包目标

本工作包完成第二周最小可用管理员后台 API，支持：

- 管理员登录与当前用户识别。
- `user` / `admin` 两类角色区分。
- `/api/admin/*` 管理员接口鉴权。
- 后台概览、原始采集数据、公共舆情事件、爬虫任务、用户反馈查询。
- 管理员审核公共舆情事件。
- 关键审核操作写入 `event_review_logs` 和 `admin_operation_logs`。

第二周不实现复杂 RBAC、菜单级权限、refresh token、管理员用户管理完整系统。

## 2. 实现结果

已新增：

- `backend/services/auth_service.py`
- `backend/services/admin_service.py`
- `backend/routers/auth.py`
- `backend/routers/admin.py`
- `scripts/check_wp8.py`
- `docs/week2-work-package-8-acceptance.md`

已修改：

- `backend/main.py`
- `backend/routers/admin_events.py`
- `backend/routers/agent_public.py`
- `backend/routers/api.py`
- `.env.example`

## 3. 接口清单

认证接口：

```http
POST /api/auth/login
GET  /api/auth/me
```

管理员后台接口：

```http
GET /api/admin/overview
GET /api/admin/raw-posts
GET /api/admin/events
GET /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
GET /api/admin/crawl-tasks
GET /api/admin/feedback
```

管理员专用 Agent 接口：

```http
POST /api/agent/public/analyze
```

公开接口保持普通用户可访问：

```http
GET /api/posts
GET /api/events
GET /api/events/{event_id}
```

其中 `GET /api/events` 和 `GET /api/events/{event_id}` 只返回 `published` 事件。

## 4. 权限规则

已实现规则：

- 无 token 调用管理员依赖：返回 `401`。
- 普通用户调用管理员依赖：返回 `403`。
- 管理员可访问 `/api/admin/*`。
- `POST /api/agent/public/analyze` 已改为管理员专用。

当前使用最小 JWT 实现，基于 HMAC SHA256，不额外引入第三方依赖。密码使用 `pbkdf2_sha256` 哈希保存，不保存明文密码。

## 5. 管理员初始化

`.env.example` 已新增：

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123456
ADMIN_DISPLAY_NAME=管理员
JWT_SECRET_KEY=replace-with-a-random-secret
JWT_EXPIRE_MINUTES=1440
```

启动时会执行默认管理员初始化：

```text
如果 users 中不存在 ADMIN_USERNAME 对应账号，则创建 admin 用户。
```

如果 `.env` 暂未配置管理员信息，代码会使用开发默认值，保证本地验收不阻塞。正式演示或部署前应修改 `ADMIN_PASSWORD` 和 `JWT_SECRET_KEY`。

## 6. 审核与审计日志

管理员调用：

```http
PATCH /api/admin/events/{event_id}/status
```

会同时完成：

- 更新 `public_events.status`
- 写入 `event_review_logs`
- 写入 `admin_operation_logs`

由于当前共享数据库的 `admin_operation_logs` 表没有单独的 `before_json` / `after_json` 字段，本次将变更前后状态写入 `detail` 字段中的 JSON：

```json
{
  "before_json": {},
  "after_json": {}
}
```

## 7. 验收命令与结果

### 7.1 WP8 验收

执行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\check_wp8.py
```

关键结果：

```text
[OK] using shared MySQL
[OK] WP8 auth/admin routes registered
[OK] missing token returns 401
[OK] normal user admin access returns 403
[OK] admin login returns access token
[OK] Bearer token resolves current admin
[OK] GET /api/auth/me returns current admin profile
[OK] admin overview returns dashboard counts
[OK] admin raw-posts returns stable paginated structure
[OK] admin crawl-tasks returns stable structure
[OK] admin feedback returns stable structure
[OK] public event exists for status review
[OK] admin event status patch updates event
[OK] event_review_logs records admin review
[OK] admin_operation_logs records status update

WP8 admin backend API checks PASSED.
```

### 7.2 WP5 回归验收

执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp5.py --limit 50
```

关键结果：

```text
WP5 public opinion Agent checks PASSED.
```

### 7.3 WP4 回归验收

执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py --min-raw 1 --min-processed 1 --min-notes 1
```

关键结果：

```text
WP4 data pipeline checks PASSED.
```

## 8. 共享数据库验收后状态

```text
users: 2
admins: 1
raw_posts: 100
processed_posts: 100
public_events: 4
published_events: 1
admin_operation_logs: 2
event_review_logs: 3
crawl_tasks: 0
user_feedback: 0
```

说明：

- `scripts/check_wp8.py` 创建了验收用管理员账号和普通用户账号。
- `crawl_tasks` 和 `user_feedback` 当前为空，但接口已返回稳定分页结构。
- 本次验收触发了事件状态修改，因此 `admin_operation_logs` 和 `event_review_logs` 均增加记录。

## 9. 验收结论

工作包 8 的最小闭环已经完成：

```text
管理员登录
-> 获取 Bearer token
-> /api/admin/* 鉴权
-> 管理员查看概览、采集数据、任务、反馈
-> 管理员审核公共舆情事件
-> 写入审核日志和操作日志
-> 普通用户不能访问管理员接口
```

后续可继续完善：

- 前端登录页与后台页面联调。
- 管理员修改反馈处理状态接口。
- 管理员查看 `admin_operation_logs` 的列表接口。
- 更严格的事件状态流转规则。
- refresh token 与更完整的账号管理能力。
