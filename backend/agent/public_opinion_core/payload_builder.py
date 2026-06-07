"""Database payload builders for the portable public opinion Agent core.

The functions in this module build insert-ready dictionaries only. They do
not import ORM models, open database connections, or call backend APIs.
"""

from __future__ import annotations

import json
from typing import Any

from .schemas import AnalyzeResult, OpinionEvent, OpinionNote


def build_public_event_payloads(result: AnalyzeResult) -> list[dict[str, Any]]:
    """Convert analyzed events to public_events insert payloads."""

    payloads: list[dict[str, Any]] = []
    for index, event in enumerate(result.events):
        event_key = _event_temp_id(event, index)
        payloads.append(
            {
                "event_key": event_key,
                "title": _limit_text(event.title, 200),
                "summary": event.summary or event.agent_summary,
                "topic": event.category,
                "event_type": event.category,
                "sentiment": event.sentiment,
                "risk_level": event.risk_level,
                "risk_score": float(event.risk_score),
                "heat_score": float(event.heat_score),
                "confidence": _confidence(event),
                "source_count": int(event.source_count),
                "date_range_json": _json_dumps(
                    {
                        "first_seen_at": event.first_seen_at,
                        "last_seen_at": event.last_seen_at,
                    }
                ),
                "source_keywords_json": _json_dumps(event.source_keywords),
                "top_tags_json": _json_dumps(event.top_tags),
                "concerns_json": _json_dumps(event.concerns),
                "risk_reasons_json": _json_dumps(event.risk_reasons),
                "status": "draft",
                "reviewed_by": "",
                "reviewed_at": None,
                "review_comment": "",
            }
        )
    return payloads


def build_event_post_link_payloads(result: AnalyzeResult) -> list[dict[str, Any]]:
    """Convert representative notes to event_post_links insert payloads.

    event_id is unknown before public_events rows are inserted, so the payload
    carries event_temp_id. The backend should replace event_temp_id with the
    real public_events.id after inserting or upserting each event.
    """

    payloads: list[dict[str, Any]] = []
    for event_index, event in enumerate(result.events):
        event_temp_id = _event_temp_id(event, event_index)
        for rank, note in enumerate(event.representative_notes, start=1):
            if note.processed_post_id is None and note.raw_post_id is None:
                continue
            payloads.append(
                {
                    "event_temp_id": event_temp_id,
                    "event_id": None,
                    "processed_post_id": note.processed_post_id,
                    "raw_post_id": note.raw_post_id,
                    "rank": rank,
                    "role": "representative",
                }
            )
    return payloads


def build_agent_run_log_payload(result: AnalyzeResult) -> dict[str, Any]:
    """Convert one AnalyzeResult to an agent_run_logs insert payload."""

    run_log = result.run_log
    return {
        "agent_type": run_log.agent_type,
        "keyword": run_log.keyword,
        "input_count": int(run_log.input_count),
        "output_count": int(run_log.event_count),
        "input_summary": _json_dumps(
            {
                "keyword": result.request.keyword,
                "platforms": result.request.platforms,
                "limit": result.request.limit,
                "start_time": result.request.start_time,
                "end_time": result.request.end_time,
                "warnings": result.warnings,
                "adapted_count": run_log.extra.get("adapted_count"),
                "matched_count": run_log.extra.get("matched_count"),
            }
        ),
        "output_summary": _json_dumps(
            {
                "event_count": len(result.events),
                "event_keys": [_event_temp_id(event, index) for index, event in enumerate(result.events)],
                "top_events": [
                    {
                        "event_key": _event_temp_id(event, index),
                        "title": event.title,
                        "risk_level": event.risk_level,
                        "source_count": event.source_count,
                        "heat_score": event.heat_score,
                    }
                    for index, event in enumerate(result.events[:5])
                ],
            }
        ),
        "status": run_log.status,
        "error_message": run_log.error_message or "",
        "duration_ms": int(run_log.duration_ms),
        "created_by": str(run_log.extra.get("created_by") or "agent"),
        "started_at": run_log.started_at,
        "finished_at": run_log.finished_at,
    }


def _event_temp_id(event: OpinionEvent, index: int) -> str:
    if event.event_key:
        return _limit_text(event.event_key, 255)
    return f"event_temp_{index + 1}"


def _confidence(event: OpinionEvent) -> float:
    raw_confidence = event.extra.get("confidence") if isinstance(event.extra, dict) else None
    if isinstance(raw_confidence, int | float):
        return _clamp(float(raw_confidence), 0.0, 1.0)
    source_count = max(int(event.source_count), 0)
    return round(_clamp(0.5 + min(source_count, 10) * 0.05, 0.0, 0.95), 3)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def _json_default(value: Any) -> str:
    return str(value)


def _limit_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
