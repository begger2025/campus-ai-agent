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
from backend.services.event_curation import (
    CurationError,
    add_post,
    create_event,
    delete_event,
    merge_events,
    remove_post,
    rename_event,
)
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


# ---------------------------------------------------------------- 人工事件修正
# AI 提议（聚类/研判）、人工裁决（status）之后的最后一块：人工修正。
# 语义（人工编辑=锁 curated、再生成只读、成员帖退出聚类池）见
# backend/services/event_curation.py 与 docs/superpowers/plans/2026-07-16-manual-event-curation.md。


def _load_event(db: Session, event_id: int) -> PublicEvent:
    event = db.query(PublicEvent).filter(PublicEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event


def _audit(db: Session, admin_user, action: str, target_id: str, before: dict, after: dict) -> None:
    write_admin_operation(
        db,
        admin_user_id=str(admin_user.id) if isinstance(admin_user, User) else "admin",
        action=action,
        target_type="public_event",
        target_id=target_id,
        before=before,
        after=after,
    )


def _run_curation(db: Session, operation):
    """统一事务边界：业务违规 → 4xx；成功才 commit（audit 与数据同事务）。"""

    try:
        result = operation()
    except CurationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    db.commit()
    return result


class EventRenamePatch(BaseModel):
    title: str


@router.patch("/admin/events/{event_id}")
def rename_admin_event(
    event_id: int,
    payload: EventRenamePatch,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    event = _load_event(db, event_id)

    def _do():
        before = {"title": event.title, "curated": bool(event.curated)}
        rename_event(db, event, payload.title)
        _audit(db, admin_user, "rename_event", str(event.id), before,
               {"title": event.title, "curated": True})
        return {"id": event.id, "title": event.title, "curated": True}

    return ok(_run_curation(db, _do))


class EventCreateBody(BaseModel):
    title: str
    post_ids: list[int]


@router.post("/admin/events")
def create_admin_event(
    payload: EventCreateBody,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    def _do():
        event = create_event(db, payload.title, payload.post_ids)
        _audit(db, admin_user, "create_event", str(event.id), {},
               {"title": event.title, "post_ids": payload.post_ids, "event_key": event.event_key})
        return {"id": event.id, "event_key": event.event_key, "title": event.title,
                "status": event.status, "source_count": event.source_count}

    return ok(_run_curation(db, _do))


@router.delete("/admin/events/{event_id}")
def delete_admin_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    event = _load_event(db, event_id)

    def _do():
        snapshot = delete_event(db, event)
        # 硬删的事件只活在审计里——快照必须够还原"删掉的是什么"
        _audit(db, admin_user, "delete_event", str(snapshot["id"]), snapshot, {})
        return {"deleted": snapshot}

    return ok(_run_curation(db, _do))


class EventMergeBody(BaseModel):
    source_id: int


@router.post("/admin/events/{event_id}/merge")
def merge_admin_events(
    event_id: int,
    payload: EventMergeBody,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    target = _load_event(db, event_id)
    source = _load_event(db, payload.source_id)
    actor = admin_user.username if isinstance(admin_user, User) else "admin"

    def _do():
        before = {"target_count": target.source_count, "source_status": source.status}
        merge_events(db, target, source, actor)
        _audit(db, admin_user, "merge_events", str(target.id), before,
               {"target_count": target.source_count, "source_id": source.id, "source_status": source.status})
        return {"id": target.id, "source_count": target.source_count,
                "merged_from": source.id, "curated": True}

    return ok(_run_curation(db, _do))


class EventPostBody(BaseModel):
    processed_post_id: int


@router.post("/admin/events/{event_id}/posts")
def add_event_post(
    event_id: int,
    payload: EventPostBody,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    event = _load_event(db, event_id)

    def _do():
        before = {"source_count": event.source_count}
        add_post(db, event, payload.processed_post_id)
        _audit(db, admin_user, "add_event_post", str(event.id), before,
               {"source_count": event.source_count, "processed_post_id": payload.processed_post_id})
        return {"id": event.id, "source_count": event.source_count, "curated": True}

    return ok(_run_curation(db, _do))


@router.delete("/admin/events/{event_id}/posts/{processed_post_id}")
def remove_event_post(
    event_id: int,
    processed_post_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    event = _load_event(db, event_id)

    def _do():
        before = {"source_count": event.source_count}
        remove_post(db, event, processed_post_id)
        _audit(db, admin_user, "remove_event_post", str(event.id), before,
               {"source_count": event.source_count, "processed_post_id": processed_post_id})
        return {"id": event.id, "source_count": event.source_count, "curated": True}

    return ok(_run_curation(db, _do))


class PostExcludePatch(BaseModel):
    excluded: bool
    reason: str = ""


@router.patch("/admin/posts/{post_id}/exclude")
def exclude_processed_post(
    post_id: int,
    payload: PostExcludePatch,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """数据质量管控：把一条无关帖**剔除**出所有下游（或恢复回来）。

    ## 剔除 ≠ 审核

    帖子是从公开平台爬来的**客观事实**（小红书上人人可见）。审核它 = 审核别人已经
    公开发布的话，语义上说不通；几千条逐条人审还会把整条 AI 流水线卡死（新帖审完
    才能进聚类）。**需要人工定夺的是 AI 的主张**（事件的聚类和研判），那道闸门在
    `public_events.status` 上，不在这里。

    这里要的不是闸门，是**质量管控**：同名的台湾国立中山大学、蹭校名的地产/床垫集采
    广告、早期乱填关键词爬回的 Python 教程帖——发现噪声，剔掉它。

    ## 剔除必须切断**所有**下游

    舆情分析页、事件聚类、舆情助手的检索（后两者共用 query_agent_rows）。漏掉任何
    一条就是**假剔除**：用户以为剔掉了，它却还在影响 AI 的结论——静默的错误答案。

    ## 软删除，不是 DELETE

    上一次清噪声帖是直接删库（375 行 / 6 张表 / 撞了外键回滚）。剔除可恢复，
    也留得下"谁在什么时候以什么理由剔的"（excluded_reason + admin_operations）。
    """

    post = db.query(ProcessedPost).filter(ProcessedPost.id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")

    before = {"excluded": bool(post.excluded), "excluded_reason": post.excluded_reason or ""}
    post.excluded = payload.excluded
    # 恢复时清掉理由：一条恢复了的帖子挂着"与本校无关"的理由，只会误导下一个看到它的人。
    post.excluded_reason = payload.reason.strip() if payload.excluded else ""
    after = {"excluded": bool(post.excluded), "excluded_reason": post.excluded_reason}

    write_admin_operation(
        db,
        admin_user_id=str(admin_user.id) if admin_user is not None else "system",
        action="exclude_processed_post" if payload.excluded else "restore_processed_post",
        target_type="processed_post",
        target_id=str(post.id),
        before=before,
        after=after,
    )
    db.commit()
    db.refresh(post)
    return ok(
        {
            "id": post.id,
            "title": post.title,
            "excluded": bool(post.excluded),
            "excluded_reason": post.excluded_reason or "",
        }
    )
