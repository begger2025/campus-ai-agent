# Week2 后端给前端的接口交接与接入指南

> 文档定位：这是一份由后端负责人交付给前端负责人的 week2 接口接入指南。目标是让前端负责人明确：后端现在已经提供了哪些接口、每个前端工作包应该接哪些接口、应该按什么步骤完成联调。

生成日期：2026-06-07

适用项目：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
```

前端目录：

```text
D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend
```

后端基础地址：

```text
http://127.0.0.1:9000
```

前端开发地址：

```text
http://localhost:5173
```

## 1. 后端当前状态

### 1.1 后端服务与数据库状态

当前后端已经接入共享 MySQL 数据库 `campus_ai_agent`。本次检查中已验证：

```powershell
Invoke-RestMethod http://127.0.0.1:9000/health
Invoke-RestMethod http://127.0.0.1:9000/api/ping
Invoke-RestMethod "http://127.0.0.1:9000/api/events?status=published&page=1&page_size=5"
```

结果摘要：

```text
/health -> status=ok
/api/ping -> code=0, database=campus_ai_agent
/api/events -> code=0, total=6, first_id=EVT-9, first_raw_id=9, first_status=published
```

这说明后端当前不是空接口，前端可以直接开始真实接口联调。

### 1.2 后端接口统一响应格式

成功响应统一为：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

前端 `frontend/src/api/http.js` 已经能解包这种格式：

```js
if (body && typeof body.code === 'number') {
  if (body.code === 0) {
    return body.data !== undefined ? body.data : body
  }
}
```

前端继续沿用这个 `http` 实例即可。

### 1.3 权限规则

当前后端有三类访问：

| 类型 | 说明 |
|---|---|
| 公开接口 | 不需要 token，例如 `/api/events`、`/api/feedback` |
| 登录用户接口 | 需要 Bearer token，例如 `/api/auth/me` |
| 管理员接口 | 需要管理员 Bearer token，例如 `/api/admin/*`、`/api/agent/public/analyze` |

管理员接口权限规则：

```text
无 token -> 401
普通用户 token -> 403
管理员 token -> 200
```

前端请求头格式：

```text
Authorization: Bearer <access_token>
```

### 1.4 前端必须注意的 ID 口径

公开事件列表接口返回两个 ID：

```json
{
  "id": "EVT-9",
  "raw_id": 9
}
```

含义：

| 字段 | 用途 |
|---|---|
| `id` | 前端展示用字符串，例如 `EVT-9` |
| `raw_id` | 后端数据库整数 ID，详情、审核、反馈接口优先使用这个 |

重要规则：

```text
GET /api/events/{event_id}
GET /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
GET /api/admin/events/{event_id}/review-logs
```

这些接口的 `event_id` 都应使用整数 `raw_id`，不是 `EVT-9` 字符串。

因此前端列表页跳详情时建议使用：

```js
router.push(`/events/${event.raw_id}`)
```

而不是：

```js
router.push(`/events/${event.id}`)
```

## 2. 后端接口总览

### 2.1 健康检查

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/health` | 公开 | 后端服务存活检查 |
| GET | `/api/ping` | 公开 | API 和数据库连接检查 |

### 2.2 认证接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | 登录，返回 Bearer token |
| GET | `/api/auth/me` | 登录用户 | 读取当前用户信息 |

### 2.3 公开事件与反馈接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/api/events` | 公开 | 获取已发布事件列表，只返回 `published` |
| GET | `/api/events/{event_id}` | 公开 | 获取已发布事件详情，`event_id` 为整数 |
| POST | `/api/feedback` | 公开 | 普通用户提交反馈 |

### 2.4 公共舆情 Agent 接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/api/agent/public/analyze` | 管理员 | 触发公共舆情 Agent 分析，并可写入事件与日志 |

注意：当前后端把 Agent 分析接口设为管理员专用。如果前端希望普通用户也能在 `/opinion` 触发真实分析，需要项目负责人确认是否修改权限规则。

### 2.5 管理员后台接口

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/api/admin/overview` | 管理员 | 后台概览 KPI |
| GET | `/api/admin/raw-posts` | 管理员 | 原始采集数据管理 |
| GET | `/api/admin/events` | 管理员 | 后台查看全部事件 |
| GET | `/api/admin/events/{event_id}` | 管理员 | 后台查看事件详情 |
| PATCH | `/api/admin/events/{event_id}/status` | 管理员 | 发布、驳回、归档事件 |
| GET | `/api/admin/events/{event_id}/review-logs` | 管理员 | 查看事件审核日志 |
| GET | `/api/admin/crawl-tasks` | 管理员 | 查看爬虫、同步、清洗任务 |
| GET | `/api/admin/feedback` | 管理员 | 查看用户反馈 |
| PATCH | `/api/admin/feedback/{feedback_id}/status` | 管理员 | 处理用户反馈 |
| GET | `/api/admin/system-logs` | 管理员 | 查看系统日志 |
| GET | `/api/admin/operation-logs` | 管理员 | 查看管理员操作日志 |

## 3. 前端工作包与接口映射

| 前端工作包 | 页面/模块 | 必接接口 | 当前后端状态 |
|---|---|---|---|
| FE-01 | 路由、导航、权限骨架 | `/api/auth/login`、`/api/auth/me` | 已提供 |
| FE-02 | API 请求层与数据状态 | 所有 `/api/...` 接口 | 已提供基础契约 |
| FE-03 | 登录页 `/login` | `POST /api/auth/login`、`GET /api/auth/me` | 已提供 |
| FE-04 | 舆情工作台 `/opinion` | `POST /api/agent/public/analyze`、`GET /api/events` | 已提供，分析接口管理员专用 |
| FE-05 | 公开事件列表与详情 | `GET /api/events`、`GET /api/events/{id}`、`POST /api/feedback` | 已提供 |
| FE-06 | 后台概览 `/admin` | `GET /api/admin/overview` | 已提供 |
| FE-07 | 事件审核 `/admin/events` | `GET /api/admin/events`、`GET /api/admin/events/{id}`、`PATCH /api/admin/events/{id}/status`、`GET /api/admin/events/{id}/review-logs` | 已提供 |
| FE-08 | 数据管理 `/admin/raw-posts` | `GET /api/admin/raw-posts` | 已提供 raw_posts；processed_posts 单独接口暂缺 |
| FE-09 | 运维反馈 `/admin/ops` | `/api/admin/feedback`、`/api/admin/crawl-tasks`、`/api/admin/system-logs`、`/api/admin/operation-logs` | 已提供；agent_run_logs 单独列表接口暂缺 |
| FE-10 | 前后端联调验收文档 | `/health`、`/api/ping`、全链路接口 | 后端 smoke test 已提供 |

## 4. 前端公共接入准备

### 4.1 保留现有 axios 封装

前端已有：

```text
frontend/src/api/http.js
```

这个文件已经完成：

- `baseURL: '/api'`
- 自动注入 `Authorization: Bearer <token>`
- 统一解包 `{ code, message, data }`
- 401 跳 `/login`
- 403 跳 `/forbidden`

前端后续新增 API 模块时都应复用：

```js
import http from './http'
```

### 4.2 建议新增 API 模块

建议前端补齐以下文件：

```text
frontend/src/api/auth.js
frontend/src/api/agent.js
frontend/src/api/events.js
frontend/src/api/feedback.js
frontend/src/api/admin.js
frontend/src/api/adminEvents.js
frontend/src/api/adminOps.js
```

当前已有：

```text
frontend/src/api/http.js
frontend/src/api/events.js
frontend/src/api/posts.js
```

但 `events.js` 目前存在静默 fallback 到 mock 的逻辑，验收阶段建议移除或至少显式提示“后端失败，当前为 mock”。

### 4.3 建议统一分页处理

后端分页统一返回：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

前端页面应保留：

```js
const loading = ref(false)
const error = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
```

每个表格页至少处理：

```text
loading
error
empty
success
```

## 5. FE-01 路由、导航、权限骨架接入指南

### 5.1 后端提供的能力

FE-01 依赖的后端能力：

```http
POST /api/auth/login
GET  /api/auth/me
```

权限规则：

```text
admin role -> 可访问 /api/admin/*
user role -> 访问 /api/admin/* 返回 403
无 token -> 访问 /api/admin/* 返回 401
```

### 5.2 前端当前问题

当前 `frontend/src/router/index.js` 中没有注册：

```text
/admin
/admin/events
/admin/raw-posts
/admin/ops
```

但 `frontend/src/config/nav.js` 已经有这些菜单。因此现在管理员点击后台菜单会进入 404。

### 5.3 前端接入步骤

第一步：新增后台页面组件。

```text
frontend/src/views/admin/AdminOverviewView.vue
frontend/src/views/admin/AdminEventsView.vue
frontend/src/views/admin/AdminRawPostsView.vue
frontend/src/views/admin/AdminOpsView.vue
```

第二步：在 `frontend/src/router/index.js` 注册路由。

建议加入到 `MainLayout` 的 children 中：

```js
{
  path: 'admin',
  name: 'AdminOverview',
  component: () => import('@/views/admin/AdminOverviewView.vue'),
  meta: { title: '后台概览', subtitle: '管理员后台', roles: ['admin'] },
},
{
  path: 'admin/events',
  name: 'AdminEvents',
  component: () => import('@/views/admin/AdminEventsView.vue'),
  meta: { title: '事件审核', subtitle: '公共舆情事件审核', roles: ['admin'] },
},
{
  path: 'admin/raw-posts',
  name: 'AdminRawPosts',
  component: () => import('@/views/admin/AdminRawPostsView.vue'),
  meta: { title: '数据管理', subtitle: '采集与清洗数据', roles: ['admin'] },
},
{
  path: 'admin/ops',
  name: 'AdminOps',
  component: () => import('@/views/admin/AdminOpsView.vue'),
  meta: { title: '运维反馈', subtitle: '反馈、任务与日志', roles: ['admin'] },
}
```

第三步：确认 `/events` 是否允许游客访问。

如果项目决定公开事件对游客开放，则把 `/events` 和 `/events/:id` 设置为：

```js
meta: { title: '事件列表', subtitle: '公开舆情事件浏览', guest: true }
```

并调整路由守卫，让 `guest: true` 页面不强制登录。

第四步：验证权限。

前端需要验证：

```text
未登录访问 /admin -> 跳 /login
普通用户访问 /admin -> 跳 /forbidden
管理员访问 /admin -> 进入后台概览
```

## 6. FE-02 API 请求层与数据状态接入指南

### 6.1 后端接口契约

所有业务接口走：

```text
/api/...
```

成功响应走：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

失败响应主要分两类：

| 类型 | 形式 | 前端处理 |
|---|---|---|
| 业务错误 | `{ code, message, data }` 中 `code != 0` | 显示 `message` |
| HTTP 错误 | 401、403、404、500 | 按状态码处理 |

### 6.2 前端接入步骤

第一步：保留 `frontend/src/api/http.js` 的 `/api` baseURL。

第二步：移除业务页面里直接写死 mock 数据的优先级。

尤其是：

```text
frontend/src/api/events.js
```

当前失败后自动返回 mock：

```js
return [...mockPublishedEvents]
```

建议验收阶段改成抛错：

```js
export async function fetchPublishedEvents(params = {}) {
  const data = await http.get('/events', {
    params: { page: 1, page_size: 20, ...params },
  })
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    total: data?.total ?? 0,
    page: data?.page ?? params.page ?? 1,
    page_size: data?.page_size ?? params.page_size ?? 20,
  }
}
```

第三步：每个页面都要显示接口失败状态。

最少要有：

```text
loading: 加载中
error: 后端错误或网络错误
empty: items.length === 0
success: 正常显示数据
```

第四步：Network 验收。

浏览器 F12 Network 中，业务请求应看到：

```text
/api/auth/login
/api/events
/api/events/{id}
/api/feedback
/api/admin/overview
/api/admin/events
/api/admin/raw-posts
/api/admin/feedback
```

不能再出现业务请求直接访问：

```text
/events
/posts
/feedbacks
```

## 7. FE-03 登录页 `/login` 接入指南

### 7.1 后端接口

登录：

```http
POST /api/auth/login
```

请求体：

```json
{
  "username": "admin",
  "password": "由后端负责人提供"
}
```

响应 `data`：

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

读取当前用户：

```http
GET /api/auth/me
```

请求头：

```text
Authorization: Bearer <access_token>
```

### 7.2 前端当前问题

当前登录使用：

```text
frontend/src/auth/session.js
mockLogin()
```

并存储：

```text
mock-admin-token
mock-user-token
```

这些 token 不能访问后端管理员接口。

### 7.3 前端接入步骤

第一步：新增 `frontend/src/api/auth.js`。

```js
import http from './http'

export function login(username, password) {
  return http.post('/auth/login', { username, password })
}

export function fetchMe() {
  return http.get('/auth/me')
}
```

第二步：修改 `session.js`，提供真实 session 写入函数。

建议 session 结构保持：

```js
{
  token: data.access_token,
  user: {
    id: data.user.id,
    username: data.user.username,
    displayName: data.user.display_name || data.user.username,
    role: data.user.role,
    status: data.user.status,
  },
}
```

第三步：修改 `LoginView.vue`。

登录按钮点击后：

```js
const data = await login(username.value, password.value)
saveSessionFromLoginResponse(data)
router.push(data.user.role === 'admin' ? '/admin' : '/opinion')
```

第四步：登录失败提示。

后端登录失败返回 401，前端应显示：

```text
用户名或密码错误
```

而不是继续显示 mock 账号提示。

第五步：测试。

前端负责人需要向后端负责人确认：

```text
管理员测试账号
普通用户测试账号
```

不要继续使用前端 mock 的：

```text
admin / admin123
user / user123
```

除非后端负责人明确也创建了这两个账号。

## 8. FE-04 舆情工作台 `/opinion` 接入指南

### 8.1 后端接口

触发公共舆情 Agent 分析：

```http
POST /api/agent/public/analyze
```

权限：

```text
管理员 token
```

请求体：

```json
{
  "keyword": "中山大学",
  "limit": 50,
  "platforms": ["xhs"],
  "start_time": "",
  "end_time": "",
  "persist": true,
  "created_by": "admin"
}
```

响应 `data`：

```json
{
  "status": "success",
  "input_count": 50,
  "event_count": 3,
  "warnings": [],
  "events": [
    {
      "id": 1,
      "event_key": "keyword:中山大学",
      "title": "中山大学相关讨论",
      "summary": "聚合摘要",
      "topic": "keyword:中山大学",
      "event_type": "keyword:中山大学",
      "sentiment": "positive",
      "risk_level": "low",
      "risk_score": 26,
      "heat_score": 257166,
      "source_count": 14,
      "status": "draft"
    }
  ],
  "payload_counts": {
    "public_events": 3,
    "event_post_links": 10,
    "agent_run_logs": 1
  },
  "run_log_id": 6
}
```

### 8.2 前端当前问题

当前 `/opinion` 的 `runAnalysis()` 是前端模拟：

```js
await new Promise(r => setTimeout(r, 1200))
```

没有调用后端 Agent 接口。

### 8.3 前端接入步骤

第一步：新增 `frontend/src/api/agent.js`。

```js
import http from './http'

export function runPublicOpinionAnalysis(payload) {
  return http.post('/agent/public/analyze', {
    keyword: payload.keyword || '',
    limit: payload.limit || 50,
    platforms: payload.platforms || [],
    start_time: payload.start_time || '',
    end_time: payload.end_time || '',
    persist: payload.persist ?? true,
    created_by: payload.created_by || 'frontend',
  })
}
```

第二步：修改 `OpinionView.vue` 的 `runAnalysis()`。

逻辑应改为：

```text
校验关键词
-> loading=true
-> POST /api/agent/public/analyze
-> 展示 data.events
-> 提示生成了多少事件
-> 如果事件 status=draft，引导管理员去 /admin/events 审核
-> loading=false
```

第三步：处理权限。

当前后端要求管理员权限。前端应二选一：

| 方案 | 做法 |
|---|---|
| 管理员专用 | 只有 admin 角色显示“开始分析”按钮 |
| 普通用户也可触发 | 请后端负责人修改接口权限，不再使用 `require_admin` |

建议 week2 先走“管理员专用”，减少权限争议。

第四步：分析成功后的页面表现。

不要只显示聊天文字。至少显示：

```text
input_count
event_count
warnings
events[].title
events[].summary
events[].risk_level
events[].source_count
events[].status
```

第五步：分析失败后的页面表现。

后端 500 时应显示：

```text
Agent 分析失败，请检查关键词、processed_posts 数据量或后端日志
```

同时管理员可去 `/admin/ops` 查看 system logs 或 operation logs。

## 9. FE-05 公开事件列表与详情接入指南

### 9.1 后端接口

事件列表：

```http
GET /api/events?page=1&page_size=20
```

说明：

```text
只返回 status=published 的事件
status 参数即使传入也不会让普通接口返回 draft/rejected/archived
```

事件详情：

```http
GET /api/events/{event_id}
```

其中 `event_id` 是整数 `raw_id`。

用户反馈：

```http
POST /api/feedback
```

### 9.2 事件列表字段

列表项核心字段：

```json
{
  "id": "EVT-9",
  "raw_id": 9,
  "title": "中山大学校长相关讨论",
  "summary": "聚合摘要",
  "topic": "keyword:中山大学校长",
  "event_type": "keyword:中山大学校长",
  "sentiment": "neutral",
  "status": "published",
  "heat_score": 4927,
  "risk_level": "low",
  "riskLabel": "低风险",
  "risk_score": 26,
  "confidence": 0.7,
  "source_count": 4,
  "source_platforms": ["xhs"],
  "source_post_ids": [13, 11, 12, 14],
  "updatedAt": "2026-06-06 18:38"
}
```

### 9.3 事件详情额外字段

详情接口额外包含：

```json
{
  "representative_posts": [
    {
      "rank": 1,
      "role": "source",
      "processed_post_id": 13,
      "raw_post_id": 13,
      "platform": "xhs",
      "title": "帖子标题",
      "content": "帖子内容",
      "author": "作者",
      "publish_time": "2026-06-06 18:38",
      "url": "原文链接",
      "raw_url": "原始链接",
      "like_count": 0,
      "collect_count": 0,
      "comment_count": 0,
      "share_count": 0
    }
  ],
  "date_range": {},
  "source_keywords": [],
  "top_tags": [],
  "concerns": [],
  "risk_reasons": []
}
```

### 9.4 前端接入步骤

第一步：改造 `frontend/src/api/events.js`。

建议提供：

```js
import http from './http'

export function fetchPublishedEvents(params = {}) {
  return http.get('/events', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}

export function fetchPublicEventDetail(eventId) {
  return http.get(`/events/${eventId}`)
}
```

第二步：事件列表页跳转详情时使用 `raw_id`。

```js
function openDetail(event) {
  router.push(`/events/${event.raw_id}`)
}
```

第三步：事件详情页改为调用详情接口。

不要再用：

```js
const all = await fetchPublishedEvents()
event.value = all.find(e => e.id === eventId.value)
```

应改为：

```js
event.value = await fetchPublicEventDetail(route.params.id)
```

第四步：反馈弹窗接后端。

新增 `frontend/src/api/feedback.js`：

```js
import http from './http'

export function submitFeedback(payload) {
  return http.post('/feedback', {
    feedback_type: payload.feedback_type || 'suggestion',
    content: payload.content,
    contact: payload.contact || '',
    user_id: payload.user_id || 'anonymous',
    target_type: payload.target_type || 'public_event',
    target_id: String(payload.target_id || ''),
  })
}
```

反馈弹窗提交：

```js
await submitFeedback({
  feedback_type: 'content_issue',
  content: form.content,
  contact: form.contact,
  user_id: currentUser?.id || 'anonymous',
  target_type: 'public_event',
  target_id: event.raw_id,
})
```

第五步：验收。

```text
打开 /events
-> Network 看到 GET /api/events
-> 点击某个事件
-> Network 看到 GET /api/events/{raw_id}
-> 提交反馈
-> Network 看到 POST /api/feedback
-> 返回 status=pending
```

## 10. FE-06 后台概览 `/admin` 接入指南

### 10.1 后端接口

```http
GET /api/admin/overview
```

权限：

```text
管理员 token
```

响应 `data`：

```json
{
  "raw_posts_count": 182,
  "processed_posts_count": 100,
  "users_count": 2,
  "events": {
    "draft": 3,
    "published": 6,
    "rejected": 0,
    "archived": 0
  },
  "crawl_tasks": {
    "success": 1
  },
  "feedback": {
    "pending": 1,
    "resolved": 3
  },
  "recent_crawl_task": {},
  "pending_feedback_count": 1,
  "recent_system_errors_count": 0,
  "draft_events_count": 3
}
```

### 10.2 前端接入步骤

第一步：新增 `frontend/src/api/admin.js`。

```js
import http from './http'

export function fetchAdminOverview() {
  return http.get('/admin/overview')
}
```

第二步：`AdminOverviewView.vue` 页面加载时调用。

```js
const overview = ref(null)
const loading = ref(false)
const error = ref('')

async function loadOverview() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await fetchAdminOverview()
  } catch (err) {
    error.value = err.message || '后台概览加载失败'
  } finally {
    loading.value = false
  }
}
```

第三步：KPI 显示建议。

至少显示：

```text
raw_posts_count
processed_posts_count
events.draft
events.published
pending_feedback_count
recent_system_errors_count
recent_crawl_task.status
```

第四步：KPI 跳转。

```text
待审核事件 -> /admin/events?status=draft
已发布事件 -> /admin/events?status=published
原始数据 -> /admin/raw-posts
待处理反馈 -> /admin/ops?tab=feedback&status=pending
系统异常 -> /admin/ops?tab=system-logs&level=error
```

## 11. FE-07 事件审核 `/admin/events` 接入指南

### 11.1 后端接口

事件列表：

```http
GET /api/admin/events?status=all&page=1&page_size=20
```

查询参数：

```text
status=all|draft|published|rejected|archived
keyword
risk_level
page
page_size
```

事件详情：

```http
GET /api/admin/events/{event_id}
```

审核状态修改：

```http
PATCH /api/admin/events/{event_id}/status
```

请求体：

```json
{
  "status": "published",
  "review_comment": "审核通过"
}
```

合法状态：

```text
draft
published
rejected
archived
```

审核日志：

```http
GET /api/admin/events/{event_id}/review-logs
```

### 11.2 前端接入步骤

第一步：新增 `frontend/src/api/adminEvents.js`。

```js
import http from './http'

export function fetchAdminEvents(params = {}) {
  return http.get('/admin/events', {
    params: {
      status: params.status || 'all',
      keyword: params.keyword || '',
      risk_level: params.risk_level || '',
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}

export function fetchAdminEventDetail(eventId) {
  return http.get(`/admin/events/${eventId}`)
}

export function updateAdminEventStatus(eventId, status, reviewComment = '') {
  return http.patch(`/admin/events/${eventId}/status`, {
    status,
    review_comment: reviewComment,
  })
}

export function fetchEventReviewLogs(eventId, params = {}) {
  return http.get(`/admin/events/${eventId}/review-logs`, {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
    },
  })
}
```

第二步：列表页加载所有事件。

默认：

```text
status=all
page=1
page_size=20
```

第三步：筛选项。

页面至少提供：

```text
状态：all/draft/published/rejected/archived
风险：high/medium/low
关键词：title/summary/topic/source_keywords_json
```

第四步：审核操作。

按钮建议：

| 按钮 | PATCH status |
|---|---|
| 发布 | `published` |
| 驳回 | `rejected` |
| 归档 | `archived` |
| 退回待审核 | `draft` |

第五步：操作后刷新。

成功后：

```text
刷新当前列表
刷新详情
显示操作成功
```

第六步：公开列表验证。

发布某个事件后，普通事件列表接口应能看到：

```http
GET /api/events
```

驳回或归档后，公开列表不应出现该事件。

## 12. FE-08 数据管理 `/admin/raw-posts` 接入指南

### 12.1 后端接口

```http
GET /api/admin/raw-posts
```

查询参数：

```text
page
page_size
platform
keyword
start_date
end_date
```

响应项字段：

```json
{
  "id": 1,
  "platform": "xhs",
  "external_id": "note_001",
  "source_table": "xhs_note",
  "source_raw_id": "note_001",
  "source_keyword": "中山大学",
  "title": "帖子标题",
  "content": "帖子内容",
  "author": "作者",
  "publish_time": "2026-06-07 10:00:00",
  "url": "原文链接",
  "raw_url": "原始链接",
  "like_count": 0,
  "collect_count": 0,
  "comment_count": 0,
  "share_count": 0,
  "status": "normal",
  "created_at": "2026-06-07 10:00:00",
  "updated_at": "2026-06-07 10:00:00"
}
```

### 12.2 当前后端缺口

FE-08 原计划希望同时查看：

```text
raw_posts
processed_posts
清洗状态
关联事件
```

当前后端已经提供 `raw_posts` 管理接口，但还没有单独提供：

```text
GET /api/admin/processed-posts
GET /api/admin/raw-posts/{id}/links
```

因此前端第二周可以先完成：

```text
raw_posts 真实列表
平台/关键词/时间筛选
原文链接跳转
基础统计
```

如果必须显示 processed_posts 和关联事件，需要后端补接口。

### 12.3 前端接入步骤

第一步：在 `frontend/src/api/admin.js` 或 `adminRawPosts.js` 增加：

```js
export function fetchAdminRawPosts(params = {}) {
  return http.get('/admin/raw-posts', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      platform: params.platform || '',
      keyword: params.keyword || '',
      start_date: params.start_date || '',
      end_date: params.end_date || '',
    },
  })
}
```

第二步：表格列建议。

```text
ID
平台 platform
关键词 source_keyword
标题 title
作者 author
发布时间 publish_time
互动量 like/comment/share
状态 status
原文 url/raw_url
```

第三步：筛选项建议。

```text
platform: xhs/weibo/tieba
keyword: 输入框
start_date/end_date: 日期选择器
```

第四步：页面状态。

```text
loading -> 表格骨架或加载中
empty -> 暂无采集数据
error -> 原始数据加载失败
success -> 表格展示
```

第五步：验收。

```text
管理员登录
-> 打开 /admin/raw-posts
-> Network 看到 GET /api/admin/raw-posts
-> 表格能看到真实 raw_posts 数据
-> 按 platform=xhs 筛选
-> 按关键词筛选
```

## 13. FE-09 运维反馈 `/admin/ops` 接入指南

### 13.1 后端接口

用户反馈：

```http
GET /api/admin/feedback?page=1&page_size=20&status=pending
PATCH /api/admin/feedback/{feedback_id}/status
```

爬虫与同步任务：

```http
GET /api/admin/crawl-tasks?page=1&page_size=20&status=success&platform=xhs&task_type=sync
```

系统日志：

```http
GET /api/admin/system-logs?page=1&page_size=20&level=error&module=agent
```

管理员操作日志：

```http
GET /api/admin/operation-logs?page=1&page_size=20&action=update_event_status&target_type=public_event
```

事件审核日志：

```http
GET /api/admin/events/{event_id}/review-logs
```

### 13.2 当前后端缺口

FE-09 原计划希望查看 Agent 运行记录。

当前后端会写入 `agent_run_logs`，但目前没有单独提供：

```text
GET /api/admin/agent-run-logs
```

前端可以临时通过以下方式展示 Agent 相关运维信息：

| 信息 | 临时来源 |
|---|---|
| Agent 成功触发记录 | `/api/admin/operation-logs?action=run_public_opinion_analysis` |
| Agent 失败错误 | `/api/admin/system-logs?module=agent` |
| Agent run_log_id | `/api/agent/public/analyze` 响应中的 `run_log_id` |

如果前端要做完整 Agent 运行记录页，需要后端补充 `agent_run_logs` 查询接口。

### 13.3 前端接入步骤

第一步：新增 `frontend/src/api/adminOps.js`。

```js
import http from './http'

export function fetchAdminFeedback(params = {}) {
  return http.get('/admin/feedback', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      status: params.status || '',
    },
  })
}

export function updateFeedbackStatus(feedbackId, status, handleNote = '') {
  return http.patch(`/admin/feedback/${feedbackId}/status`, {
    status,
    handle_note: handleNote,
  })
}

export function fetchCrawlTasks(params = {}) {
  return http.get('/admin/crawl-tasks', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      status: params.status || '',
      platform: params.platform || '',
      task_type: params.task_type || '',
    },
  })
}

export function fetchSystemLogs(params = {}) {
  return http.get('/admin/system-logs', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      level: params.level || '',
      module: params.module || '',
    },
  })
}

export function fetchOperationLogs(params = {}) {
  return http.get('/admin/operation-logs', {
    params: {
      page: params.page || 1,
      page_size: params.page_size || 20,
      action: params.action || '',
      target_type: params.target_type || '',
    },
  })
}
```

第二步：`/admin/ops` 页面做 tabs。

建议 tabs：

```text
用户反馈
爬虫任务
Agent记录
系统日志
管理员操作
```

第三步：用户反馈 tab。

字段：

```text
id
target_type
target_id
feedback_type
content
contact
status
created_at
handled_by
handle_note
```

操作：

```text
标记处理中 -> handling
标记已解决 -> resolved
忽略 -> ignored
```

第四步：爬虫任务 tab。

字段：

```text
task_name
task_type
platform
keyword
status
success_count
failed_count
error_message
started_at
finished_at
```

第五步：Agent 记录 tab。

当前临时做法：

```text
调用 /api/admin/operation-logs?action=run_public_opinion_analysis
调用 /api/admin/system-logs?module=agent
```

页面文案应注明：

```text
当前展示 Agent 操作记录和失败日志；完整 agent_run_logs 列表接口待后端补充。
```

第六步：系统日志 tab。

字段：

```text
level
module
message
detail
trace_id
created_at
```

第七步：管理员操作日志 tab。

字段：

```text
admin_user_id
action
target_type
target_id
detail
ip_address
created_at
```

## 14. FE-10 前后端联调验收流程

### 14.1 启动后端

在主项目根目录：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\run.bat
```

后端成功标志：

```text
Uvicorn running on http://127.0.0.1:9000
```

只读检查：

```powershell
Invoke-RestMethod http://127.0.0.1:9000/health
Invoke-RestMethod http://127.0.0.1:9000/api/ping
```

### 14.2 启动前端

新开一个终端：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend"
npm run dev
```

成功标志：

```text
Local: http://localhost:5173
```

### 14.3 构建检查

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend"
npm run build
```

成功标志：

```text
✓ built
```

### 14.4 完整人工验收链路

第一步：管理员登录。

```text
打开 http://localhost:5173/login
输入后端负责人提供的管理员账号
Network 看到 POST /api/auth/login
登录成功后进入 /admin
```

第二步：后台概览。

```text
打开 /admin
Network 看到 GET /api/admin/overview
页面显示 raw_posts、processed_posts、待审核事件、反馈、系统异常等 KPI
```

第三步：数据管理。

```text
打开 /admin/raw-posts
Network 看到 GET /api/admin/raw-posts
能看到真实采集数据
```

第四步：舆情分析。

```text
打开 /opinion
输入关键词，例如 中山大学
点击开始分析
Network 看到 POST /api/agent/public/analyze
页面显示 input_count、event_count、events
```

第五步：事件审核。

```text
打开 /admin/events
Network 看到 GET /api/admin/events
选择 draft 事件
点击发布
Network 看到 PATCH /api/admin/events/{raw_id}/status
```

第六步：公开事件查看。

```text
打开 /events
Network 看到 GET /api/events
刚发布的事件应该出现在 published 列表
点击事件详情
Network 看到 GET /api/events/{raw_id}
```

第七步：普通用户反馈。

```text
在事件详情页点击反馈
提交反馈
Network 看到 POST /api/feedback
返回 status=pending
```

第八步：管理员处理反馈。

```text
打开 /admin/ops
进入用户反馈 tab
Network 看到 GET /api/admin/feedback
处理反馈
Network 看到 PATCH /api/admin/feedback/{feedback_id}/status
```

第九步：查看日志。

```text
/admin/ops 系统日志 tab -> GET /api/admin/system-logs
/admin/ops 管理员操作 tab -> GET /api/admin/operation-logs
/admin/events 事件详情 -> GET /api/admin/events/{raw_id}/review-logs
```

## 15. 前端负责人应优先完成的文件清单

### 15.1 必须新增或修改

```text
frontend/src/api/auth.js
frontend/src/api/agent.js
frontend/src/api/feedback.js
frontend/src/api/admin.js
frontend/src/api/adminEvents.js
frontend/src/api/adminOps.js
frontend/src/router/index.js
frontend/src/auth/session.js
frontend/src/views/LoginView.vue
frontend/src/views/OpinionView.vue
frontend/src/views/EventListView.vue
frontend/src/views/EventDetailView.vue
frontend/src/components/EventFeedbackDialog.vue
```

### 15.2 必须新增页面

```text
frontend/src/views/admin/AdminOverviewView.vue
frontend/src/views/admin/AdminEventsView.vue
frontend/src/views/admin/AdminRawPostsView.vue
frontend/src/views/admin/AdminOpsView.vue
```

### 15.3 必须减少或禁用 mock 的位置

```text
frontend/src/auth/session.js
frontend/src/api/events.js
frontend/src/views/OpinionView.vue
frontend/src/components/EventFeedbackDialog.vue
```

验收阶段不能让后端接口失败后悄悄显示 mock 数据。

## 16. 需要前后端再次确认的问题

### 16.1 `/events` 是否允许游客访问

当前工作包中写了游客入口跳转 `/events`，但当前前端路由守卫会拦截未登录访问。

需要确认：

```text
公开事件是否允许游客查看？
```

如果允许，前端应把 `/events` 和 `/events/:id` 设为 guest 页面。

### 16.2 `/opinion` 是否只允许管理员触发分析

当前后端：

```text
POST /api/agent/public/analyze -> 管理员专用
```

需要确认：

```text
普通用户是否能触发 Agent 分析？
```

如果普通用户不能触发，前端 `/opinion` 对普通用户应只展示已发布事件和只读分析，不显示“开始分析”按钮。

### 16.3 是否需要 processed_posts 单独管理页面

当前后端：

```text
GET /api/admin/raw-posts 已有
GET /api/admin/processed-posts 暂无
```

如果 FE-08 必须展示清洗结果，需要后端补充 processed_posts 接口。

### 16.4 是否需要 agent_run_logs 单独页面

当前后端：

```text
agent_run_logs 会写入
但 GET /api/admin/agent-run-logs 暂无
```

如果 FE-09 必须展示完整 Agent 运行记录，需要后端补充 agent_run_logs 查询接口。

## 17. 最小可验收目标

前端负责人完成接入后，最小验收不要求页面最终美化，但必须能跑通：

```text
真实管理员登录
-> /admin 后台概览
-> /admin/raw-posts 查看真实采集数据
-> /opinion 触发真实 Agent 分析
-> /admin/events 审核发布事件
-> /events 查看已发布事件
-> /events/{raw_id} 查看代表内容和原文链接
-> POST /api/feedback 提交反馈
-> /admin/ops 查看并处理反馈、任务、日志
```

验收时以浏览器 Network 为准。只要关键请求没有走 `/api/...`，或者页面仍然依赖静默 mock，就不能算完成 week2 前端联调。
