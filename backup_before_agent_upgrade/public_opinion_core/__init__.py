"""Portable public opinion Agent core package for Week2 work."""

from .adapter import processed_post_to_note, processed_posts_to_notes
from .clustering import classify_event, cluster_notes
from .payload_builder import (
    build_agent_run_log_payload,
    build_event_post_link_payloads,
    build_public_event_payloads,
)
from .scoring import calculate_heat_score, score_note, score_notes
from .service import PublicOpinionAgentService
from .sentiment_risk import analyze_note_sentiment_and_risk, analyze_notes_sentiment_and_risk
from .schemas import (
    AgentRunLogPayload,
    AnalyzeRequest,
    AnalyzeResult,
    EventPayload,
    EventPostLinkPayload,
    OpinionEvent,
    OpinionNote,
)

__all__ = [
    "AgentRunLogPayload",
    "AnalyzeRequest",
    "AnalyzeResult",
    "EventPayload",
    "EventPostLinkPayload",
    "OpinionEvent",
    "OpinionNote",
    "PublicOpinionAgentService",
    "analyze_note_sentiment_and_risk",
    "analyze_notes_sentiment_and_risk",
    "build_agent_run_log_payload",
    "build_event_post_link_payloads",
    "build_public_event_payloads",
    "calculate_heat_score",
    "classify_event",
    "cluster_notes",
    "processed_post_to_note",
    "processed_posts_to_notes",
    "score_note",
    "score_notes",
]
