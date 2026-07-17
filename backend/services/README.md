# backend/services — 业务层（编排与规则）

33 个服务模块，按职责分组如下。分层约定：`routers` 只调这里；这里可以调
`agent/public_opinion_core`（纯标准库核心）；**核心不回头 import 本层**（依赖单向向下）。

`event_*` 系列的共同模式：核心包里是"纯逻辑 + 注入 LLM 函数"，本层负责把它们
**接到真实模型上**（读配置、建客户端、处理降级）。

## 对话主线（舆情助手）

| 模块 | 职责 |
|------|------|
| `opinion_chat_service.py` | 对话总编排：路由 → 检索 → 生成 → 审校，流式/阻塞双入口 |
| `intent_router.py` | 意图路由：规则有把握时抢答（省 ~4s），否则 LLM 分类 |
| `router_keywords.py` | 语料播种关键词 → 路由动态词表（启动时刷新） |
| `react_loop.py` | 复杂问题的 ReAct 多步工具循环 |
| `opinion_report.py` | 确定性报告构建器（简报/研判的骨架来自数据，不靠模型自由发挥） |
| `citations.py` | 引用编号体系（pN/eN）：让报告的每句话可溯源 |
| `critic.py` | 生成后事实审校（发现问题记入 meta.review） |
| `prompt_guard.py` | 提示注入防御：爬取内容进 prompt 前的清洗 |
| `chat_memory_store.py` | 会话记忆持久层（写穿 SQLite，重启恢复上下文） |
| `search_filters.py` | LIKE 通配符转义（用户输入的 % _ 按字面处理） |

## 事件流水线（离线生成 + 在线读）

| 模块 | 职责 |
|------|------|
| `event_refiner.py` | 聚类 LLM 精修接线（拆误合并的大桶） |
| `event_merger.py` | 近重簇合并裁决接线 |
| `event_risk.py` | 事件级风险研判接线 |
| `event_lifecycle.py` | 生命周期研判接线（这件事还悬着吗） |
| `event_judge.py` | 检索裁决：用户问的是不是这件事 |
| `event_keywords.py` | 从事件生成爬取检索词 |
| `event_prescreen.py` | draft 事件的 LLM 预审建议（供审核员参考） |
| `event_curation.py` | 人工事件修正：改名/合并/建删/帖子进出 |
| `event_read_model.py` | 已发布事件的读模型 |
| `heat_ranking.py` | 平台内热度归一化（heat_rank）与权威度 |
| `keyword_suggestion_adapter.py` | 智能选题聚合：五路信号 → 核心 planner |

## LLM 与语义基础设施

| 模块 | 职责 |
|------|------|
| `llm_client.py` | OpenAI 兼容客户端：重试、本地缓存、用量统计、备胎链 |
| `llm_config.py` | LLM/embedding 运行时配置 |
| `embedding.py` | bge-small-zh 语义向量封装（可选依赖，缺席自动降级） |
| `semantic_posts.py` | 帖子层语义检索（离线向量 + 在线余弦） |
| `sentiment_llm.py` | LLM 情感分类（逐条规则兜底） |
| `web_evidence.py` | GLM 联网检索 → ReAct 的站外证据 |

## 数据接入与业务 CRUD

| 模块 | 职责 |
|------|------|
| `public_opinion_adapter.py` | processed_posts ↔ 可移植核心的适配器 |
| `comment_loader.py` | MediaCrawler 原生评论表 → 高赞评论摘录 |
| `auth_service.py` / `admin_service.py` | 鉴权 / 管理后台业务 |
| `comment_service.py` / `submission_service.py` | 评论区 / 投稿的业务规则 |
| `log_service.py` | 任务与运行日志统一写入 |
