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
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    risk_level: str = "low"
    risk_score: float = 0.0
    risk_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
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
    risk_score: float = 0.0
    first_seen_at: str = ""
    last_seen_at: str = ""
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
