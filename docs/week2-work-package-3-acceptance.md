# Week2 后端工作包 3 验收记录：修复前后端真实联调问题

检查时间：2026-06-05

## 1. 工作包目标

工作包 3 的核心问题是：第一周前端请求 `/posts?page=1&page_size=10` 时，Vite 开发服务器把它当作前端页面路由处理，返回了 `text/html`，而不是 FastAPI 的 JSON。

本次修复目标：

- 后端真实 API 统一挂到 `/api/*`。
- 前端统一通过 `/api` 前缀访问后端。
- Vite 开发代理只代理 `/api -> http://127.0.0.1:9000`。
- 浏览器 Network 中 `/api/posts`、`/api/events` 返回 `application/json`，不再返回前端 HTML。

## 2. 本次已修改内容

### 后端

修改文件：

- `backend/main.py`
- `backend/routers/api.py`
- `backend/schemas.py`

完成项：

- `app.include_router(api_router, prefix="/api")` 已配置。
- 新增 `/api/{path:path}` JSON 404，位置在 SPA fallback 前，避免未匹配 API 返回 `index.html`。
- `/api/ping` 可用。
- `/api/posts?page=1&page_size=10` 可用，返回统一结构：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "page_size": 10
  }
}
```

- 新增 `/api/events?status=published`，用于前端事件列表真实联调。
- 新增 `/api/admin/overview`，用于后台概览接口约定。
- `/api/ping` 不再暴露完整数据库连接串，只返回数据库名。

### 前端

修改文件：

- `frontend/src/api/posts.js`
- `frontend/src/api/events.js`
- `frontend/src/views/HomeView.vue`
- `frontend/vite.config.js`

完成项：

- `frontend/src/api/http.js` 继续作为统一 axios 实例，`baseURL` 为 `/api`。
- `fetchPosts()` 改为通过统一实例请求 `/posts`，实际 Network 路径为 `/api/posts`。
- `fetchPublishedEvents()` 改为通过统一实例请求 `/events`，实际 Network 路径为 `/api/events`。
- 首页健康检查从裸 `fetch('/health')` 改为 `checkHealth()`，实际 Network 路径为 `/api/ping`。
- Vite 代理已收口为只代理 `/api`，不再代理 `/posts`、`/events`、`/health`、`/ping`。
- 已重新执行前端生产构建，更新 `frontend/dist`。

## 3. 验收结果

### 3.1 后端路由注册检查

命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -c "from backend.main import app; print([r.path for r in app.routes if '/api' in r.path][:10])"
```

结果：

```text
['/api/ping', '/api/posts', '/api/events', '/api/admin/overview', '/api/{path:path}']
```

结论：通过。

### 3.2 前端构建检查

命令：

```powershell
cd frontend
npm.cmd run build
```

结果：

```text
vite v5.4.21 building for production...
1680 modules transformed.
dist/index.html
dist/assets/index-D8CauEMJ.css
dist/assets/index-DvdnCeZo.js
built in 8.10s
```

结论：通过。构建时只有 chunk 体积提醒，不影响本工作包验收。

### 3.3 API JSON 结构检查

由于当前执行环境无法连通共享 MySQL 3306 端口，本次使用临时 SQLite 数据库挂载同一套 `backend.routers.api` 路由进行接口结构验收。

验收结果：

```text
URL: /api/ping
Status: 200
Content-Type: application/json
code: 0
data keys: ['database', 'pong', 'timestamp']

URL: /api/posts?page=1&page_size=5
Status: 200
Content-Type: application/json
code: 0
data keys: ['items', 'page', 'page_size', 'total']

URL: /api/events?status=published&page=1&page_size=5
Status: 200
Content-Type: application/json
code: 0
data keys: ['items', 'page', 'page_size', 'total']

URL: /api/admin/overview
Status: 200
Content-Type: application/json
code: 0
data keys: ['crawl_tasks', 'processed_posts', 'public_events', 'raw_posts', 'users']

URL: /api/not-found-check
Status: 404
Content-Type: application/json
code: 404
```

结论：通过。`/api/*` 不再返回 HTML。

### 3.4 共享 MySQL 连通性说明

当前网络下测试共享数据库：

```powershell
Test-NetConnection rm-wz98ixlbr528d87heqo.mysql.rds.aliyuncs.com -Port 3306
```

结果：

```text
TcpTestSucceeded: False
```

SQLAlchemy 连接报错核心信息：

```text
WinError 10013
Can't connect to MySQL server
```

这属于当前网络到阿里云 RDS 3306 端口不可达或被拦截，不是本工作包的代码问题。换到能连通该 RDS 白名单的网络后，再运行真实联调即可。

## 4. 你本机最终验收步骤

在能连通共享数据库的网络下执行：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
verify_db.bat
```

再启动开发联调：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
dev.bat
```

浏览器打开：

```text
http://localhost:5173
```

打开 F12 -> Network -> Fetch/XHR，刷新页面后重点看：

- `/api/ping`
- `/api/posts?page=1&page_size=10`
- `/api/events?status=published&page=1&page_size=100`

成功标志：

- Status 为 `200`。
- Content-Type 为 `application/json`。
- Response 中有 `code: 0`、`message: "ok"`、`data`。
- 不再看到前端请求裸 `/posts?page=1&page_size=10`。
- 不再看到 `/api/posts` 返回 `<div id="app"></div>` 或 `text/html`。

## 5. 验收结论

工作包 3 的代码修复已完成：

- 后端 API 前缀已统一为 `/api/*`。
- 前端 API 请求已统一走 `/api`。
- Vite 代理已只保留 `/api`。
- `/api/posts`、`/api/events`、`/api/admin/overview` 的 JSON 响应结构已验收通过。

剩余风险只和当前网络访问共享 MySQL 有关。只要切换到能访问 RDS 3306 端口的网络，按第 4 节步骤即可完成真实数据库联调验收。
