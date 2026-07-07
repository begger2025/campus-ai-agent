"""Adapter between processed_posts and the portable public opinion Agent core."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.admin_models import AgentRunLog
from backend.agent.public_opinion_core import (
    AnalyzeRequest,
    OpinionNote,
    PublicOpinionAgentService,
    build_agent_run_log_payload,
    build_event_post_link_payloads,
    build_public_event_payloads,
    processed_posts_to_notes,
)
from backend.models import EventPostLink, ProcessedPost, PublicEvent


REVIEW_LOCKED_STATUSES = {"published", "rejected", "archived"}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[str] = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _datetime_to_text(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def processed_post_to_agent_row(post: ProcessedPost) -> dict[str, Any]:
    """Convert one ProcessedPost ORM row to the Agent's processed-post mapping."""

    return {
        "id": post.id,
        "processed_post_id": post.id,
        "raw_post_id": post.raw_post_id,
        "platform": post.platform,
        "note_id": post.note_id,
        "title": post.title,
        "content": post.content,
        "source_keyword": post.source_keyword,
        "publish_date": post.publish_date,
        "publish_time": post.publish_time_raw or _datetime_to_text(post.publish_time),
        "author_name": post.author_name or post.author,
        "author": post.author_name or post.author,
        "keywords": _json_list(post.tags_json),
        "url": post.note_url,
        "note_url": post.note_url,
        "raw_url": post.raw_note_url,
        "raw_note_url": post.raw_note_url,
        "like_count": post.like_count,
        "collect_count": post.collect_count,
        "comment_count": post.comment_count,
        "share_count": post.share_count,
        "sentiment": post.sentiment,
        "risk_level": post.risk_level,
    }


def query_agent_rows(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Load processed_posts rows as dictionaries accepted by the Agent core."""

    query = db.query(ProcessedPost)
    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                ProcessedPost.title.like(like),
                ProcessedPost.content.like(like),
                ProcessedPost.source_keyword.like(like),
                ProcessedPost.author_name.like(like),
                ProcessedPost.tags_json.like(like),
            )
        )

    clean_platforms = [platform.strip() for platform in platforms or [] if platform.strip()]
    if clean_platforms:
        query = query.filter(ProcessedPost.platform.in_(clean_platforms))

    rows = query.order_by(ProcessedPost.id.desc()).limit(max(limit, 1)).all()
    return [processed_post_to_agent_row(row) for row in rows]


def load_opinion_notes_from_db(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
) -> list[OpinionNote]:
    """Load processed_posts and convert them to portable OpinionNote objects."""

    rows = query_agent_rows(db, keyword=keyword, platforms=platforms, limit=limit)
    return processed_posts_to_notes(rows)


def upsert_public_events(
    db: Session,
    event_payloads: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, str]]:
    """Insert or update public_events and return event ids/statuses by event_key."""

    event_id_by_temp_id: dict[str, int] = {}
    event_status_by_temp_id: dict[str, str] = {}
    review_fields = {"reviewed_by", "reviewed_at", "review_comment"}

    for payload in event_payloads:
        event_key = str(payload.get("event_key") or "").strip()
        event = db.query(PublicEvent).filter(PublicEvent.event_key == event_key).first()

        if event is None:
            event = PublicEvent(**payload)
            db.add(event)
        else:
            old_status = event.status
            old_reviewed_by = event.reviewed_by
            old_reviewed_at = event.reviewed_at
            old_review_comment = event.review_comment
            for key, value in payload.items():
                if key in review_fields:
                    continue
                if hasattr(event, key):
                    setattr(event, key, value)
            if old_status in REVIEW_LOCKED_STATUSES:
                event.status = old_status
                event.reviewed_by = old_reviewed_by
                event.reviewed_at = old_reviewed_at
                event.review_comment = old_review_comment

        db.flush()
        event_id_by_temp_id[event_key] = event.id
        event_status_by_temp_id[event_key] = event.status

    return event_id_by_temp_id, event_status_by_temp_id


def replace_event_post_links(
    db: Session,
    link_payloads: list[dict[str, Any]],
    event_id_by_temp_id: dict[str, int],
) -> None:
    """Replace representative post links for the events touched by this run."""

    event_ids = list(event_id_by_temp_id.values())
    if event_ids:
        db.query(EventPostLink).filter(EventPostLink.event_id.in_(event_ids)).delete(
            synchronize_session=False
        )

    for payload in link_payloads:
        event_temp_id = str(payload.pop("event_temp_id", "") or "")
        event_id = event_id_by_temp_id.get(event_temp_id)
        if event_id is None:
            continue
        payload["event_id"] = event_id
        db.add(EventPostLink(**payload))
    db.flush()


def insert_agent_run_log(db: Session, payload: dict[str, Any]) -> AgentRunLog:
    row = AgentRunLog(
        agent_type=payload.get("agent_type", "public_opinion"),
        keyword=payload.get("keyword", ""),
        input_count=int(payload.get("input_count") or 0),
        output_count=int(payload.get("output_count") or 0),
        input_summary=payload.get("input_summary", ""),
        output_summary=payload.get("output_summary", ""),
        status=payload.get("status", "success"),
        error_message=payload.get("error_message", ""),
        duration_ms=int(payload.get("duration_ms") or 0),
        created_by=payload.get("created_by", ""),
        started_at=_parse_datetime(payload.get("started_at")) or datetime.utcnow(),
        finished_at=_parse_datetime(payload.get("finished_at")),
    )
    db.add(row)
    db.flush()
    return row


def insert_failed_agent_run_log(
    db: Session,
    *,
    keyword: str,
    error_message: str,
    created_by: str = "system",
) -> AgentRunLog:
    now = datetime.utcnow()
    row = AgentRunLog(
        agent_type="public_opinion",
        keyword=keyword or "",
        input_count=0,
        output_count=0,
        input_summary="{}",
        output_summary="{}",
        status="failed",
        error_message=error_message,
        duration_ms=0,
        created_by=created_by,
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()
    return row


def run_public_opinion_analysis(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
    start_time: str = "",
    end_time: str = "",
    persist: bool = True,
    created_by: str = "system",
) -> dict[str, Any]:
    """Run the public opinion Agent and optionally persist its payloads."""

    rows = query_agent_rows(db, keyword=keyword, platforms=platforms, limit=limit)
    request = AnalyzeRequest(
        keyword=keyword or "",
        limit=max(limit, 1),
        platforms=platforms or [],
        start_time=start_time or "",
        end_time=end_time or "",
    )
    result = PublicOpinionAgentService().analyze_from_rows(rows, request)

    event_payloads = build_public_event_payloads(result)
    link_payloads = build_event_post_link_payloads(result)
    run_log_payload = build_agent_run_log_payload(result)
    run_log_payload["created_by"] = created_by

    event_id_by_temp_id: dict[str, int] = {}
    event_status_by_temp_id: dict[str, str] = {}
    run_log_id = None

    if persist:
        event_id_by_temp_id, event_status_by_temp_id = upsert_public_events(db, event_payloads)
        replace_event_post_links(db, link_payloads, event_id_by_temp_id)
        run_log = insert_agent_run_log(db, run_log_payload)
        run_log_id = run_log.id

    events = []
    for event in result.events:
        status = event_status_by_temp_id.get(event.event_key, "draft")
        events.append(
            {
                "id": event_id_by_temp_id.get(event.event_key),
                "event_key": event.event_key,
                "title": event.title,
                "summary": event.summary,
                "topic": event.category,
                "event_type": event.category,
                "sentiment": event.sentiment,
                "risk_level": event.risk_level,
                "risk_score": event.risk_score,
                "heat_score": event.heat_score,
                "source_count": event.source_count,
                "status": status,
            }
        )

    return {
        "status": result.run_log.status,
        "input_count": result.run_log.input_count,
        "event_count": len(result.events),
        "warnings": result.warnings,
        "events": events,
        "payload_counts": {
            "public_events": len(event_payloads),
            "event_post_links": len(link_payloads),
            "agent_run_logs": 1,
        },
        "run_log_id": run_log_id,
        "payload_preview": None
        if persist
        else {
            "public_events": event_payloads,
            "event_post_links": link_payloads,
            "agent_run_logs": run_log_payload,
        },
    }
