# backend/routers — 接口层（薄控制器）

9 组 FastAPI 路由。职责只有三件事：解析请求 → 调 `services/` → 用 `schemas.ok()` 统一封装返回。
**业务规则不写在这里**（分层约定见 [backend/README.md](../README.md)）。

| 模块 | 前缀/职责 | 鉴权 |
|------|-----------|------|
| `api.py` | 基础接口：`/ping` 健康检查、`/posts` 帖子读取 | 公开 |
| `auth.py` | 登录/注销/当前用户（JWT） | 公开(登录)/登录态 |
| `agent_public.py` | 舆情 Agent：对话（流式/阻塞）、事件、报告 | 公开 |
| `comments.py` | 事件评论区：公开读、登录写、管理员管控 | 分级 |
| `submissions.py` | 用户投稿 + 图片上传 + 管理员前置审核 | 登录/管理员 |
| `feedback.py` | 用户反馈 | 登录 |
| `admin.py` | 管理后台基础：用户、原始帖、运维统计 | 管理员 |
| `admin_events.py` | 舆情事件审核动线：发布/驳回/归档、人工修正、审核日志 | 管理员 |
| `admin_evidence.py` | AI 联网证据的采集、核验与交付 | 管理员 |

接口契约（路径、参数、响应示例）见 [docs/api.md](../../docs/api.md)。
新增路由需在 `backend/main.py` 挂载，并在 `backend/tests/` 添加接口测试。
