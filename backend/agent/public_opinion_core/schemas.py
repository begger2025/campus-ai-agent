"""Portable dataclasses for the Week2 public opinion Agent core.

These structures intentionally avoid ORM, database, FastAPI, and project
backend imports. They are the stable boundary between processed_posts rows,
Agent analysis logic, and database-ready payload builders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class OpinionNote:
    """Agent-internal representation of one processed public post."""

    note_id: str
    title: str
    content: str
    processed_post_id: int | None = None
    raw_post_id: int | None = None
    platform: str = ""
    author_name: str = ""
    publish_time: str = ""
    publish_date: str = ""
    url: str = ""
    raw_url: str = ""
    source_keyword: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    heat_score: float = 0.0
    # 平台内归一化排序分（0-100 百分位，来自 processed_posts.heat_rank）。
    # heat_score 跨平台不可比（xhs 中位 3924 / weibo 3），排序、选 top-N、加权重要性
    # 一律用 heat_rank；heat_score 只用于展示。0 表示该行还没归一化（老数据）。
    heat_rank: float = 0.0
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    risk_level: str = "low"
    risk_score: float = 0.0
    risk_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    # 高赞评论摘录：进情绪/风险分析文本与简报语料，不进聚类嵌入（口径见 normalizer）。
    top_comments: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OpinionEvent:
    """Agent-internal representation of one clustered public opinion event."""

    event_key: str
    title: str
    summary: str
    category: str
    risk_level: str
    sentiment: str
    heat_score: float
    source_count: int
    # 成员帖 heat_rank 之和（平台内百分位之和）。
    heat_rank: float = 0.0
    # 成员帖 ranking_score 之和（平台先验权重 × 平台内百分位，见 platform_weights）。
    # **事件之间排序用它**：既跨平台可比，又保留了各平台真实触达的差异。heat_score 留给展示。
    # 不落库——权重要能不改数据库就调，所以它只是排序时现算的派生量。
    ranking_score: float = 0.0
    risk_score: float = 0.0
    first_seen_at: str = ""
    last_seen_at: str = ""
    # ---- 时效性（第三根轴，见 recency.py）----
    # 事件的**代表时间**：成员帖发布时间的中位数（造事件时算好，是事实，落库）。
    event_time: str = ""
    # 相对于某个注入的 now 的年龄（天）。None = 没有任何可解析的时间戳（"不知道多老"，
    # 不等于"很老"）。**不落库**：它是 now 的函数，冻进数据库第二天就是错的。
    age_days: float | None = None
    # 时效权重 0.5 ** (age_days / half_life)，钳在 [min_weight, 1.0]。默认 1.0 = 未标注/不打折。
    recency_weight: float = 1.0
    # 成员帖的发布时间（ISO 串，升序）。**事实**（同 event_time），落库——读侧要拿它现算
    # "这件事还在不在长"（见 recency.growth_signal）。
    member_times: list[str] = field(default_factory=list)
    # ---- 生命周期（第四根轴，见 llm_lifecycle.py）----
    # 看板上真正显示、也真正进排序的那个状态：
    #   resolved（已了结）/ ongoing（悬而未决）/ escalating（持续发酵）/ not_applicable（非事件）。
    # "" = 未研判（LLM 关掉/失败/老数据）-> 因子 1.0 -> 排序退化回改造前。
    # **它是判断和测量的合成**：escalating = ongoing ∧ 算术判定仍在增长（effective_lifecycle）。
    # 因此 escalating **不落库**——它是 now 的函数，冻进数据库第二天就是错的（同 age_days）。
    lifecycle: str = ""
    # LLM 答的那一半：**有没有一件悬而未决的事**（resolved / ongoing / not_applicable）。
    # 模型不再被允许回答 escalating（那是测量，不是判断）。这一半是对内容的判断、不是 now 的
    # 函数，所以**落库**；读侧用它 + 成员帖时间重新合成 lifecycle。
    lifecycle_judgement: str = ""
    # 状态的人话理由（给管理员看的："凭什么这条 3 个月前的事还在前面"）。
    lifecycle_reason: str = ""
    # 增长的**证据**（算术算出来的，展示给管理员看"凭什么标持续发酵"）：
    # {"window_days", "total_notes", "recent_notes", "recent_share", "recent_rate",
    #  "baseline_rate", "growing"}。**不落库**（是 now 的函数），读侧现算。
    growth: dict[str, Any] = field(default_factory=dict)
    # 展示优先级 = severity_weight × recency_weight × lifecycle_weight，事件排序的第一排序键。
    priority_score: float = 0.0
    source_keywords: list[str] = field(default_factory=list)
    top_tags: list[dict[str, Any]] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    representative_notes: list[OpinionNote] = field(default_factory=list)
    agent_summary: str = ""
    trend: str = "new"
    heat_delta: float = 0.0
    previous_risk_level: str = ""
    risk_escalated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventSnapshot:
    """Memory record of one event from a previous Agent run."""

    event_key: str
    title: str = ""
    heat_score: float = 0.0
    risk_level: str = "low"
    risk_score: float = 0.0
    source_count: int = 0
    sentiment: str = "neutral"
    last_seen_at: str = ""
    # 语义聚类的簇中心向量，用于跨次运行事件对齐；规则聚类时为空。
    centroid: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemorySnapshot:
    """Memory of all events captured at the end of one Agent run."""

    captured_at: str = ""
    events: dict[str, EventSnapshot] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalyzeRequest:
    """Input contract for an Agent analysis run."""

    keyword: str = ""
    limit: int = 50
    platforms: list[str] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""

    def __post_init__(self) -> None:
        if self.limit < 1:
            self.limit = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventPayload:
    """Database-ready payload for public_events, without performing writes."""

    title: str
    summary: str
    category: str
    risk_level: str
    sentiment: str
    status: str = "draft"
    heat_score: float = 0.0
    source_count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    agent_summary: str = ""
    event_key: str = ""
    risk_score: float = 0.0
    concerns: list[str] = field(default_factory=list)
    risk_reasons: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventPostLinkPayload:
    """Database-ready payload for event_post_links, without performing writes."""

    event_temp_id: str
    processed_post_id: int | None
    raw_post_id: int | None = None
    relation_type: str = "representative"
    rank_score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentRunLogPayload:
    """Database-ready payload for agent_run_logs, without performing writes."""

    agent_type: str = "public_opinion"
    status: str = "success"
    input_count: int = 0
    event_count: int = 0
    keyword: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalyzeResult:
    """Output contract for one Agent analysis run."""

    request: AnalyzeRequest
    events: list[OpinionEvent]
    run_log: AgentRunLogPayload
    warnings: list[str] = field(default_factory=list)
    snapshot: MemorySnapshot | None = None
    visualization: dict[str, Any] = field(default_factory=dict)
    # 逐帖分析标注（含情绪/风险），供调用方把结果回写到持久层。
    notes: list[OpinionNote] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
