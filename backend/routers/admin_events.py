"""Administrator endpoints for public opinion event review."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.routers.api import _event_detail_item, _event_item
from backend.schemas import ok
from backend.services.auth_service import require_admin
from backend.services.log_service import write_admin_operation, write_event_review_log

router = APIRouter(tags=["admin-events"])

VALID_EVENT_STATUSES = {"draft", "published", "rejected", "archived"}


class EventStatusPatch(BaseModel):
    status: str
    reviewed_by: str = ""
    review_comment: str = ""


def _links_by_event(db: Session, event_ids: list[int]) -> dict[int, list[EventPostLink]]:
    result: dict[int, list[EventPostLink]] = {event_id: [] for event_id in event_ids}
    if not event_ids:
        return result
    rows = (
        db.query(EventPostLink)
        .filter(EventPostLink.event_id.in_(event_ids))
        .order_by(EventPostLink.event_id.asc(), EventPostLink.rank.asc())
        .all()
    )
    for row in rows:
        result.setdefault(row.event_id, []).append(row)
    return result


def _fallback_processed(db: Session, events: list[PublicEvent]) -> dict[int, ProcessedPost]:
    fallback_ids = [event.source_post_id for event in events if event.source_post_id]
    if not fallback_ids:
        return {}
    return {
        post.id: post
        for post in db.query(ProcessedPost).filter(ProcessedPost.id.in_(fallback_ids)).all()
    }


@router.get("/admin/events")
def list_admin_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    status: str = Query("all"),
    keyword: str | None = None,
    risk_level: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    clean_status = (status or "all").strip()
    if clean_status != "all" and clean_status not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid event status")

    query = db.query(PublicEvent)
    if clean_status != "all":
        query = query.filter(PublicEvent.status == clean_status)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (PublicEvent.title.like(like))
            | (PublicEvent.summary.like(like))
            | (PublicEvent.topic.like(like))
            | (PublicEvent.source_keywords_json.like(like))
        )
    if risk_level:
        query = query.filter(PublicEvent.risk_level == risk_level)
    query = query.order_by(PublicEvent.created_at.desc(), PublicEvent.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    links_by_event = _links_by_event(db, [row.id for row in rows])
    fallback = _fallback_processed(db, rows)

    items = [
        _event_item(
            row,
            links_by_event.get(row.id, []),
            fallback.get(row.source_post_id) if row.source_post_id else None,
        )
        for row in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/admin/events/{event_id}")
def get_admin_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    event = db.query(PublicEvent).filter(PublicEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    links = _links_by_event(db, [event.id]).get(event.id, [])
    fallback = None
    if event.source_post_id:
        fallback = db.query(ProcessedPost).filter(ProcessedPost.id == event.source_post_id).first()
    return ok(_event_detail_item(event, links, fallback))


@router.patch("/admin/events/{event_id}/status")
def update_event_status(
    event_id: int,
    payload: EventStatusPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if payload.status not in VALID_EVENT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid event status")

    event = db.query(PublicEvent).filter(PublicEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    old_status = event.status
    actor = (
        current_user.username
        if isinstance(current_user, User)
        else (payload.reviewed_by or "admin")
    )
    admin_user = current_user if isinstance(current_user, User) else None
    before = {
        "id": event.id,
        "status": old_status,
        "reviewed_by": event.reviewed_by,
        "review_comment": event.review_comment,
    }
    event.status = payload.status
    event.reviewed_by = actor
    event.reviewed_at = datetime.utcnow()
    event.review_comment = payload.review_comment
    after = {
        "id": event.id,
        "status": event.status,
        "reviewed_by": event.reviewed_by,
        "review_comment": event.review_comment,
    }

    write_event_review_log(
        db,
        event_id=event.id,
        admin_user_id=actor,
        from_status=old_status,
        to_status=payload.status,
        review_comment=payload.review_comment,
    )
    write_admin_operation(
        db,
        admin_user_id=str(admin_user.id) if admin_user is not None else actor,
        action="update_event_status",
        target_type="public_event",
        target_id=str(event.id),
        before=before,
        after=after,
    )
    db.commit()
    db.refresh(event)
    return ok(
        {
            "id": event.id,
            "old_status": old_status,
            "new_status": event.status,
            "reviewed_by": event.reviewed_by,
            "review_comment": event.review_comment,
        }
    )
