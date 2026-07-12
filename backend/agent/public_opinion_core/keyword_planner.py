"""Crawl keyword recommendation planner（智能选题核心算法）.

纯函数、零 IO、零新依赖。**五路**客观信号融合为一个可解释分数：
  A demand    —— 用户提问频率，3 天半衰期衰减
  B gap       —— 提问后站内检索命中不足的话题加权补给
  C heat      —— 已爬内容在小红书侧的互动热度延续，7 天半衰期
  D discovery —— 笔记标签里冒头、但从未作为关键词爬过的新话题
  E event     —— **舆情事件流水线**（本轮新增；见下）

score(kw) = (0.5·demand_norm + 0.3·min(2·demand_norm, 1) + 0.2·heat_norm) × crawl_penalty × 10
          + 0.3·event_norm × event_penalty × 10
crawl_penalty：14 天内爬过 ×0.3；命中贫瘠集合（爬过但零相关入库）×0.1（强降权，替代而非叠乘）

---------------------------------------------------------------------------
**E：选题器从来没听说过"事件"**（2026-07-12 在线上库实测的缺陷）

    grep -c event keyword_planner.py keyword_suggestion_adapter.py  ->  0 和 0

候选池只有两个来源：`ChatQueryLog`（用户问过什么）和 `ProcessedPost` 标签（已经爬回来什么）。
于是同一个系统，一边把「中大杰青实名举报」判成 high(91) / 悬而未决 / 全库第一优先级，
一边让选题器继续推荐**「食堂」**。左手不知道右手在干什么。

**这一路是算术，不是智能。** 严重性（LLM 早就判完并落库了）、生命周期（同上）、时效性
（`0.5**(age/21)`）——三个数**都已经算好、都已经在 `public_events` 里**。把它们接进 planner
是**接线**：

    event_priority = severity_weight(risk) × recency_weight(age) × lifecycle_weight(lifecycle)
                   = recency.priority_score(...)          ← 一个字都不重新发明
    event_norm     = event_priority / max(event_priority)  ← 与 demand_norm/heat_norm 同一个套路

**为什么是"第四个加项"而不是把老三路重新归一化。** 把权重改成 0.35/0.21/0.14/0.30（和仍为 1）
看起来更漂亮，代价是：**一个一个事件都没有的部署，每个候选词的分数会凭空掉 30%**——这一路
明明什么都没说，却改写了别人的答案。所以取加项：`events=[]` 时 `event_norm` 恒为 0，分数
**逐位**回到改造前（`DegradationTest` 钉死）。代价是分数上界从 10 变成 10×(1+0.3)=**13.0**，
如实写在这里，也如实写进文档——一个诚实的量纲变化，好过一次静默的全局贬值。

**W_EVENT = 0.3 = W_GAP。** 排序读作一句人话：**用户明确问过 (0.5) > 编辑部认定的当务之急
(0.3) = 站内供给不足 (0.3) > 已有内容的热度 (0.2)**。事件信号本质上就是一种 gap——"这件事
正在发生，而我们的语料里没有它"——所以和 gap 同权；但它是**推断**出来的，而一个真实用户
敲下的问题是**事实**，所以压不过 demand。

**crawl_penalty 的张力（真问题，必须选边）。** 「昨天刚爬过」该不该压住「这是头号未决丑闻」？
爬取降权问的是：**我们是不是已经有这份数据了？**

  - 事件 `ongoing` / `escalating`（悬而未决、仍在发酵）：**新帖还在来**（`growth` 是算术测出来的）。
    "昨天爬过"只说明我们有了**昨天以前**的存量，对今天新增的证据它什么都没说。
    -> 事件项**不吃**常规爬取降权（`event_penalty = 1.0`）。
  - 事件 `resolved` / `not_applicable` / 未研判：不会再有新证据了，"昨天爬过"就是真的
    "我们已经有了" -> 事件项**照常**吃 ×0.3。
  - **贫瘠词（×0.1）例外中的例外：不豁免。** 贫瘠是关于**这个词**的证据——我们拿它搜过，
    什么都没捞回来。事件再急，一个搜不到东西的词也搜不到东西。豁免它等于让"火烧眉毛"
    变成"可以无视实测结果"的通行证。

注意 penalty 因此**分别**作用在两个加项上（老三路是"存量的供给"，事件项是"新证据的供给"，
两者的供给事实不同）——这是本轮唯一的结构性改动。

设计文档：主项目 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md
        + docs/keyword-event-ablation.md（消融）
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .recency import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_MIN_WEIGHT,
    age_in_days,
    priority_score,
    recency_weight,
)


HALF_LIFE_ASK_DAYS = 3.0
HALF_LIFE_CONTENT_DAYS = 7.0
CRAWL_PENALTY = 0.3
BARREN_PENALTY = 0.1
CRAWL_PENALTY_WINDOW_DAYS = 14
GAP_HIT_THRESHOLD = 3
GAP_BOOST = 2.0
W_ASK = 0.5
W_GAP = 0.3
W_HEAT = 0.2
# 事件信号的权重。**加项，不参与老三路的归一化**（理由见模块顶部）。
W_EVENT = 0.3
SCORE_SCALE = 10.0
ASK_WINDOW_DAYS = 7
MAX_KEYWORD_LEN = 12

# 仍会产生新证据的事件状态：爬取降权对它们**不成立**（见模块顶部 crawl_penalty 的张力）。
LIVE_LIFECYCLES = frozenset({"ongoing", "escalating"})

SCHOOL_PREFIXES = ("中山大学", "中大")
# 太宽泛、不适合作为爬取关键词的通用词（含学校名本身与营销标签）。
GENERIC_BLACKLIST = frozenset(
    {
        "中山大学", "中大", "大学", "校园", "学校", "大学生", "学生",
        "大学生活", "校园生活", "日常", "分享", "生活", "推荐", "攻略",
        "vlog", "打卡", "笔记", "干货", "好物",
        "探店", "美食", "穿搭", "ootd", "旅游", "旅行", "景点", "拍照",
        "约拍", "优惠", "团购", "种草", "测评", "集美", "姐妹",
    }
)

# emoji / 图形符号区段（保守清单：不含中文、英文、数字、常规标点）。
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),  # SMP 图形区：表情、交通、麻将、补充符号等
    (0x2600, 0x27BF),    # 杂项符号与装饰符号（☀✅✈ 等）
    (0x2B00, 0x2BFF),    # 杂项符号和箭头（⭐⬆ 等）
    (0xFE00, 0xFE0F),    # 变体选择符（emoji 样式后缀）
    (0x200D, 0x200D),    # 零宽连接符（组合 emoji）
)


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)


def _strip_edge_punct(word: str) -> str:
    """剥离首尾的标点符号（Unicode P 类）与空白，词内字符不动。"""

    start, end = 0, len(word)
    while start < end and (unicodedata.category(word[start]).startswith("P") or word[start].isspace()):
        start += 1
    while end > start and (unicodedata.category(word[end - 1]).startswith("P") or word[end - 1].isspace()):
        end -= 1
    return word[start:end]


@dataclass(slots=True)
class QueryRecord:
    """一次用户提问（来自 chat_query_log）。"""

    keyword: str
    asked_at: datetime
    hit_count: int = 0


@dataclass(slots=True)
class ContentStat:
    """一个词在一条已爬内容上的统计（C 用 source_keyword，D 用笔记标签）。"""

    keyword: str
    engagement: int
    published_at: datetime


@dataclass(slots=True)
class EventRecord:
    """一个已发布的舆情事件，喂给选题器的**只读投影**（由 adapter 从 public_events 读出来）。

    这里面**没有一个字段需要重新计算**：`risk_level` 是 LLM 早就判完落库的严重性，
    `lifecycle` 是它判完落库的"这件事完了没有"，`event_time` 是成员帖发布时间的中位数。
    planner 拿它们做的唯一一件事是把三个现成的权重乘起来（`event_priority`）。

    keywords           —— 事件**已经带着**的词（top_tags / source_keywords）。字面已存在。
    keyword_weights    —— 每个标签**有多像这件事**（0-1，缺省 1.0）。见下。
    generated_keywords —— **LLM 从事件正文生成**的检索词（见 llm_keywords.py）。
                          字面**不存在于**任何标题/标签/提问——这正是规则生不出来的那一半。
    texts              —— 代表帖正文，只给 LLM 读；算术这一路一个字都不看。

    **keyword_weights 为什么必须存在**（消融第一版实测打的脸）：头号事件「中大杰青实名举报」
    的 top_tags 是 学术(3) / 热点(1) / 新闻(1) / 社会新闻(1) / 学术论文(1) / 医学(1) /
    **上海(1)** / **广州(1)**。若一个事件的所有标签共享同一个 `event_norm`，那么
    **「上海」「广州」「新闻」会和「学术不端」并列 3.00 分**，把一堆搜出来全是噪音的词顶上首屏。

    修法是**算术，不是往黑名单里再塞几个词**：`top_tags_json` 里本来就存着 count（几条成员帖
    带这个标签）。3 条帖子都带「学术」、只有 1 条带「上海」——**权重 = count / max_count**。
    往黑名单里加「上海」「广州」是治不了的（下一个事件是「深圳」「珠海」，穷举不完，
    同 llm_risk 顶部那个论证）；数标签出现在几条帖子上，是**测量**。

    LLM 生成词**不吃这个折扣**（权重恒 1.0）：它是被**当作检索词提出来的**，不是被顺手打上的
    标签——这正是两路的区别。
    """

    event_id: str
    title: str
    risk_level: str = "low"
    lifecycle: str = ""
    event_time: datetime | None = None
    keywords: list[str] = field(default_factory=list)
    keyword_weights: dict[str, float] = field(default_factory=dict)
    generated_keywords: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def event_priority(
    event: EventRecord,
    now: datetime,
    *,
    half_life_days: float | None = None,
) -> float:
    """事件的展示优先级 = 严重性 × 时效 × 生命周期 —— **直接复用 recency.priority_score**。

    `half_life_days` 显式传入（缺省 21 天），**不读 .env**：planner 必须是确定性的，
    否则单测不可重复、消融不可复现。部署侧要用 `.env` 的半衰期，由 adapter 传进来。
    """

    half_life = DEFAULT_HALF_LIFE_DAYS if half_life_days is None else float(half_life_days)
    age = age_in_days(event.event_time, now)
    weight = recency_weight(age, half_life_days=half_life, min_weight=DEFAULT_MIN_WEIGHT)
    return priority_score(event.risk_level, weight, event.lifecycle)


@dataclass(slots=True)
class KeywordSuggestion:
    keyword: str
    score: float
    signals: list[str] = field(default_factory=list)
    ask_count_7d: int = 0
    last_asked_at: datetime | None = None
    last_hit_count: int | None = None
    last_crawled_at: datetime | None = None
    # 出处（provenance）：这个词**凭什么**被推荐。事件来源必须带上事件 id 和标题，
    # 否则管理员看到「学术不端」时无从判断它是哪来的。
    #   [{"event_id": "20", "title": "中大杰青实名举报", "risk_level": "high",
    #     "lifecycle": "ongoing", "origin": "event_llm" | "event_tag"}]
    event_refs: list[dict[str, str]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("last_asked_at", "last_crawled_at"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        data["score"] = round(self.score, 1)
        return data


def normalize_keyword(keyword: str) -> str:
    """归一化候选词：删 emoji、剥首尾标点、剥学校前缀、过滤黑名单/单字/纯数字/超长。返回 "" 表示丢弃。"""

    word = (keyword or "").strip().lower()
    word = "".join(char for char in word if not _is_emoji(char))
    # 先清掉首尾 emoji/标点再剥前缀，否则"🔥中山大学食堂"这类词会让 startswith 失配
    word = _strip_edge_punct(word)
    for prefix in SCHOOL_PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix):
            word = word[len(prefix):]
            break
    # 剥前缀可能暴露新的首部标点（如"中山大学-食堂"→"-食堂"），需再剥一次
    word = _strip_edge_punct(word)
    if len(word) < 2 or word in GENERIC_BLACKLIST or word.isdigit():
        return ""
    if len(word) > MAX_KEYWORD_LEN:
        return ""
    return word


@dataclass(slots=True)
class _Candidate:
    """打分中间态：一个候选词累计的各路信号原始值。"""

    demand: float = 0.0
    ask_total: int = 0
    ask_count_7d: int = 0
    last_asked_at: datetime | None = None
    last_hit_count: int | None = None
    heat_raw: float = 0.0
    content_count: int = 0
    last_crawled_at: datetime | None = None
    # 事件信号：**取 max，不求和**。一个词挂在三个瞌睡事件上，加起来也不许压过头号丑闻——
    # 这一路问的是"这个词属于的**最急**的那件事有多急"，不是"它被多少件事提过"。
    event_priority: float = 0.0
    top_event: EventRecord | None = None
    event_refs: list[dict[str, str]] = field(default_factory=list)


def _decay(age_days: float, half_life_days: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / half_life_days)


def _age_days(now: datetime, moment: datetime) -> float:
    return (now - moment).total_seconds() / 86400.0


LIFECYCLE_LABELS = {
    "escalating": "持续发酵",
    "ongoing": "悬而未决",
    "resolved": "已了结",
    "not_applicable": "非事件",
    "": "未研判",
}


def _event_reason(cand: _Candidate, *, live: bool) -> str:
    """事件那一路的理由：管理员必须一眼看见「学术不端」是从哪件事上来的。"""

    event = cand.top_event
    if event is None:
        return ""
    origins = {ref["origin"] for ref in cand.event_refs if ref["event_id"] == event.event_id}
    how = "LLM 据该事件正文生成" if "event_llm" in origins else "该事件的内容标签"
    text = (
        f"来自{event.risk_level}风险事件「{event.title}」"
        f"（{LIFECYCLE_LABELS.get(event.lifecycle, event.lifecycle or '未研判')}，{how}）"
    )
    if live:
        # 这句话是给管理员解释"为什么刚爬过还推荐它"的——不解释就像个 bug。
        text += "，事件仍在发酵、新证据仍在产生（爬取降权对事件项不适用）"
    return text


def _build_reason(
    cand: _Candidate,
    *,
    now: datetime,
    gap: bool,
    penalized: bool,
    barren: bool = False,
    live: bool = False,
) -> str:
    parts: list[str] = []
    if cand.ask_total:
        if cand.ask_count_7d:
            parts.append(f"近7天被问{cand.ask_count_7d}次")
        else:
            parts.append("近期有用户提问")
        if gap:
            parts.append(f"最近一次命中{cand.last_hit_count or 0}条站内数据")
    if cand.heat_raw > 0:
        label = "相关" if cand.last_crawled_at else "带此标签"
        parts.append(f"近期有{cand.content_count}条已爬内容{label}、互动量热")
    if (event_part := _event_reason(cand, live=live)):
        parts.append(event_part)
    if cand.last_crawled_at is not None:
        days = max(int(_age_days(now, cand.last_crawled_at)), 0)
        if barren:
            parts.append(f"{days}天前爬过但无相关内容（已强降权）")
        else:
            parts.append(f"{days}天前爬过（已降权）" if penalized else f"{days}天前爬过")
    elif barren:
        # 贫瘠标记来自爬取历史，即使内容表倒推不出爬取时间也如实说明
        parts.append("近期爬过但无相关内容（已强降权）")
    else:
        parts.append("从未爬取过" if cand.ask_total else "从未作为关键词爬取")
    return "，".join(parts)


def _build_alias_map(keywords: set[str]) -> dict[str, str]:
    """短词并入唯一包含它的长词（"空调"→"宿舍空调"）；多个包含者视为歧义，不合并。"""

    alias: dict[str, str] = {}
    for word in sorted(keywords, key=len):
        containers = [other for other in keywords if other != word and word in other]
        if len(containers) == 1:
            alias[word] = containers[0]
    return alias


def plan_keywords(
    queries: list[QueryRecord],
    content_stats: list[ContentStat],
    crawled_at_by_keyword: dict[str, datetime],
    now: datetime,
    top_n: int = 10,
    barren_keywords: set[str] | None = None,
    events: list[EventRecord] | None = None,
    event_half_life_days: float | None = None,
) -> list[KeywordSuggestion]:
    """五信号融合打分，返回按分数降序的 Top-N 推荐。

    barren_keywords：近期爬过但零相关入库的贫瘠词（原始形态），命中者强降权至 BARREN_PENALTY。
    events：已发布的舆情事件（**算术**信号，见模块顶部）。`None` / `[]` -> 这一路恒等于 0，
            分数**逐位**退化回改造前——这是降级保证，不是巧合。
    """

    normalized_queries = [
        (word, query) for query in queries if (word := normalize_keyword(query.keyword))
    ]
    normalized_contents = [
        (word, stat) for stat in content_stats if (word := normalize_keyword(stat.keyword))
    ]
    normalized_crawled: dict[str, datetime] = {}
    for raw_keyword, crawled_at in crawled_at_by_keyword.items():
        word = normalize_keyword(raw_keyword)
        if word and (word not in normalized_crawled or crawled_at > normalized_crawled[word]):
            normalized_crawled[word] = crawled_at

    # 事件送来的词走**同一套**卫生规则：LLM 说「校园生活」，和用户说「校园生活」一样被拒。
    # （origin 记在这里，因为归一化会把「中山大学 学术不端」变成「学术不端」，事后认不出来源。）
    normalized_events: list[tuple[str, EventRecord, str, float]] = []
    for event in events or []:
        for origin, raw_words in (
            ("event_tag", event.keywords),
            ("event_llm", event.generated_keywords),
        ):
            for raw in raw_words:
                if not (word := normalize_keyword(raw)):
                    continue
                # 标签按"几条成员帖带它"打折（见 EventRecord 的注释）；生成词恒 1.0。
                weight = (
                    1.0 if origin == "event_llm"
                    else float(event.keyword_weights.get(raw, 1.0))
                )
                normalized_events.append((word, event, origin, max(min(weight, 1.0), 0.0)))

    all_words = (
        {w for w, _ in normalized_queries}
        | {w for w, _ in normalized_contents}
        | {w for w, _, _, _ in normalized_events}
    )
    alias = _build_alias_map(all_words)

    def canon(word: str) -> str:
        return alias.get(word, word)

    # 贫瘠词与 crawled_at_by_keyword 同口径对账：归一化（丢弃为空者）后再并入合并词
    barren_set = {
        canon(word) for raw in (barren_keywords or set()) if (word := normalize_keyword(raw))
    }

    candidates: dict[str, _Candidate] = {}

    for word, query in normalized_queries:
        cand = candidates.setdefault(canon(word), _Candidate())
        age = _age_days(now, query.asked_at)
        cand.demand += _decay(age, HALF_LIFE_ASK_DAYS)
        cand.ask_total += 1
        if age <= ASK_WINDOW_DAYS:
            cand.ask_count_7d += 1
        if cand.last_asked_at is None or query.asked_at > cand.last_asked_at:
            cand.last_asked_at = query.asked_at
            cand.last_hit_count = query.hit_count

    for word, stat in normalized_contents:
        cand = candidates.setdefault(canon(word), _Candidate())
        age = _age_days(now, stat.published_at)
        cand.heat_raw += math.log10(1 + max(stat.engagement, 0)) * _decay(age, HALF_LIFE_CONTENT_DAYS)
        cand.content_count += 1

    # E：事件流水线。priority 是**现成的三个权重相乘**（severity × recency × lifecycle），
    # 一个数都不重新发明；一个词挂多个事件时取 **max**（最急的那件事），不求和。
    for word, event, origin, weight in normalized_events:
        cand = candidates.setdefault(canon(word), _Candidate())
        priority = event_priority(event, now, half_life_days=event_half_life_days) * weight
        ref = {
            "event_id": str(event.event_id),
            "title": event.title,
            "risk_level": event.risk_level,
            "lifecycle": event.lifecycle,
            "origin": origin,
        }
        if ref not in cand.event_refs:
            cand.event_refs.append(ref)
        if priority > cand.event_priority:
            cand.event_priority = priority
            cand.top_event = event

    for word, crawled_at in normalized_crawled.items():
        word = canon(word)
        if word not in candidates:
            continue
        cand = candidates[word]
        if cand.last_crawled_at is None or crawled_at > cand.last_crawled_at:
            cand.last_crawled_at = crawled_at

    max_demand = max((c.demand for c in candidates.values()), default=0.0)
    max_heat = max((c.heat_raw for c in candidates.values()), default=0.0)
    max_event = max((c.event_priority for c in candidates.values()), default=0.0)

    suggestions: list[KeywordSuggestion] = []
    for word, cand in candidates.items():
        demand_norm = cand.demand / max_demand if max_demand else 0.0
        heat_norm = cand.heat_raw / max_heat if max_heat else 0.0
        event_norm = cand.event_priority / max_event if max_event else 0.0
        gap = cand.ask_total > 0 and (cand.last_hit_count or 0) < GAP_HIT_THRESHOLD
        gap_norm = min(demand_norm * GAP_BOOST, 1.0) if gap else 0.0
        penalized = (
            cand.last_crawled_at is not None
            and _age_days(now, cand.last_crawled_at) < CRAWL_PENALTY_WINDOW_DAYS
        )
        barren = word in barren_set
        # 贫瘠词强降权替代常规降权（不叠乘）
        penalty = BARREN_PENALTY if barren else (CRAWL_PENALTY if penalized else 1.0)
        # 事件项的供给事实**和老三路不同**（见模块顶部）：悬而未决/持续发酵的事件新证据还在来，
        # "昨天爬过"对它们不成立 -> 不吃常规降权。但**贫瘠不豁免**：搜不到就是搜不到。
        live = (
            cand.top_event is not None
            and str(cand.top_event.lifecycle or "").strip().lower() in LIVE_LIFECYCLES
        )
        event_penalty = BARREN_PENALTY if barren else (1.0 if live else penalty)
        score = (
            (W_ASK * demand_norm + W_GAP * gap_norm + W_HEAT * heat_norm) * penalty * SCORE_SCALE
            + W_EVENT * event_norm * event_penalty * SCORE_SCALE
        )
        if score <= 0:
            continue
        signals: list[str] = []
        if cand.ask_total:
            signals.append("demand")
        if gap:
            signals.append("gap")
        if cand.heat_raw > 0:
            signals.append("heat" if cand.last_crawled_at else "discovery")
        origins = {ref["origin"] for ref in cand.event_refs}
        if "event_tag" in origins:
            signals.append("event")
        if "event_llm" in origins:
            signals.append("event_llm")
        suggestions.append(
            KeywordSuggestion(
                keyword=word,
                score=score,
                signals=signals,
                ask_count_7d=cand.ask_count_7d,
                last_asked_at=cand.last_asked_at,
                last_hit_count=cand.last_hit_count,
                last_crawled_at=cand.last_crawled_at,
                event_refs=list(cand.event_refs),
                reason=_build_reason(
                    cand, now=now, gap=gap, penalized=penalized, barren=barren, live=live
                ),
            )
        )

    suggestions.sort(key=lambda s: (-s.score, s.keyword))
    return suggestions[:top_n]
