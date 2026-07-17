# Week6 舆情 Agent 集成（第二轮：对话助手）

## 1. 功能

对话式舆情问答，登录用户（user/admin）均可使用。LLM 意图路由把问题分发到 6 类处理：

| 意图 | 行为 |
|---|---|
| hotspots / risk_analysis / opinion_answer | 单步：取数 → LLM 总结（规则摘要兜底） |
| report | 简报生成 + **Critic 审校**（第二次 LLM 调用核对事实，warn 时附审校提示） |
| search | 关键词检索，返回帖子列表 |
| complex_analysis | **ReAct 多步工具循环**：LLM 自主决定调哪些工具（search_notes/hotspots/risks/overview）、调几次，再综合作答；思考轨迹随响应返回 |

支持追问继承话题（"食堂有什么风险？"→"严重吗？"自动沿用食堂）。全程只读 processed_posts，不写库、不碰审核流。

## 2. 端点契约

```
POST /api/agent/public/chat        Authorization: Bearer <token>（任意登录用户）
请求  { "message": "对比一下食堂和宿舍哪个风险更高？" }    # 1~500 字
响应  ok({
  "intent": "complex_analysis",
  "keyword": "",
  "answer": "结论：…",
  "route_source": "llm",                  // llm | rules（降级）
  "events": [...],                        // 单步意图附带的事件预览
  "steps": [{"thought","action","action_input","observation"}],  // 仅 complex
  "stop_reason": "answered",              // answered | max_steps | repeated_action | llm_error
  "degraded": false,                      // true 时 answer 为规则摘要
  "review": {"verdict","issues"},         // 仅 report 意图
  "citations": {"p1": {"title","url","event_title"}}  // 仅 report 意图，[来源:pN] 的溯源映射
})
```

注意：复杂问题（推理模型多次调用）耗时 1~2 分钟，前端 `api/agentChat.js` 已单独放宽超时到 180s；重复问题命中本地 LLM 缓存秒回。

## 3. 新增文件

后端（`backend/services/`）：`intent_router.py`、`react_loop.py`、`critic.py`（子项目移植，那边 207 测试守护）、`opinion_report.py`（核心 schema 版报告构建）、`opinion_chat_service.py`（DB 版对话服务）；`routers/agent_public.py` 新增 chat 端点。

前端：`api/agentChat.js`、`views/AgentChatView.vue`（气泡对话 + 意图/路由徽标 + 推理轨迹折叠 + 降级/审校警示）；路由 `/agent-chat`，侧边栏"舆情助手"。

## 3.5 多轮对话上下文（2026-06-13 补充）

- 服务端按用户保留**最近 3 轮对话**（助手回答截断 200 字存储），注入答案生成 prompt，支持"刚才提到的第一条依据再展开讲讲"式指代追问
- 意图路由器新增 `last_intent` 上下文：追问类消息沿用上一轮意图，不再落进 search 兜底（真实验证发现并修复的缺口，子项目提交 8a9d410）
- 请求体新增 `reset: bool`，为 true 时清空该用户会话记忆；前端"新对话"按钮已接
- 路由仍用原句（历史会干扰关键词提取），历史只进答案生成
- 主项目新增测试基建：`backend/tests/`（8 个用例，`python -m unittest backend.tests.test_opinion_chat_history`）

## 3.6 引用强制的可审计简报（2026-07-08 补充）

- report 意图升级为引用溯源模式：代表帖编号 `p1..pN`，LLM 论断句末必须标注 `[来源:pN]`；响应新增 `citations` 映射（pN → 标题/原帖链接/所属事件），前端可渲染成可点击角标
- 校验双层：确定性校验零成本抓幻觉引用（引用了不存在的编号）和零引用，命中强制 warn；critic LLM 再逐条核对论断与被引帖子是否相符
- 降级保护：LLM 降级为规则摘要时跳过引用审计（不误报"无引用"、不对故障服务二次重试）；关键词无匹配数据（`citations` 为空）时不强制引用
- 安全：帖子文本里伪造的 `[来源:pN]` 标记编号前剥离；`citations` 里的 url 仅保留 http(s)
- 设计细节与实测见子项目 `docs/week7-agent-citation-grounded-report.md`；主项目回归测试 `backend/tests/test_opinion_chat_citations.py`（3 个用例）

## 4. 已知限制

- 会话记忆（话题词、上一轮意图、最近 3 轮对话）存进程内存：多 worker 部署或重启后丢失，后果仅是追问需重新带话题词
- 对话工具用规则情绪（速度优先）；LLM 级情绪在 `/agent/public/analyze` 里
- 同一用户并发提问会共享会话记忆，可能互相覆盖（课程项目可接受）

## 5. 真实验证记录（2026-06-13，182 条小红书数据）

- "最近有什么热点？" → hotspots（LLM 路由），返回真实事件表格，27s
- "Python相关的内容大家怎么看？" → opinion_answer，keyword=Python
- "严重吗？" → risk_analysis，**keyword=Python 自动继承** ✓
- "对比一下食堂和宿舍哪个风险更高？" → complex_analysis，ReAct 两次 `risks` 调用（食堂/宿舍），75s，给出带真实风险分的对比结论 ✓
- HTTP 层：无 token 401；user token 200；重复问题命中缓存 0.8s ✓
- `npm run build` 通过

## 6. 人工验收清单（启动 dev.bat 后过一遍）

1. 普通用户登录 → 侧边栏出现"舆情助手" → 进入页面点示例问题
2. 简单问题约 20~30s 出答案，带意图/路由徽标
3. 复杂对比问题出现"查看推理过程（N 步）"折叠面板
4. "给我一份校园舆情简报" → 出简报，若有审校提示显示黄色警示
5. 断网/清空 OPENAI_API_KEY 再问 → 答案为规则摘要 + 降级提示（验证兜底）
