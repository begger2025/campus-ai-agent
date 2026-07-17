# Week2 前端工作包进度审查报告

审查日期：2026-06-07

审查对象：

- 前端工作包文档：`C:\Users\31879\Downloads\week2 前端工作包.md`
- 主项目：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`
- 前端目录：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend`

## 1. 总体结论

当前前端并没有达到 week2 前端工作包的完整验收标准。

比较准确的判断是：**公开事件浏览与舆情工作台的页面框架已经有基础，并且部分页面能读取后端真实 `/api/events` 数据；但登录、后台管理、Agent 触发、事件审核、反馈提交、运维反馈这些 week2 主链路关键环节仍未真正接入后端。**

按工作包完成度粗略估算：

- FE-01 至 FE-05：部分完成。
- FE-06 至 FE-09：基本未完成或只有导航入口。
- FE-10：后端验收文档较完整，但前端自己的完整联调验收闭环不足。

当前前端大约处于 **35% - 40%** 的 week2 完成度。它可以演示“事件列表/舆情页读取已发布事件”，但还不能演示工作包要求的完整链路：

```text
登录 -> 舆情分析 -> 事件审核发布 -> 普通用户查看事件 -> 用户反馈 -> 管理员处理反馈/异常
```

## 2. 已验证的正向结果

### 2.1 前端可以正常构建

在前端目录执行：

```powershell
npm run build
```

结果：

```text
✓ 1680 modules transformed.
✓ built in 7.15s
```

说明当前前端代码没有阻塞生产构建的语法错误。

需要注意：

- 构建产物 JS chunk 约 `1,146.75 kB`，Vite 提示超过 500 kB，后续可以考虑动态导入或拆包。
- Rollup 对 `@vueuse/core` 的 PURE 注释有警告，但不影响本次构建通过。

### 2.2 Vite 已正确代理 `/api`

文件：

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend\vite.config.js`

当前配置：

```js
server: {
  port: 5173,
  proxy: {
    '/api': apiProxy,
  },
}
```

这符合工作包 FE-02 对“所有业务请求统一走 `/api/...`”的方向。

### 2.3 后端真实接口当前可用

已验证：

```powershell
Invoke-RestMethod http://127.0.0.1:9000/health
Invoke-RestMethod http://127.0.0.1:9000/api/ping
Invoke-RestMethod "http://127.0.0.1:9000/api/events?status=published&page=1&page_size=100"
```

结果：

- `/health` 返回 `status=ok`
- `/api/ping` 返回 `code=0`，数据库为 `campus_ai_agent`
- `/api/events` 返回 `code=0`，当前有 6 条 `published` 事件

说明前端要接入的后端基础接口是存在的，不是“后端没有接口导致前端无法继续”。

### 2.4 `/events` 和 `/opinion` 能显示真实事件数据

通过 headless Playwright 实际打开页面验证：

- `/events` 能展示 6 条已发布事件。
- `/opinion` 能展示同一批已发布事件。
- 页面顶部能显示“真实接口”状态。

截图保存在：

```text
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\user-events.png
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\opinion.png
```

## 3. 关键问题汇总

### 3.1 后台管理页面没有实现

工作包要求的后台路由包括：

```text
/admin
/admin/events
/admin/raw-posts
/admin/ops
```

当前 `src/config/nav.js` 里已经配置了这些菜单项，但 `src/router/index.js` 没有注册这些路由，也没有对应的后台页面组件。

实际打开结果：

| 路由 | 页面结果 |
|---|---|
| `/admin` | 404 页面未找到 |
| `/admin/events` | 404 页面未找到 |
| `/admin/raw-posts` | 404 页面未找到 |
| `/admin/ops` | 404 页面未找到 |

这意味着 FE-06、FE-07、FE-08、FE-09 目前不能通过验收。

截图保存在：

```text
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\admin.png
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\admin-events.png
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\admin-raw-posts.png
C:\Users\31879\AppData\Local\Temp\campus_ai_agent_frontend_audit\admin-ops.png
```

### 3.2 登录仍然是前端 mock，没有接后端认证

文件：

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend\src\auth\session.js`

当前登录逻辑是：

```js
mockLogin(...)
token: `mock-${normalizedRole}-token`
```

它没有调用：

```http
POST /api/auth/login
GET /api/auth/me
```

后端实际上已经有这些接口：

```text
backend/routers/auth.py
POST /api/auth/login
GET  /api/auth/me
```

因此 FE-03 目前只能算“登录 UI 和本地角色模拟存在”，不能算“真实登录联调完成”。

### 3.3 游客访问 `/events` 被路由守卫拦到登录页

工作包 FE-03 写了“游客入口跳转 `/events`”，FE-05 也要求普通用户能查看公开事件。

当前实际验证：

```text
游客访问 http://localhost:5173/events
最终跳转到 http://localhost:5173/login?redirect=/events
```

原因是 `src/router/index.js` 的路由守卫把所有非 `guest` meta 的页面都视为需要登录，而 `/events` 当前没有设置 `meta.guest = true`。

这会影响公开事件浏览的验收口径。需要项目负责人确认：

- 如果 `/events` 要允许游客访问，应把 `/events` 和 `/events/:id` 标为 guest 可访问。
- 如果必须登录才能看公开事件，则应修改工作包和登录页文案，避免“游客浏览公开事件”与实现矛盾。

### 3.4 `/opinion` 还没有真正触发 Agent 分析接口

文件：

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend\src\views\OpinionView.vue`

当前 `runAnalysis()` 是前端模拟：

```js
// mock: 模拟 Agent 分析延迟
await new Promise(r => setTimeout(r, 1200))
```

它没有调用：

```http
POST /api/agent/public/analyze
```

后端接口已经存在：

```text
backend/routers/agent_public.py
POST /api/agent/public/analyze
```

因此 FE-04 目前只是“能展示事件列表和模拟 Agent 文案”，不是“输入关键词后触发真实 Agent 分析”。

### 3.5 事件详情页没有调用详情接口，存在 ID 不一致问题

工作包要求 `/events/:event_id` 展示事件详情、代表内容、来源链接。

当前前端详情页逻辑是：

```js
const all = await fetchPublishedEvents()
event.value = all.find(e => e.id === eventId.value) || null
```

也就是说，它不是调用：

```http
GET /api/events/{event_id}
```

而是重新拉列表后在前端查找。

实际验证：

- `/events/EVT-9` 可以打开，因为列表接口里前端展示 ID 是 `EVT-9`。
- `/events/9` 显示“事件不存在”，但后端文档说明 `GET /api/events/{event_id}` 使用数据库整数 ID。

这说明前端与后端详情接口的 ID 口径尚未统一。

建议：

- 前端详情页改为调用 `GET /api/events/{raw_id}` 或后端补充兼容 `EVT-9`。
- 列表页跳转时明确使用后端可识别的 `raw_id`，例如 `/events/9`。
- 详情页补齐 `representative_posts`、原文 URL、风险理由等字段展示。

### 3.6 用户反馈仍是模拟提交

文件：

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend\src\components\EventFeedbackDialog.vue`

当前逻辑：

```js
// 模拟提交（待后端实现 POST /feedbacks）
await new Promise(resolve => setTimeout(resolve, 600))
```

问题有两个：

- 没有调用真实接口。
- 注释里写的是 `POST /feedbacks`，但后端实际接口是 `POST /api/feedback`。

后端已经具备：

```text
backend/routers/feedback.py
POST /api/feedback
```

因此 FE-05 的“用户反馈能提交到后端”目前不满足。

### 3.7 `fetchPublishedEvents()` 静默 fallback 到 mock，可能掩盖接口问题

文件：

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend\src\api\events.js`

当前逻辑：

```js
catch {
  console.warn('[api/events] backend unavailable, using mock data')
  return [...mockPublishedEvents]
}
```

这在开发早期有用，但验收阶段会带来风险：

- 后端接口挂了，页面仍然显示 mock 事件。
- 验收人员可能误以为接口正常。
- 页面上部分位置硬编码 `DataSourceBadge source="mock"`，和顶部“真实接口”提示互相矛盾。

建议验收阶段不要静默 fallback。可以改成：

- 开发模式允许 fallback，但页面必须明确标注“后端失败，当前为 mock”。
- 验收模式直接显示 error，不自动混入 mock。

## 4. FE-01 至 FE-10 逐项进度

| 工作包 | 当前状态 | 结论 |
|---|---|---|
| FE-01 路由、导航、权限骨架 | 左侧导航已有公共舆情和后台菜单；角色菜单能按 mock role 区分；但后台路由没有注册，游客 `/events` 被拦截 | 部分完成 |
| FE-02 API 请求层与数据状态 | `axios` baseURL 为 `/api`，能解包 `code/data/message`；`/api/events` 可用；但 mock fallback 会掩盖错误，很多页面没有真实 error/empty 处理 | 部分完成 |
| FE-03 登录页 | 登录页 UI 存在；普通用户/管理员只是本地 mock；未接 `POST /api/auth/login` | 部分完成，未真实联调 |
| FE-04 舆情工作台 `/opinion` | 页面存在，能显示真实事件列表；“开始分析”和 Agent 问答是 mock，未接 `POST /api/agent/public/analyze` | 部分完成 |
| FE-05 公开事件列表与详情 | `/events` 能显示 published 事件；详情页可显示 `EVT-*`；但未调用详情接口，代表内容/原文 URL 不完整，反馈未入库 | 部分完成 |
| FE-06 后台概览 `/admin` | 导航存在，页面 404 | 未完成 |
| FE-07 事件审核 `/admin/events` | 导航存在，页面 404；未接审核接口 | 未完成 |
| FE-08 数据管理 `/admin/raw-posts` | 导航存在，页面 404；未接 raw/processed 管理接口 | 未完成 |
| FE-09 运维反馈 `/admin/ops` | 导航存在，页面 404；未接反馈、爬虫任务、Agent 日志、系统日志 | 未完成 |
| FE-10 联调与验收文档 | 后端 smoke test 文档较完整；前端没有形成能从登录跑到审核、反馈、后台处理的完整验收闭环 | 部分完成 |

## 5. 后端接口与前端接入差距

后端当前已经提供了前端工作包所需的大部分接口：

```text
POST /api/auth/login
GET  /api/auth/me
GET  /api/events
GET  /api/events/{event_id}
POST /api/feedback
POST /api/agent/public/analyze
GET  /api/admin/overview
GET  /api/admin/raw-posts
GET  /api/admin/events
GET  /api/admin/events/{event_id}
PATCH /api/admin/events/{event_id}/status
GET  /api/admin/crawl-tasks
GET  /api/admin/feedback
PATCH /api/admin/feedback/{feedback_id}/status
GET  /api/admin/system-logs
GET  /api/admin/operation-logs
GET  /api/admin/events/{event_id}/review-logs
```

所以当前前端不能完整验收的主要原因不是“后端没有接口”，而是：

1. 前端认证仍使用 mock。
2. 后台页面没有实现。
3. Agent 分析按钮没有调用后端。
4. 反馈弹窗没有调用后端。
5. 详情页没有接后端详情接口。
6. mock fallback 和数据源标识会混淆验收判断。

## 6. 建议的修复优先级

### 优先级 1：先补真实登录

新增：

```text
src/api/auth.js
```

接入：

```http
POST /api/auth/login
GET /api/auth/me
```

替换 `mockLogin()`，把真实 `access_token` 存入 session。否则所有 `/api/admin/*` 都无法真实联调。

### 优先级 2：补后台四个路由和页面

至少新增：

```text
src/views/admin/AdminOverviewView.vue
src/views/admin/AdminEventsView.vue
src/views/admin/AdminRawPostsView.vue
src/views/admin/AdminOpsView.vue
```

并在 `src/router/index.js` 注册：

```text
/admin
/admin/events
/admin/raw-posts
/admin/ops
```

这些路由应设置：

```js
meta: { roles: ['admin'] }
```

### 优先级 3：接入后台 API

建议新增：

```text
src/api/admin.js
src/api/adminEvents.js
src/api/feedback.js
src/api/agent.js
```

对应接入：

- `/api/admin/overview`
- `/api/admin/raw-posts`
- `/api/admin/events`
- `/api/admin/events/{event_id}/status`
- `/api/admin/feedback`
- `/api/admin/system-logs`
- `/api/admin/operation-logs`
- `/api/agent/public/analyze`
- `/api/feedback`

### 优先级 4：修正事件详情 ID 口径

当前前端使用 `EVT-9`，后端详情接口使用整数 `9`。

建议二选一：

- 前端路由使用 `raw_id`，例如 `/events/9`。
- 后端详情接口兼容 `EVT-9`。

为了减少后端改动，建议前端列表跳转使用 `event.raw_id`。

### 优先级 5：取消验收阶段静默 mock fallback

验收时应做到：

- 后端失败就显示错误。
- mock 页面必须明确标注。
- 不允许真实接口失败后自动显示 mock 数据。

## 7. 当前可验收与不可验收清单

### 当前可以验收

- 前端能构建。
- Vite `/api` proxy 存在。
- `/events` 登录后能展示真实 published 事件列表。
- `/opinion` 登录后能展示真实 published 事件列表。
- 普通用户和管理员菜单可以通过 mock role 做区分。

### 当前不能通过 week2 完整验收

- 管理员真实登录。
- 管理员进入 `/admin` 后台概览。
- 管理员进入 `/admin/raw-posts` 查看采集数据。
- `/opinion` 输入关键词后真实触发 Agent 分析。
- 管理员进入 `/admin/events` 审核、发布、驳回、归档事件。
- 普通用户在事件详情页提交反馈到后端。
- 管理员进入 `/admin/ops` 查看反馈、异常、Agent 运行记录。
- 从登录一路跑完整个公共舆情闭环。

## 8. 最终判断

前端目前不是“完全没做”，而是完成了第一批公共舆情展示型页面和基础 API 封装；但 week2 最关键的“前后端真实联调闭环”还没有完成。

下一步前端负责人应该停止继续堆展示页面，优先把以下闭环打通：

```text
真实登录
-> 后台路由和页面
-> Agent 分析接口
-> 事件审核接口
-> 公开事件详情接口
-> 用户反馈接口
-> 后台反馈/日志处理接口
```

只有这条链路打通后，week2 前端工作包才接近可验收状态。
