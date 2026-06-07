"""Service helpers for the minimal admin backend API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.admin_models import (
    AdminOperationLog,
    CrawlTask,
    EventReviewLog,
    SystemLog,
    User,
    UserFeedback,
)
from backend.models import ProcessedPost, PublicEvent, RawPost
from backend.services.log_service import write_admin_operation


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _status_counts(db: Session, model, field_name: str) -> dict[str, int]:
    field = getattr(model, field_name)
    rows = db.query(field, func.count()).group_by(field).all()
    return {str(status or ""): int(count or 0) for status, count in rows}


def overview_data(db: Session) -> dict[str, Any]:
    recent_crawl_task = (
        db.query(CrawlTask).order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc()).first()
    )
    recent_error_count = (
        db.query(SystemLog)
        .filter(SystemLog.level.in_(["error", "critical"]))
        .count()
    )
    return {
        "raw_posts_count": db.query(RawPost).count(),
        "processed_posts_count": db.query(ProcessedPost).count(),
        "users_count": db.query(User).count(),
        "events": {
            "draft": db.query(PublicEvent).filter(PublicEvent.status == "draft").count(),
            "published": db.query(PublicEvent).filter(PublicEvent.status == "published").count(),
            "rejected": db.query(PublicEvent).filter(PublicEvent.status == "rejected").count(),
            "archived": db.query(PublicEvent).filter(PublicEvent.status == "archived").count(),
        },
        "crawl_tasks": _status_counts(db, CrawlTask, "status"),
        "feedback": _status_counts(db, UserFeedback, "status"),
        "recent_crawl_task": crawl_task_item(recent_crawl_task) if recent_crawl_task else None,
        "pending_feedback_count": db.query(UserFeedback).filter(UserFeedback.status == "pending").count(),
        "recent_system_errors_count": recent_error_count,
        "draft_events_count": db.query(PublicEvent).filter(PublicEvent.status == "draft").count(),
    }


def raw_post_item(row: RawPost) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform": row.platform,
        "external_id": row.external_id,
        "source_table": row.source_table,
        "source_raw_id": row.source_raw_id,
        "source_keyword": row.source_keyword,
        "title": row.title,
        "content": row.content,
        "author": row.author,
        "publish_time": _format_datetime(row.publish_time),
        "url": row.url,
        "raw_url": row.raw_url,
        "like_count": row.like_count,
        "collect_count": row.collect_count,
        "comment_count": row.comment_count,
        "share_count": row.share_count,
        "status": row.status,
        "created_at": _format_datetime(row.created_at),
        "updated_at": _format_datetime(row.updated_at),
    }


def list_raw_posts_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    platform: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    query = db.query(RawPost)
    if platform:
        query = query.filter(RawPost.platform == platform)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                RawPost.title.like(like),
                RawPost.content.like(like),
                RawPost.source_keyword.like(like),
                RawPost.author.like(like),
            )
        )
    if start_date:
        query = query.filter(RawPost.publish_time >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(RawPost.publish_time <= f"{end_date} 23:59:59")

    query = query.order_by(RawPost.publish_time.desc(), RawPost.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [raw_post_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def crawl_task_item(row: CrawlTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_name": row.task_name,
        "task_type": row.task_type,
        "platform": row.platform,
        "keyword": row.keyword,
        "status": row.status,
        "started_by": row.started_by or row.created_by,
        "started_at": _format_datetime(row.started_at),
        "finished_at": _format_datetime(row.finished_at),
        "total_count": row.total_count,
        "success_count": row.success_count,
        "failed_count": row.failed_count,
        "error_message": row.error_message,
        "report_path": row.report_path,
        "created_at": _format_datetime(row.created_at),
    }


def list_crawl_tasks_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    platform: str | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    query = db.query(CrawlTask)
    if status:
        query = query.filter(CrawlTask.status == status)
    if platform:
        query = query.filter(CrawlTask.platform == platform)
    if task_type:
        query = query.filter(CrawlTask.task_type == task_type)
    query = query.order_by(CrawlTask.created_at.desc(), CrawlTask.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [crawl_task_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def feedback_item(row: UserFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "feedback_type": row.feedback_type,
        "content": row.content,
        "contact": row.contact,
        "status": row.status,
        "handled_by": row.handled_by,
        "handled_at": _format_datetime(row.handled_at),
        "handle_note": row.handle_note,
        "created_at": _format_datetime(row.created_at),
        "updated_at": _format_datetime(row.updated_at),
    }


def list_feedback_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    query = db.query(UserFeedback)
    if status:
        query = query.filter(UserFeedback.status == status)
    query = query.order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [feedback_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_feedback_status_data(
    db: Session,
    *,
    feedback_id: int,
    status: str,
    handled_by: str,
    handle_note: str = "",
) -> UserFeedback | None:
    row = db.query(UserFeedback).filter(UserFeedback.id == feedback_id).first()
    if row is None:
        return None

    before = {
        "id": row.id,
        "status": row.status,
        "handled_by": row.handled_by,
        "handle_note": row.handle_note,
    }
    row.status = status
    row.handled_by = handled_by
    row.handled_at = datetime.utcnow()
    row.handle_note = handle_note
    after = {
        "id": row.id,
        "status": row.status,
        "handled_by": row.handled_by,
        "handle_note": row.handle_note,
    }
    write_admin_operation(
        db,
        admin_user_id=handled_by,
        action="update_feedback_status",
        target_type="user_feedback",
        target_id=str(row.id),
        before=before,
        after=after,
    )
    db.flush()
    return row


def system_log_item(row: SystemLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "level": row.level,
        "module": row.module,
        "message": row.message,
        "detail": row.detail,
        "trace_id": row.request_id,
        "created_at": _format_datetime(row.created_at),
    }


def list_system_logs_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    level: str | None = None,
    module: str | None = None,
) -> dict[str, Any]:
    query = db.query(SystemLog)
    if level:
        query = query.filter(SystemLog.level == level)
    if module:
        query = query.filter(SystemLog.module == module)
    query = query.order_by(SystemLog.created_at.desc(), SystemLog.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [system_log_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def operation_log_item(row: AdminOperationLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "admin_user_id": row.admin_user_id or row.user_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": row.detail,
        "ip_address": row.ip_address or row.ip,
        "user_agent": row.user_agent,
        "created_at": _format_datetime(row.created_at),
    }


def list_operation_logs_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    action: str | None = None,
    target_type: str | None = None,
) -> dict[str, Any]:
    query = db.query(AdminOperationLog)
    if action:
        query = query.filter(AdminOperationLog.action == action)
    if target_type:
        query = query.filter(AdminOperationLog.target_type == target_type)
    query = query.order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [operation_log_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def event_review_log_item(row: EventReviewLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "admin_user_id": row.reviewer_id,
        "from_status": row.old_status,
        "to_status": row.new_status,
        "review_comment": row.review_comment or row.comment,
        "created_at": _format_datetime(row.created_at),
    }


def list_event_review_logs_data(
    db: Session,
    *,
    event_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    query = (
        db.query(EventReviewLog)
        .filter(EventReviewLog.event_id == event_id)
        .order_by(EventReviewLog.created_at.desc(), EventReviewLog.id.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [event_review_log_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def record_admin_operation(
    db: Session,
    *,
    admin_user: User | None,
    admin_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str = "",
    user_agent: str = "",
) -> AdminOperationLog:
    actor = str(admin_user.id) if admin_user is not None else admin_user_id
    detail = json.dumps(
        {
            "before_json": before or {},
            "after_json": after or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    row = AdminOperationLog(
        admin_user_id=actor,
        user_id=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        ip=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    db.flush()
    return row
