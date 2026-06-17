# frontend — Campus AI Agent 前端

基于 **Vue 3 + Element Plus + Vite** 构建的校园舆情智能助手前端界面。

## 技术栈

| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 核心框架 |
| Vue Router 4 | 前端路由（含导航守卫 + 角色权限） |
| Element Plus | UI 组件库（中文） |
| Axios | HTTP 请求（统一拦截器 + JWT 注入） |
| Vite 5 | 构建工具 / 开发服务器 |

## 目录结构

```text
frontend/
├── index.html
├── package.json
├── vite.config.js          # Vite 配置（含后端代理）
└── src/
    ├── main.js             # 应用入口，注册 Element Plus
    ├── App.vue             # 根组件
    ├── router/
    │   └── index.js        # 路由配置（13 条路由 + beforeEach 守卫）
    ├── layouts/
    │   └── MainLayout.vue  # 主布局（侧边栏 + 顶栏 + 路由出口）
    ├── auth/
    │   └── session.js      # JWT Token 会话管理（登录/登出/角色/权限）
    ├── config/
    │   └── nav.js          # 侧边栏导航配置（按角色分组）
    ├── views/
    │   ├── HomeView.vue            # 首页仪表盘
    │   ├── LoginView.vue           # 统一登录页
    │   ├── SentimentView.vue       # 舆情分析页
    │   ├── EventListView.vue       # 公开事件列表
    │   ├── EventDetailView.vue     # 事件详情页
    │   ├── OpinionView.vue         # 舆情工作台（Agent 辅助分析）
    │   ├── PersonalView.vue        # 个人事项（课表/作业/日程）
    │   ├── ForbiddenView.vue       # 403 无权限
    │   ├── NotFoundView.vue        # 404 页面
    │   └── admin/
    │       ├── AdminOverviewView.vue   # 后台概览（KPI + 事件分布）
    │       ├── AdminEventsView.vue     # 事件审核（发布/驳回/归档）
    │       ├── AdminRawPostsView.vue   # 原始数据管理
    │       └── AdminOpsView.vue        # 运营管理（反馈/爬虫/日志）
    ├── components/
    │   ├── StatCard.vue              # 统计卡片通用组件
    │   ├── DataSourceBadge.vue       # 数据来源标签
    │   ├── EventFeedbackDialog.vue   # 用户反馈对话框
    │   └── PageStub.vue              # 占位页面
    ├── api/
    │   ├── http.js         # Axios 实例（baseURL / JWT 拦截 / 错误处理）
    │   ├── auth.js         # POST /api/auth/login  ·  GET /api/auth/me
    │   ├── agent.js        # POST /api/agent/public/analyze
    │   ├── events.js       # GET  /api/events  ·  GET /api/events/:id
    │   ├── feedback.js     # POST /api/feedback
    │   ├── posts.js        # GET  /api/health  ·  GET /api/posts
    │   ├── admin.js        # GET  /api/admin/overview  ·  /api/admin/raw-posts
    │   ├── adminEvents.js  # 事件审核全套（列表/详情/修改状态/审核日志）
    │   └── adminOps.js     # 反馈处理/爬虫任务/系统日志/操作日志
    ├── mock/
    │   ├── data.js         # 旧 mock 数据（不再主动使用，保留作参考）
    │   └── events.js       # 旧 mock 事件（同上）
    └── assets/
        └── style.css       # 全局样式 / CSS 变量
```

## 路由总览

| 路径 | 页面 | 权限 |
|------|------|------|
| `/login` | 登录页 | 游客可访问 |
| `/` | 首页仪表盘 | 需登录 |
| `/sentiment` | 舆情分析 | 需登录 |
| `/events` | 公开事件列表 | 游客可访问 |
| `/events/:id` | 事件详情 | 游客可访问 |
| `/opinion` | 舆情工作台 | 用户 + 管理员 |
| `/personal` | 个人事项 | 用户 + 管理员 |
| `/admin` | 后台概览 | 仅管理员 |
| `/admin/events` | 事件审核 | 仅管理员 |
| `/admin/raw-posts` | 原始数据管理 | 仅管理员 |
| `/admin/ops` | 运营管理 | 仅管理员 |
| `/forbidden` | 403 | 不限 |
| `/:pathMatch(.*)*` | 404 | 不限 |

## 认证与权限

### 登录流程

1. 用户在统一登录页输入账号密码 → `POST /api/auth/login`
2. 后端返回 `{ access_token, user: { id, username, role, ... } }`
3. 前端将 token + user 存入 localStorage，axios 拦截器自动注入 `Authorization: Bearer <token>`
4. 角色由后端返回的 `user.role` 决定（`admin` / `user`），前端不做预判

### 路由守卫

- `meta: { guest: true }` — 游客可直接访问
- `meta: { roles: ['admin'] }` — 仅管理员可访问
- 无 `roles` 标记 — 任何已登录用户均可访问
- 未登录 → 跳转 `/login?redirect=原路径`

### 会话管理 (`auth/session.js`)

| 函数 | 说明 |
|------|------|
| `isAuthenticated()` | 是否已登录 |
| `getCurrentUser()` | 当前用户信息 |
| `getCurrentRole()` | 当前角色（admin / user） |
| `login()` | 调用登录 API |
| `logout()` | 清除 localStorage 会话 |
| `saveSessionFromLoginResponse(data)` | 从登录响应写入 session |

## 接口约定（与后端统一）

> 后端统一响应格式：`{ code: 0, message: "ok", data: { ... } }`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/auth/login` | 登录（含 JWT token） | 公开 |
| GET | `/api/auth/me` | 获取当前用户 | 已登录 |
| GET | `/api/events` | 公开事件列表（分页） | 公开 |
| GET | `/api/events/:raw_id` | 事件详情 | 公开 |
| POST | `/api/feedback` | 提交用户反馈 | 已登录 |
| POST | `/api/agent/public/analyze` | Agent 舆情分析 | 仅管理员 |
| GET | `/api/admin/overview` | 后台 KPI 概览 | 仅管理员 |
| GET | `/api/admin/raw-posts` | 原始采集数据 | 仅管理员 |
| GET | `/api/admin/events` | 全量事件列表 | 仅管理员 |
| GET | `/api/admin/events/:raw_id` | 事件全量详情 | 仅管理员 |
| PATCH | `/api/admin/events/:raw_id/status` | 修改事件状态 | 仅管理员 |
| GET | `/api/admin/feedback` | 反馈列表 | 仅管理员 |
| GET | `/api/admin/crawl-tasks` | 爬虫任务列表 | 仅管理员 |
| GET | `/api/admin/system-logs` | 系统日志 | 仅管理员 |
| GET | `/api/admin/operation-logs` | 操作日志 | 仅管理员 |

### 关键约定

- 后端返回 `snake_case` 字段（`risk_level`、`source_platforms`），前端列表层通过 `normalizeEvent()` 统一转为 `camelCase`
- 事件 ID：列表返回字符串格式 `id: "EVT-9"`，详情/审核接口使用整数 `raw_id: 9`
- 分页格式：`{ items: [], total, page, page_size }`

## 本地启动

> 确保已安装 Node.js 18+

```bash
# 1. 进入前端目录
cd campus-ai-agent/frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器（默认 http://localhost:5173）
npm run dev
```

前端通过 Vite proxy 将 `/api` 请求代理到后端 FastAPI（默认 `http://localhost:9000`）。

## 构建

```bash
npm run build    # 产物输出到 dist/
npm run preview  # 本地预览构建结果
```

## 测试账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | `admin` | `admin123456` |
| 普通用户 | `user` | `user123456` |
