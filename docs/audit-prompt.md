# 审核提示词（给新会话的模型）

复制下面整段作为第一条消息。

---

我要你对这个项目做一次**深度审核与 bug 排查**，重点是 Agent 部分。这是一个软件工程课程大作业，
两周内答辩，所以你找到的问题要按「**答辩现场会不会炸**」来排优先级。

## 项目

「校声智枢」——中山大学校园舆情 AI 平台。爬取小红书/快手/知乎/微博/贴吧的公开校园讨论，
清洗打分、语义聚类成「公共事件」、LLM 研判风险与状态、生成简报、采集证据，
并提供一个对话式舆情助手。

- 主仓（唯一事实来源）：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`
- 后端：Python + FastAPI + SQLAlchemy + MySQL（**共享 RDS，组员共用**）
- 前端：Vue 3 + Element Plus
- LLM：OpenAI 兼容端点（gpt-5.4）+ 智谱 GLM

## 环境与命令

```powershell
# 测试框架是 unittest，不是 pytest
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -q      # 全量（当前 893 个，全绿）
.\.venv\Scripts\python.exe -m unittest backend.tests.test_xxx -q         # 单个

# 事件流水线（会写共享库！只读地看请加 --preview）
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview

# 消融实验（可复跑，temperature=0 + 缓存）
.\.venv\Scripts\python.exe scripts\ablation_event_judge.py
```

## 核心设计原则（读代码前先记住这句）

> **可测量的用算术，需要判断的用 AI。**

- 热度（互动量）、时效性（`0.5^(age/21天)`）、「这事还在不在长」（发帖速率）、
  「两条帖子差了几年」 → **算术**
- 严重性、「有没有悬而未决的事」、「这条帖子属不属于这个事件」、生成检索词 → **LLM**

四轴排序：`priority = severity(risk_level) × recency(age) × lifecycle(状态)`，
`heat_score` / `heat_rank` / `ranking_score` 独立保留，**LLM 永远不许改它们**。

## 架构

```
backend/agent/public_opinion_core/     ← 可移植内核，**仅标准库**，不 import 任何 backend.*
                                          能力靠依赖注入（Embedder / RiskAssessor / ClusterRefiner …）
                                          注入 None ⇒ 优雅降级到规则版，逐位一致
backend/services/                      ← 适配层：把 DB / LLM / embedding 注入内核
backend/routers/                       ← HTTP
frontend/src/views/                    ← Vue
scripts/                               ← 离线流水线 + 消融实验
```

**人工闸门**：AI 提议，人来定夺。事件要管理员点击才 published；证据要 verified + approved 才交付；
选题关键词要审批才进爬取队列。

## ⚠️ 先读注释再下结论

这个代码库里有**大量中文注释在解释「为什么这么做」**，而且很多是踩过坑之后写的。
你觉得「奇怪」的地方，八成有原因写在旁边。**在把某件事叫 bug 之前，先找有没有注释解释它。**

## 已经修过的（别当新发现报给我）

近期一轮改造已完成，别重复发现：

1. **聊天延迟**：流式输出（SSE）、AI 审校挪到正文之后、ReAct 步数预算 bug、
   LLM 客户端连接池 / 缓存单例 / 缓存原子写、意图路由规则抢答。
2. **事件流水线并行化**：per-event 的 LLM 研判从串行改 8 路并发，结果逐位一致。
3. **检索准确性**：`source_keyword` 和 `top_tags` 的弱信号污染、`representative_notes[:3]`
   静默截断、聊天不读 `public_events`（改成三层检索：字面 → 语义余弦 → LLM 裁决）。
4. **聚类时间约束**：一个事件的成员帖时间跨度不得超过 90 天（一条 2021 年的疫情帖曾被聚进
   2026 年的宿舍搬迁事件，占了该事件 90% 的热度）。连带修了精修的跨簇同名合并、
   `event_key` 撞车（key 只哈希头帖标题，撞了会导致事件行覆盖 + 链接叠加）。

## 已知的开放问题（别当新发现）

- **语料只有 4% 是近 30 天的**（397 帖里 93 帖是 2024 年以前的）。这是数据问题，不是代码问题。
- `data/llm_cache.json` 和 `data/public_opinion_memory.json` 被 git 跟踪，每次运行都变脏。
- 语义检索里「论文造假」余弦只有 0.54（阈值 0.65），靠 LLM 裁决层捞回来。
- 项目没有 git remote。
- API key 需要在答辩后轮换。

## 🔥 测量陷阱（这一节能帮你省半天，都是我们真踩过的）

**任何延迟/准确率数字，先确认你不是在测一个假象：**

1. **`TestClient` 会缓冲 SSE**。它把 ASGI 应用一路驱动到底再返回，测出来「首字时间 = 总时长」，
   看着像流式没生效。**要测真实流式时序，必须起真 uvicorn。**
2. **本机的 Clash 代理会劫持 localhost**。curl 打本地服务返回 502。
   httpx 要 `trust_env=False`（Windows 上它还会读注册表里的系统代理，清环境变量没用）。
3. **测 LLM 延迟时缓存必须关掉**（`LLM_CACHE_ENABLED=false`）。否则你测的是「缓存有多快」。
4. **测之前先预热**：embedding 模型冷启动 26 秒，httpx 连接池冷的时候 LLM 调用要 11 秒（热了 3.6 秒）。
   不预热就比较，会跑出「做的事更多的臂反而更快」这种一看就假的数。
5. **控制台是 GBK，中文会乱码**。把结果写成 UTF-8 文件再读回来，别信控制台输出。
6. **厂商的官方聊天机器人会编 API**。智谱的机器人曾经编造了一个不存在的响应结构，
   还说「glm-5.2 不存在」（它存在）。**任何 API 行为都要真调一次才算数。**

## 🔒 硬约束（违反任何一条都是严重错误）

1. **绝不写共享 MySQL**，除非：干跑预览 → 我确认 → 执行 → 幂等复跑验证。
   查库随便查（只读）。写库必须先问我。
2. **绝不提交**这三个文件：`MediaCrawler/config/base_config.py`（我的本地冒烟改动）、
   `data/llm_cache.json`、`data/public_opinion_memory.json`。
3. **只 `git add` 明确路径，绝不 `git add -A`**。
4. `.env` 里有共享 RDS 凭据和 API key。**只显示键名，值一律打码。**
5. `backend/agent/public_opinion_core/` **必须保持仅标准库**（不许 import `backend.*`）。
   这是架构分界线。

## 我要你找什么

**「真 bug」的定义**：能让系统**信誓旦旦地给出一个错误答案**的东西——尤其是**静默**的。

这个代码库真实出现过的 bug，都是这个形状：

- **检索污染**：`source_keyword`（爬虫搜索时用的词）被当成「帖子在讲什么」，
  于是「97岁生日快乐」被检索成「宿舍搬迁舆情」。
- **静默截断**：`representative_notes[:3]` 把最切题的那条帖子（热度为 0 但内容最相关）
  挡在了 prompt 外，模型读到的是 5 年前的旧帖。
- **静默数据丢失**：并发写缓存时读者能读到半个 JSON，而解析失败是**静默返回 `{}`**——
  整个缓存无声丢光。
- **约束失效**：ReAct 的步数预算被坏 JSON 绕过（`continue` 但不计步）。
- **身份撞车**：`event_key` 只哈希头帖标题，两个簇撞同一个 key → 事件行互相覆盖、
  链接互相叠加 → 已发布事件里混进了别的簇的帖子。
- **两条管线看到不同的世界**：事件页说「宿舍搬迁 medium 风险 6 帖」，
  聊天却说「未检索到相关内容」。

**不要给我**：命名建议、格式问题、「可以考虑加类型注解」、泛泛的「建议增加错误处理」。

## 建议的审核范围（按我认为的风险排序）

我近期只深挖了「聊天 + 事件聚类 + 检索」这条线。**下面这些我基本没审过**：

1. **证据采集**（`backend/services/evidence/`，`scripts/collect_evidence.py`）——
   联网搜索 → URL 抓取校验 → 人工审核 → 交付。**这条链路上有 68 条 pending 的证据从没被交付过。**
2. **智能选题**（`backend/services/keyword_suggestion_adapter.py`,
   `public_opinion_core/keyword_planner.py`, `llm_keywords.py`）
3. **数据管道**（`scripts/sync_media_to_raw_posts.py`, `scripts/process_raw_posts.py`）——
   爬虫原生表 → `raw_posts` → `processed_posts`。热度计算、平台内归一化都在这。
4. **情感分析**（`sentiment_llm.py`, `public_opinion_core/sentiment_risk.py`）——
   这里曾经有个 bug：`aggregate_sentiment` 把一场宿舍火灾判成了 `positive`
   （它只把 positive 和 negative 比，忽略了 neutral）。
5. **认证与权限**（`backend/services/auth_service.py`, `backend/routers/admin*.py`）
6. **前端**（`frontend/src/views/`）——我只改过 `AgentChatView.vue`。

## 交付要求

**每一条发现都要带证据，不要断言。**

对每个 bug：
1. **它是什么**（一句话）
2. **怎么复现**（具体的输入 / 数据 / 命令）——最好是一个**会失败的测试**
3. **后果**（答辩现场会怎样）
4. **file:line**

**你不确定的，就说不确定。** 我宁可要 5 条确凿的，也不要 30 条「可能有问题」的。

如果你发现**上一轮改造（我做的）有做错的地方，直接说**——尤其是那些新加的东西：
三层检索、时间窗、并发化、流式。它们是新的，最可能有洞。

先跑一遍全量测试确认基线（893 全绿），然后开始。
