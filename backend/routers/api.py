import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.database import DATABASE_URL, get_db
from backend.models import EventPostLink, ProcessedPost, PublicEvent, RawPost
from backend.schemas import PingData, PostItem, PostListData, ok

router = APIRouter(tags=["api"])


def _database_name() -> str:
    try:
        return make_url(DATABASE_URL).database or ""
    except Exception:
        return ""


def _risk_level(row: PublicEvent) -> str:
    if row.risk_level:
        return row.risk_level
    score = row.heat_score or 0
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _risk_label(level: str) -> str:
    return {"high": "高风险", "medium": "中风险", "low": "低风险"}.get(level, level)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def _json_value(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _normalize_platform(platform: str | None) -> str:
    text = (platform or "").strip()
    lower = text.lower()
    if "weibo" in lower or "微博" in text:
        return "weibo"
    if "xhs" in lower or "小红书" in text:
        return "xhs"
    if "tieba" in lower or "贴吧" in text:
        return "tieba"
    return lower or text


def _representative_post_item(link: EventPostLink) -> dict:
    processed = link.processed_post
    raw = link.raw_post
    platform = ""
    title = ""
    content = ""
    author = ""
    publish_time = None
    url = ""
    raw_url = ""
    counts = {
        "like_count": 0,
        "collect_count": 0,
        "comment_count": 0,
        "share_count": 0,
    }

    if processed is not None:
        platform = processed.platform
        title = processed.title
        content = processed.content
        author = processed.author_name or processed.author
        publish_time = processed.publish_time
        url = processed.note_url
        raw_url = processed.raw_note_url
        counts = {
            "like_count": processed.like_count or 0,
            "collect_count": processed.collect_count or 0,
            "comment_count": processed.comment_count or 0,
            "share_count": processed.share_count or 0,
        }
    elif raw is not None:
        platform = raw.platform
        title = raw.title
        content = raw.content
        author = raw.author
        publish_time = raw.publish_time
        url = raw.url
        raw_url = raw.raw_url
        counts = {
            "like_count": raw.like_count or 0,
            "collect_count": raw.collect_count or 0,
            "comment_count": raw.comment_count or 0,
            "share_count": raw.share_count or 0,
        }

    return {
        "rank": link.rank,
        "role": link.role,
        "processed_post_id": link.processed_post_id,
        "raw_post_id": link.raw_post_id,
        "platform": _normalize_platform(platform),
        "title": title,
        "content": content,
        "author": author,
        "publish_time": _format_datetime(publish_time),
        "url": url,
        "raw_url": raw_url,
        **counts,
    }


def _representative_posts(
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
) -> list[dict]:
    posts = [_representative_post_item(link) for link in sorted(links, key=lambda item: item.rank)]
    if posts or fallback_processed is None:
        return posts
    return [
        {
            "rank": 1,
            "role": "source",
            "processed_post_id": fallback_processed.id,
            "raw_post_id": fallback_processed.raw_post_id,
            "platform": _normalize_platform(fallback_processed.platform),
            "title": fallback_processed.title,
            "content": fallback_processed.content,
            "author": fallback_processed.author_name or fallback_processed.author,
            "publish_time": _format_datetime(fallback_processed.publish_time),
            "url": fallback_processed.note_url,
            "raw_url": fallback_processed.raw_note_url,
            "like_count": fallback_processed.like_count or 0,
            "collect_count": fallback_processed.collect_count or 0,
            "comment_count": fallback_processed.comment_count or 0,
            "share_count": fallback_processed.share_count or 0,
        }
    ]


def _event_item(
    row: PublicEvent,
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
) -> dict:
    risk_level = _risk_level(row)
    source_post_ids: list[int] = []
    source_platforms: list[str] = []

    for link in sorted(links, key=lambda item: item.rank):
        if link.raw_post_id and link.raw_post_id not in source_post_ids:
            source_post_ids.append(link.raw_post_id)
        platform = None
        if link.raw_post is not None:
            platform = link.raw_post.platform
        elif link.processed_post is not None:
            platform = link.processed_post.platform
        normalized = _normalize_platform(platform)
        if normalized and normalized not in source_platforms:
            source_platforms.append(normalized)

    if not links and fallback_processed is not None:
        if fallback_processed.raw_post_id:
            source_post_ids.append(fallback_processed.raw_post_id)
        normalized = _normalize_platform(fallback_processed.platform)
        if normalized:
            source_platforms.append(normalized)

    source_count = row.source_count or len(source_post_ids)

    return {
        "id": f"EVT-{row.id}",
        "raw_id": row.id,
        "event_key": row.event_key,
        "title": row.title,
        "summary": row.summary,
        "topic": row.topic,
        "event_type": row.event_type,
        "sentiment": row.sentiment,
        "status": row.status,
        "heatScore": row.heat_score,
        "heat_score": row.heat_score,
        "riskLevel": risk_level,
        "risk_level": risk_level,
        "riskLabel": _risk_label(risk_level),
        "risk_score": row.risk_score,
        "confidence": row.confidence,
        "source_count": source_count,
        "sourcePlatforms": source_platforms,
        "source_platforms": source_platforms,
        "source_post_ids": source_post_ids,
        "representativeCount": source_count,
        "representative_count": source_count,
        "date_range_json": row.date_range_json,
        "source_keywords_json": row.source_keywords_json,
        "top_tags_json": row.top_tags_json,
        "concerns_json": row.concerns_json,
        "risk_reasons_json": row.risk_reasons_json,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "review_comment": row.review_comment,
        "tags": [row.topic] if row.topic else [],
        "trend": [],
        "updatedAt": _format_datetime(row.updated_at or row.created_at),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _event_detail_item(
    row: PublicEvent,
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
) -> dict:
    item = _event_item(row, links, fallback_processed)
    item.update(
        {
            "date_range": _json_value(row.date_range_json, {}),
            "source_keywords": _json_value(row.source_keywords_json, []),
            "top_tags": _json_value(row.top_tags_json, []),
            "concerns": _json_value(row.concerns_json, []),
            "risk_reasons": _json_value(row.risk_reasons_json, []),
            "representative_posts": _representative_posts(links, fallback_processed),
        }
    )
    return item


@router.get("/ping")
def ping():
    return ok(
        PingData(
            pong=True,
            timestamp=datetime.utcnow(),
            database=_database_name(),
        ).model_dump()
    )


@router.get("/posts")
def list_posts(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(RawPost).order_by(RawPost.publish_time.desc(), RawPost.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [PostItem.model_validate(row).model_dump() for row in rows]
    return ok(PostListData(items=items, total=total, page=page, page_size=page_size).model_dump())


@router.get("/events")
def list_events(
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(PublicEvent).filter(PublicEvent.status == "published")
    query = query.order_by(PublicEvent.created_at.desc(), PublicEvent.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    event_ids = [row.id for row in rows]

    links_by_event: dict[int, list[EventPostLink]] = {event_id: [] for event_id in event_ids}
    if event_ids:
        links = (
            db.query(EventPostLink)
            .filter(EventPostLink.event_id.in_(event_ids))
            .order_by(EventPostLink.event_id.asc(), EventPostLink.rank.asc())
            .all()
        )
        for link in links:
            links_by_event.setdefault(link.event_id, []).append(link)

    fallback_processed = {}
    fallback_ids = [row.source_post_id for row in rows if row.source_post_id]
    if fallback_ids:
        fallback_processed = {
            post.id: post
            for post in db.query(ProcessedPost).filter(ProcessedPost.id.in_(fallback_ids)).all()
        }

    items = [
        _event_item(
            row,
            links_by_event.get(row.id, []),
            fallback_processed.get(row.source_post_id) if row.source_post_id else None,
        )
        for row in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/events/{event_id}")
def get_event_detail(event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(PublicEvent)
        .filter(PublicEvent.id == event_id, PublicEvent.status == "published")
        .first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    links = (
        db.query(EventPostLink)
        .filter(EventPostLink.event_id == event.id)
        .order_by(EventPostLink.rank.asc())
        .all()
    )
    fallback = None
    if event.source_post_id:
        fallback = db.query(ProcessedPost).filter(ProcessedPost.id == event.source_post_id).first()
    return ok(_event_detail_item(event, links, fallback))
