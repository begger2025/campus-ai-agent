# 智能选题接入事件流水线：一半是算术，一半是 LLM

> 消融实测报告：[`keyword-event-ablation.md`](keyword-event-ablation.md)（真实事件集，可复现）
> 核心算法：`backend/agent/public_opinion_core/keyword_planner.py`、`llm_keywords.py`
> 部署接线：`backend/services/keyword_suggestion_adapter.py`、`event_keywords.py`

## 一、缺陷：左手不知道右手

```
grep -c event backend/agent/public_opinion_core/keyword_planner.py \
             backend/services/keyword_suggestion_adapter.py
->  0 和 0
```

**爬取选题器从来没听说过「事件」。** 它的候选池只有两个来源：用户问过什么
（`ChatQueryLog`）、已经爬回来什么（`ProcessedPost` 标签）。

与此同时，事件流水线正在发布：

```
中大杰青实名举报    risk=high(91)  lifecycle=ongoing  priority=2.03   ← 头号未决事件
东校区宿舍搬迁      risk=medium    lifecycle=ongoing  priority=1.18
中大作息调整争议    risk=medium    lifecycle=ongoing  priority=0.50
```

而选题器推荐的是：`食堂 / 宿舍 / 毕业季`。

**系统把一起持续发酵的学术不端丑闻定为头号事件，它自己的爬取计划器还在建议爬「食堂」。**

## 二、分工：测量归算术，判断归 LLM

这是本项目五个 commit 一以贯之的那条线。本次改造**恰好横跨它**，所以两半必须分清楚：

| 问题 | 谁来答 | 为什么 |
| --- | --- | --- |
| 这件事有多严重（`risk_level`） | **LLM**（早就判完并落库了） | 校园出事的方式穷举不完 |
| 这件事完了没有（`lifecycle`） | **LLM**（早就判完并落库了） | 「悬而未决」是对内容的判断 |
| 这件事多老（`recency_weight`） | **算术** | `0.5**(age/21)`，减法和指数 |
| 这件事还在长吗（`growth`） | **算术** | 数成员帖的 `publish_time` 分布 |
| **这个词有多值得爬** | **算术** | 见 §3——**三个数都是现成的** |
| **这件事该用什么词去搜** | **LLM** | 见 §4——**排序器排不出它没见过的词** |

## 三、算术那一半：事件 → 候选池（**零 LLM**）

严重性、生命周期、时效性**都已经算好并落在 `public_events` 里了**。把它们接进选题器是
**接线，不是智能**：

```python
event_priority = severity_weight(risk_level)      # LLM 判的，9 / 3 / 1
               × recency_weight(age_days)          # 算术，0.5**(age/21)
               × lifecycle_weight(lifecycle)       # LLM 判的，4 / 2 / 0.5
               = recency.priority_score(...)       # ← 一个数都不重新发明
event_norm     = event_priority / max(event_priority)   # 与 demand_norm / heat_norm 同一个套路
```

### 3.1 它怎么和原有的三路权重复合

原式：`score = (0.5·demand + 0.3·gap + 0.2·heat) × crawl_penalty × 10`（权重和为 1，分∈[0,10]）

新式：

```
score = (0.5·demand + 0.3·gap + 0.2·heat) × crawl_penalty × 10        ← 一个字节都没动
      +  0.3·event_norm × event_penalty  × 10                          ← 加项
```

**为什么是「第四个加项」，不是把老三路重新归一化成 0.35/0.21/0.14/0.30。**
后者数学上更漂亮（和仍为 1、分数仍∈[0,10]），代价是：**一个事件都没有的部署，每个候选词
的分数会凭空掉 30%**——这一路明明什么都没说，却改写了所有人的答案。取加项则有
**逐位退化保证**：`events=[]` ⇒ `event_norm ≡ 0` ⇒ 分数与改造前**完全一致**
（`test_keyword_event_signal.py::DegradationTest` 钉死，且原有 15 个 adapter 测试的
断言值 8.0 / 2.4 / 0.6 / 0.8 一个都没改）。

**代价如实记：分数上界从 10 变成 `10 × (1 + 0.3) = 13.0`。** 一个诚实的量纲变化，好过一次
静默的全局贬值。

**`W_EVENT = 0.3 = W_GAP`。** 排序读作一句人话：

> **真人敲下的问题 (0.5) > 系统推断的当务之急 (0.3) = 站内供给不足 (0.3) > 已有内容的热度 (0.2)**

事件信号本质上就是一种 gap（「这件事正在发生，而我们的语料里没有它」），所以与 gap 同权；
但它是**推断**出来的，而一个真实用户的提问是**事实**，所以压不过 demand。
消融实测印证了这个选择：改造后「食堂」**依然是第 1 名**（真的有人问过它），而丑闻的检索词
紧随其后占据 2-7 名。

### 3.2 `crawl_penalty` 的张力：「昨天刚爬过」 vs 「这是头号未决丑闻」

爬取降权（14 天内爬过 ×0.3、贫瘠词 ×0.1）问的是一个具体问题：**我们是不是已经有这份数据了？**

对**不同的信号**，这个问题的答案不一样——所以 penalty **分别**作用在两个加项上：

| 情形 | 事件项的 penalty | 理由 |
| --- | --- | --- |
| 事件 `ongoing` / `escalating` | **1.0（不降权）** | 新帖**还在来**（`growth` 是算术测出来的）。「昨天爬过」只说明我们有了**昨天以前**的存量，对今天新增的证据它什么都没说。 |
| 事件 `resolved` / `not_applicable` / 未研判 | 继承 ×0.3 | 不会再有新证据了，「昨天爬过」就是真的「我们已经有了」。 |
| **词在贫瘠集合里** | **×0.1（不豁免）** | 贫瘠是关于**这个词**的证据——我们拿它搜过，什么都没捞回来。**事件再急，一个搜不到东西的词也搜不到东西。** 豁免它等于让「火烧眉毛」变成绕过实测结果的通行证。 |

消融里看得见这条规则在工作：`ongoing` 事件的词（学术不端 3.00、强制搬宿舍 1.73）reason 里带
「事件仍在发酵、新证据仍在产生（爬取降权对事件项不适用）」；`resolved` 事件的词
（宿舍起火、楼道浓烟）老老实实停在 0.19。

### 3.3 标签权重：`count / max_count`（消融第一版打脸后加的）

**第一版消融的真实输出**：头号事件「中大杰青实名举报」的 `top_tags` 是
`学术(3) / 热点(1) / 新闻(1) / 社会新闻(1) / 学术论文(1) / 医学(1) / 上海(1) / 广州(1)`。
一个事件的所有标签共享同一个 `event_norm=1.0` ⇒ **「上海」「广州」「新闻」和「学术不端」
并列 3.00 分，一起顶上首屏。**

修法是**算术，不是往黑名单里再塞几个词**：`top_tags_json` 里本来就存着 `count`（几条成员帖
带这个标签）。**3 条帖子都带「学术」，只有 1 条带「上海」**——权重 = `count / max_count`。
（往黑名单里加「上海」「广州」治不了：下一个事件是「深圳」「珠海」，穷举不完——同 `llm_risk`
顶部对闭集词表的那个论证。数标签出现在几条帖子上，是**测量**。）

**LLM 生成词不吃这个折扣（权重恒 1.0）**：它是被**当作检索词提出来的**，不是被顺手打上的标签。

## 四、LLM 那一半：事件 → 检索词（**规则结构上做不到**）

事件「中大杰青实名举报」应该让系统想去爬「学术不端」。可：

> **「学术不端」不出现在任何标题、任何标签、任何用户提问里。**
> （该事件的 `top_tags` 是 学术/热点/新闻/社会新闻/学术论文/医学/上海/广州——一个能拿去搜的都没有。）

现行 planner 是一个**排序器**：它只能给**字面上已经出现过**的字符串打分。所以它**永远**提不出
「学术不端」——不是权重不够，是候选池里根本没有这个字符串。

**这不是一条僵化的规则，这是一条生不出语言的规则。** 往词表里再加一百个词也修不了它：
下一个事件是导师霸凌、食物中毒、电梯困人，要的词是「师德」「食物中毒」「电梯故障」。
**这才是 LLM 真正该站的地方**：它读得懂「耿同学继续举报中山大学另一位杰青」讲的是学术不端，
然后**说出**这个词。

### 4.1 seam（与 `llm_risk` / `llm_lifecycle` 完全同构）

```
public_opinion_core/llm_keywords.py     ← stdlib-only，只认识一个 Callable
    KeywordProposer = (title, texts, risk_level, lifecycle) -> Sequence[str] | None
backend/services/event_keywords.py      ← 唯一读 EVENT_LLM_* 、发 HTTP 的地方
    temperature=0 + call_llm 缓存 ⇒ 可复现、重复跑不花钱
```

### 4.2 提示词的四条硬要求（每条都在防一个具体的失败）

1. **「一个真人会在小红书/微博/知乎搜索框里敲什么」**——是**检索词**，不是摘要、不是主题词。
2. **不许带学校名**：爬虫会自己拼 `CRAWL_TOPIC_QUALIFIER`
   （`compose_topic_keyword("学术不端", "中山大学") -> "中山大学 学术不端"`）。关键词里再带一遍，
   等于把 12 字的预算花 4 个字买重复。
3. **不许泛泛的词**（校园/大学/热点/新闻…）——搜出来全是噪音。
4. **只提这件事特有的说法**：能把它和别的事件区分开的那几个字。

### 4.3 安全边界

- **走 planner 自己的卫生规则**：`normalize_keyword` / `GENERIC_BLACKLIST` / `MAX_KEYWORD_LEN(12)`。
  **LLM 提「校园生活」，和用户提「校园生活」被同一条规则拒掉——AI 不享有绕过校验的特权。**
- **逐事件降级**：超时 / 返回 `None` / 返回垃圾 / 提的词全被拒 ⇒ 该事件不贡献生成词、记一条
  warning、**别的事件照常工作**，而且该事件的**标签词（算术那一路）一个都不少**。
  LLM 整个关掉（`EVENT_KEYWORDS_ENABLED=0`）⇒ 事件仍然进候选池、仍然按 priority 加权，
  只是提不出语料里没有的新词。
- **只在算术已经说它重要的事件上花钱**：按 `event_priority` 降序取 top-5（`EVENT_KEYWORD_TOP_EVENTS`）。
  **算术先说哪件事重要，LLM 才去为它想词。**

## 五、出处是强制的

每一条建议都带 `event_refs`：

```json
{"keyword": "学术不端", "score": 3.0, "signals": ["event_llm"],
 "event_refs": [{"event_id": "20", "title": "中大杰青实名举报",
                 "risk_level": "high", "lifecycle": "ongoing", "origin": "event_llm"}],
 "reason": "来自high风险事件「中大杰青实名举报」（悬而未决，LLM 据该事件正文生成），
            事件仍在发酵、新证据仍在产生（爬取降权对事件项不适用），从未作为关键词爬取"}
```

管理员点开就知道「学术不端」是**从哪件事上长出来的**，而不是一个凭空冒出来的词。
`origin` 三选一：`demand`（用户问的）/ `event_tag`（内容标签）/ `event_llm`（**LLM 从事件生成**）。

## 六、人工闸门没有动

`GET /api/admin/keyword-suggestions` 只**返回建议**。把一个词放进爬取队列，**必须**由管理员
再点一下——**没有任何东西被自动入队**。

这和证据投递、事件发布是同一条纪律：**AI 提议，人来决定。**

消融里有一个正好命中这条纪律的例子：模型提出了「耿同学」（举报人的网名）。作为检索策略它是
对的（真人就是这么搜的），但**「要不要围绕一个自然人做定向采集」不该由模型决定**——它躺在
建议列表里等人点，这正是闸门存在的理由。

## 七、配置

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `EVENT_KEYWORDS_ENABLED` | `true` | 关掉 ⇒ 只剩算术那一半（事件仍加权，但不生成新词） |
| `EVENT_KEYWORD_TOP_EVENTS` | `5` | 只给 priority 最高的 N 个事件调 LLM |
| `EVENT_KEYWORD_MAX` | `5` | 一个事件最多贡献几个生成词 |
| `EVENT_RECENCY_HALF_LIFE_DAYS` | `21` | 与事件看板**共用**（选题器和看板不许各用一套年龄） |

## 八、测试

- `backend/tests/test_keyword_event_signal.py`（18）——算术那一半：优先级、归一化、
  加项不贬值老三路、crawl_penalty 张力的三个分支、标签权重、卫生规则。**零 LLM、零 IO、`now` 注入。**
- `backend/tests/test_llm_keywords.py`（12）——LLM 那一半：注入假 proposer，验收/拒绝/
  逐事件降级/花钱闸门。**零网络、零 DB。**
- `backend/tests/test_keyword_suggestions.py`（21，其中 6 个新增）——adapter 端到端（SQLite）：
  只有 published 事件能左右计划、proposer 炸了照常工作、live vs resolved 的降权差异。
