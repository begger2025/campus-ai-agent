# frontend — Campus AI Agent 前端

基于 **Vue 3 + Element Plus + Vite** 构建的校园智能助手前端界面。

## 技术栈

| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 核心框架 |
| Vue Router 4 | 前端路由 |
| Element Plus | UI 组件库（中文） |
| Axios | HTTP 请求 |
| Vite 5 | 构建工具 / 开发服务器 |

## 目录结构

```text
frontend/
├── index.html            # 入口 HTML
├── package.json          # 依赖配置
├── vite.config.js        # Vite 配置（含后端代理）
└── src/
    ├── main.js           # 应用入口，注册 Element Plus
    ├── App.vue           # 根组件（侧边导航 + 布局）
    ├── router/
    │   └── index.js      # 路由配置（3 个页面）
    ├── views/
    │   ├── HomeView.vue       # 首页仪表盘
    │   ├── SentimentView.vue  # 舆情分析页
    │   └── PersonalView.vue   # 个人事项页
    ├── components/
    │   └── StatCard.vue  # 统计卡片通用组件
    ├── api/
    │   └── posts.js      # 后端接口封装（/posts、/health）
    ├── mock/
    │   └── data.js       # 演示用 mock 数据（后端未启动时降级）
    └── assets/
        └── style.css     # 全局样式 / CSS 变量
```

## 页面说明

### 首页（`/`）
- 欢迎横幅 + 在线状态提示
- 6 张统计卡片（总帖数、高风险、新增线索、课程、DDL、后端状态）
- 近 7 天舆情趋势迷你柱状图
- 最新帖子列表（对接后端 `/posts` 接口，后端不在线时自动切换 mock）
- 高风险预警快览 + 今日事务摘要

### 舆情分析页（`/sentiment`）
- 风险统计卡片（高/中/低风险数量）
- 搜索 + 风险等级 + 状态多维筛选
- 帖子列表（分页，点击高亮）
- 右侧热点事件卡片（点击展开 AI 摘要、风险原因、处理建议）

### 个人事项页（`/personal`）
- 5 张统计卡片（课程/作业/DDL/提醒/活动）
- 今日日程时间轴
- AI 每日建议（支持一键刷新）
- 本周课表缩略视图（7 天网格）
- 作业与 DDL 列表（优先级标签 + 状态）
- 活动推荐卡片（加入日程功能）
- 提醒中心

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

如果后端服务（FastAPI，端口 9000）已启动，前端会自动代理 `/posts`、`/health` 等接口；否则自动降级到 mock 数据展示。

## 构建

```bash
npm run build    # 产物输出到 dist/
npm run preview  # 本地预览构建结果
```

## 接口约定

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回 `{ status: "ok" }` |
| GET | `/posts?page=1&page_size=20` | 获取帖子列表 |

## 第一周交付物清单

- [x] 页面草图（见 `docs/` 目录）
- [x] 前端项目骨架（Vue 3 + Vite + Element Plus）
- [x] 路由（3 个核心页面）
- [x] Mock 数据展示（首页 + 舆情 + 个人事项）
- [x] 后端接口对接（/posts，含降级）
- [x] 本 README
