# 事件状态研判（生命周期）：悬而未决的事不随时间沉底

> 代码：`backend/agent/public_opinion_core/llm_lifecycle.py`（核心，判断）、
> `backend/agent/public_opinion_core/recency.py`（算术，因子）、
> `backend/services/event_lifecycle.py`（部署，接模型）、
> `backend/routers/api.py::sort_event_rows`（读侧排序，前端真正消费的那个顺序）
> 消融：`scripts/ablation_event_lifecycle.py` -> `docs/event-lifecycle-ablation.md`

## 1. 被修的缺陷

时效衰减（17d5ef2）把排序键变成 `severity_weight(risk_level) × 0.5 ** (age_days / 21)`，
一举把五年前的旧事件从首屏赶了下去。**但它只认年龄**：两个同龄的事件，在它眼里没有区别。

而真实语料里，同龄的事件可以处在完全不同的状态：

| 事件 | 年龄 | 严重性 | 真实状态 |
| --- | ---: | --- | --- |
| 东校区宿舍火情 | 3.5 个月 | high / 95 | 火已扑灭、校方已通报、无人员伤亡、调查已立案 —— **事情结束了** |
| 中大杰青实名举报 | 2.2 个月 | high / 91 | 调查有结论了吗？没有 —— **口子还开着** |
| 中大作息调整争议 | 2.5 个月 | medium / 62 | 校方只说「会关注师生关切」—— **然后呢？** |

火情作为记录仍然严重（严重性是事实，不因时间打折，这一点没变），但**学校已经不需要再为它
做任何动作**；举报和作息争议没有结论，它们仍然是学校要处置的东西——哪怕最后一条帖子是两个月前的。

**「已了结」还是「悬而未决」是对内容的判断，不是时间的函数。**

- **时间戳答不了**：停止发帖既可能是因为事情解决了，也可能是因为没人再关注但问题还在。
- **关键词答不了**：「通报」既出现在"校方已通报处理结果"里，也出现在"至今未见校方通报"里；
  同一个词，相反的状态。这是闭集词表的死穴，和 `llm_risk.py` 里那六个电诈词是同一类问题。
- **读一遍帖子的模型答得了**。

这是时间这根轴上**唯一**该上 LLM 的地方——衰减本身是算术（`0.5 ** (age/21)`，可解释、可复现、
零调用），一个字节都不许 LLM 碰。

## 2. 设计：第四根正交轴

四根轴，各判各的，互不改写：

| 轴 | 字段 | 谁算的 | 答的问题 |
| --- | --- | --- | --- |
| 严重性 | `risk_level` / `risk_score` | LLM（`llm_risk.py`） | 学校要不要立即处置？**不随时间打折** |
| 流行度 | `heat_score` / `heat_rank` | 算术（实测互动量） | 这件事有多火？**不改写** |
| 时效性 | `recency_weight` | 算术（`0.5 ** (age/半衰期)`） | 这件事多新？**只是年龄的函数** |
| **生命周期** | **`lifecycle` / `lifecycle_reason`** | **LLM（`llm_lifecycle.py`）** | **这件事完了没有？** |

    priority_score = severity_weight(risk_level) × recency_weight × lifecycle_weight(lifecycle)

### 三个状态（为什么是这三个）

| 状态 | 含义 | 因子 |
| --- | --- | ---: |
| `resolved`（已了结） | 已处置完毕 / 已通报结论 / 已结案。**学校不需要再做新的动作**。严重的事一样可以是 resolved（火灭了、通报发了、立案了） | ×0.5 |
| `ongoing`（悬而未决） | 没有结论：校方未回应、只有表态性回应（"会关注"/"已收到材料"）、调查仍在进行 | ×2 |
| `escalating`（持续发酵） | 没有结论 **且还在扩大**：新帖仍在增加、蔓延到更多平台、出现联名/集体行动 | ×4 |
| （未研判） | LLM 关掉 / 超时 / 幻觉 / 老数据 | ×1.0（**恒等**） |

后两者都该抗衰减，但**程度不同**：一个还在涨的舆情比一个冷下来但没结论的事更急；把它们压成
一档，等于承认"我们分不出急和不急"。四档以上（如 `monitoring`）在这份语料上没有可靠证据支撑，
模型只会瞎猜。

### 因子的量级（为什么是 4 / 2 / 0.5）

**取 2 的幂，因为这样能用半衰期读**，而这是答辩上唯一站得住的解释方式：

    0.5 ** ((age - 21) / 21)  ==  2 × 0.5 ** (age / 21)

- `×2`（ongoing）⇔ 把事件当作**年轻了一个半衰期（21 天）**；
- `×4`（escalating）⇔ 年轻两个半衰期（42 天）；
- `×0.5`（resolved）⇔ 当作**老了一个半衰期**。

于是「悬而未决」有了精确的含义：**它抵得过三周的沉底，不多不少**。

**上界是刻意压住的**：整根轴的动态范围是 8×（0.5 → 4），**小于严重性的 9×**（low → high）。
所以「持续发酵的低风险」永远压不过「已了结的高风险」——生命周期是第四根轴，不是推翻严重性的后门。
（它确实能翻转相邻档：一个持续发酵的 medium 可以压过一个已了结的 high。这是**要的**行为：
火已经灭了、通报也发了，学校不需要再对它做动作；那个还在发酵的争议需要。实测里这正是
「作息调整争议」升到第 3、「宿舍火情」落到第 4 的原因。）

**「已了结」不等于删除**：3.5 个月的火情打了 0.5 折仍排第 4 / 28 —— severity 95 托着它。

### 降级：未研判 = 恒等，不是"已了结"

`lifecycle=""` -> 因子 **1.0**。这条口径和 `recency_weight` 对未知年龄、`platform_weights` 对
未知平台的口径完全一致：**"不知道结没结" ≠ "已经结了"**，绝不许凭空把一个事件打折沉底。
它同时是降级保证的基石：LLM 全挂时公式逐位退化回改造前的 `severity × recency`，
排序不变，而不是变成随机。

## 3. 落地的每一个点

| 位置 | 改了什么 |
| --- | --- |
| `public_opinion_core/llm_lifecycle.py` | 新模块：`LifecycleAssessor` 协议 + `assess_events_lifecycle()` + 验证/逐事件降级。**stdlib only**，不 import `backend.*` |
| `public_opinion_core/recency.py` | 因子表 `LIFECYCLE_WEIGHTS` + `lifecycle_weight()`；`priority_score(risk, weight, lifecycle)`；`lifecycle_from_payload()`（读侧）。**衰减算术一个字节没动** |
| `public_opinion_core/schemas.py` | `OpinionEvent.lifecycle` / `.lifecycle_reason` |
| `public_opinion_core/clustering.py` | `sort_events()` 的第一排序键带上第三个因子 |
| `public_opinion_core/service.py` | 编排：风险研判 -> **状态研判** -> 时效标注 -> 重排；`lifecycle_mode` / `lifecycle_assessed` / `lifecycle_counts` 记进 `agent_run_logs` |
| `public_opinion_core/payload_builder.py` | 状态落 `date_range_json`（**不加列**：共享 MySQL 的表结构不动，而这个字段本来就装着事件的时间维度） |
| `services/event_lifecycle.py` | 部署侧：提示词 + `call_llm`（temperature=0，走 JSON 缓存），唯一读 `EVENT_LLM_*` 的地方 |
| `services/llm_config.py` | `EVENT_LIFECYCLE_ENABLED`（复用 `EVENT_LLM_*` 与 `EVENT_RISK_MAX_TEXTS`） |
| `services/public_opinion_adapter.py` | 生产流水线注入 assessor；状态与模式回到 API 响应 |
| **`routers/api.py`** | **`sort_event_rows()`（前端真正消费的那个顺序）+ 事件 payload 带 `lifecycle` / `lifecycle_reason`。核心的 `sort_events` 只决定写库顺序，写完就被 `ORDER BY created_at DESC` 冲掉——两处都得改到** |
| `frontend/src/utils/lifecycle.js`、`views/OpinionView.vue` | 看板上的「悬而未决」/「已了结」徽标 + hover 显示模型给的理由 |

### 提示词挡的四种误判（`services/event_lifecycle.py`）

1. **问题不是"多严重"**：严重性已经有 `event_risk.py` 判过了，而严重的事**恰恰可能已经了结**。
2. **状态不是热度**：没人转发不代表事情解决了（火情播报只有 3 个赞，但它确实结束了）。
3. **表态不是结论**：「会关注师生关切」「已收到材料」「正在核实」——都是 `ongoing`。
   这是真实语料里最容易骗过关键词规则的一类句子。
4. **拿不准就选 `ongoing`**：两种错误的代价不对称——把没结论的事误判成 resolved，等于让看板
   提前埋掉一个还开着的口子（不可接受）；把已了结的事误判成 ongoing，代价只是它多留几天（便宜）。

## 4. 消融结果（真实输出见 `docs/event-lifecycle-ablation.md`）

`now=2026-07-12`，half_life=21 天，28 个事件全部研判成功（0 降级）：

| 事件 | 年龄 | 风险 | 模型判的状态 | 理由（模型原话） | A 臂（无状态） | B 臂（生命周期） |
| --- | ---: | --- | --- | --- | ---: | ---: |
| 中大杰青实名举报 | 2.2 个月 | high/91 | **持续发酵** | 举报仍在追加，质疑范围继续扩大 | 第 1 | 第 1 |
| 中大作息调整争议 | 2.5 个月 | medium/62 | **持续发酵** | 仍在联名反对发声，校方仅称会回应 | 第 5 | **第 3（↑2）** |
| 东校区宿舍火情 | 3.5 个月 | high/95 | **已了结** | 火势已控且校方通报无伤亡并启动调查 | 第 3 | **第 4（↓1）** |
| 中大缩短课间争议 | 2.5 个月 | medium/58 | 已了结 | 学校致歉并暂停问卷收集 | 第 4 | 第 5（↓1） |
| 中大学生诽谤被开除 | 5.1 年 | high/90 | 已了结 | 帖子称已拘留并开除学籍 | 第 16 | 第 17（↓1） |

火情判对了（`resolved`），并且**掉得很克制**：3.5 个月 + 0.5 折之后仍是第 4 / 28，severity 95
托着它——「已了结」不等于删除。

### 两个诚实的发现（模型判的和我预期的不一样）

**发现 1：举报和作息都判成了 `escalating`，不是我预期的 `ongoing`。**
理由分别是「举报仍在追加，质疑范围继续扩大」和「仍在联名反对发声，校方仅称会回应」——
读语料的话这两句都站得住（举报帖确实在追加，作息争议确实出现了联名）。方向是对的（都抗衰减），
只是模型认为它们不止"没结论"，而是"还在扩大"。**但这里有一个真实的方法论隐患**：模型看到的是
一份冻结的 fixture，它没法真正观察"新帖还在不在增加"——它是从帖子的**措辞**里推断出的发酵感。
换句话说，`escalating` 和 `ongoing` 的边界目前由文本语气决定，而不是由发帖速率决定。
这一档的判据比另外两档软，答辩时不该把它说得比实际更硬。（能用算术补上：成员帖的时间分布是
现成的，"最近 7 天的帖子占比"可以作为 escalating 的客观校验——但那是下一次的事，
这次不把没验证过的东西写进代码。）

**发现 2（更值得记）：咨询/分享类事件被判成 `ongoing`，理由是"未见校方结论"。**
「中大图书馆对外开放」「中大参观开放询问」「中大食堂对外开放」「中大计算机专业咨询」——
这些帖子是**问问题**（能不能进馆、能不能参观），不是**提诉求**：它们根本没有"待处置的事"，
既不是悬而未决，也谈不上已了结。模型按提示词里的「拿不准就选 ongoing」把它们判成了未决，
于是它们各拿了 ×2。**而同类的内容它又判了 resolved**（「中大考研信息汇总」「中大校园与宿舍展示」
判 resolved，理由是"未见待处置问题"）——**同一类内容，两种判法，这是模型在这一档上的不一致，
不是一个可以辩护的判断**。

影响是**有界的**：这些事件全都是 `low` 且年龄触到权重地板（1e-6），×2 之后仍排在第 19-22 / 28，
不会挤掉任何一个真事件（前 8 名一个都没变）。但它是真实的误判，如实记在这里：
真正的修法是给"无诉求的咨询/分享类内容"一个明确的归属（要么在提示词里点名判 resolved，
要么承认需要第四个状态 `not_applicable`），而不是让「拿不准就 ongoing」这条兜底规则去承接它。

### 完整性检查（脚本自动校验）

- `risk_level` / `risk_score` / `heat_score` / `heat_rank` / `recency_weight` 两臂逐事件比对：
  **全部一致** —— 状态只进排序，不改事实，也不改衰减算术。
- LLM 用量：28 次调用、27969 token、110 秒（temperature=0 + JSON 缓存 ⇒ 重复跑不再花钱）。

## 5. 降级（逐事件，全部有测试）

| 情况 | 行为 |
| --- | --- |
| 未配 key / `EVENT_LIFECYCLE_ENABLED=false` | assessor 为 `None`，跳过研判；所有事件因子 1.0，排序退化回改造前 |
| assessor 抛异常（超时/网络） | **该事件**保持未研判，warning 记进 `agent_run_logs`，其余事件不受影响 |
| 返回 `None` / 不是 JSON 对象 | 同上 |
| 编了一个不在枚举里的状态（`dormant`） | 同上（编造的状态永远不许变成一个排序因子） |
| 给不出理由（空串/不是字符串） | 同上（没有理由的判断在看板上和答辩里都辩护不了） |
| 一个事件都没判成 | `lifecycle_mode` 如实记成 `none`（**不许假装 AI 上过**） |
| 库里的 `lifecycle` 是脏值 | 读侧 `lifecycle_from_payload` 只认三个枚举值，其余一律当未研判 |

测试：`backend/tests/test_event_lifecycle.py`（核心 + 部署 + 服务编排，40 例）、
`backend/tests/test_events_api_lifecycle.py`（GET /api/events 的顺序与 payload，6 例）。
零网络、零数据库（内存 sqlite + 注入的假 assessor）。
