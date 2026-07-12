"""Portable public opinion Agent core package for Week2 work."""

from .adapter import processed_post_to_note, processed_posts_to_notes
from .clustering import classify_event, cluster_notes
from .memory import JsonMemoryStore, annotate_events_with_memory, build_snapshot
from .payload_builder import (
    build_agent_run_log_payload,
    build_event_post_link_payloads,
    build_public_event_payloads,
)
from .platform_weights import (
    DEFAULT_PLATFORM_WEIGHTS,
    note_ranking_score,
    platform_weight,
    platform_weights,
    ranking_score,
)
from .recency import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_MIN_WEIGHT,
    age_in_days,
    annotate_events_with_recency,
    event_reference_time,
    event_time_from_payload,
    priority_score,
    recency_config,
    recency_weight,
    severity_weight,
)
from .scoring import calculate_heat_score, score_note, score_notes
from .service import PublicOpinionAgentService
from .sentiment_risk import analyze_note_sentiment_and_risk, analyze_notes_sentiment_and_risk
from .visualization import (
    build_daily_trend_series,
    build_event_trend_overview,
    build_keyword_cloud,
    build_platform_distribution,
    build_risk_distribution,
    build_sentiment_distribution,
    build_visualization_payload,
)
from .schemas import (
    AgentRunLogPayload,
    AnalyzeRequest,
    AnalyzeResult,
    EventPayload,
    EventPostLinkPayload,
    EventSnapshot,
    MemorySnapshot,
    OpinionEvent,
    OpinionNote,
)

__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "DEFAULT_MIN_WEIGHT",
    "DEFAULT_PLATFORM_WEIGHTS",
    "AgentRunLogPayload",
    "AnalyzeRequest",
    "AnalyzeResult",
    "EventPayload",
    "EventPostLinkPayload",
    "EventSnapshot",
    "JsonMemoryStore",
    "MemorySnapshot",
    "OpinionEvent",
    "OpinionNote",
    "PublicOpinionAgentService",
    "age_in_days",
    "analyze_note_sentiment_and_risk",
    "analyze_notes_sentiment_and_risk",
    "annotate_events_with_memory",
    "annotate_events_with_recency",
    "build_agent_run_log_payload",
    "build_daily_trend_series",
    "build_event_post_link_payloads",
    "build_event_trend_overview",
    "build_keyword_cloud",
    "build_platform_distribution",
    "build_public_event_payloads",
    "build_risk_distribution",
    "build_sentiment_distribution",
    "build_snapshot",
    "build_visualization_payload",
    "calculate_heat_score",
    "classify_event",
    "cluster_notes",
    "event_reference_time",
    "event_time_from_payload",
    "note_ranking_score",
    "platform_weight",
    "platform_weights",
    "priority_score",
    "processed_post_to_note",
    "processed_posts_to_notes",
    "ranking_score",
    "recency_config",
    "recency_weight",
    "score_note",
    "score_notes",
    "severity_weight",
]
