# frontend — Campus AI Agent 前端

基于 **Vue 3 (Composition API) + Element Plus + Vite** 的校园舆情分析平台前端，
共 19 个页面，覆盖公共门户、舆情业务与管理后台三块。

## 技术栈

| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 核心框架 |
| Vue Router 4 | 前端路由 + 登录/角色守卫 |
| Element Plus（含 icons-vue） | UI 组件库 |
| Axios | HTTP 请求（相对路径 `/api`，开发经 Vite 代理） |
| GSAP | 首页/登录页动效 |
| Vite 5 | 构建工具 / 开发服务器 |

## 目录结构

```text
frontend/src/
├── main.js / App.vue     # 应用入口
├── router/               # 路由 + 鉴权守卫（登录态、管理员角色）
├── layouts/              # MainLayout：侧边导航 + 顶栏
├── views/                # 19 个页面
│   ├── HomeView / LoginView / NotFoundView / ForbiddenView
│   ├── SentimentView / OpinionView / EventListView / EventDetailView
│   ├── AgentChatView（舆情助手对话，流式）
│   ├── PersonalView / SubmissionView
│   └── Admin*（8 个管理后台页：总览/事件/证据/评论/投稿/关键词/原始帖/运维）
├── api/                  # 9 个接口模块（http.js 统一封装拦截器）
├── components/           # 通用组件
├── utils/                # citations（引用编号解析）等
├── auth/ config/ constants/ directives/
└── assets/
```

## 数据原则

前端**不含任何 mock 数据**：后端不可用时如实报错，不用假数据顶替
（见 `api/events.js` 的 no-fake-fallback 注释）。图表、列表、报告全部来自 `/api` 真实响应。

## 运行

```bash
# 开发（推荐在项目根直接跑 dev.bat：前端 5173 + 后端 9000 一起起）
npm run dev        # 仅前端，Vite 代理 /api → 127.0.0.1:9000

# 生产构建（产物 dist/，由后端静态挂载或 Nginx 服务）
npm run build
```

项目根的 `check.ps1` 全量回归包含本目录的生产构建（构建通过 = 模板/脚本静态检查通过）。
