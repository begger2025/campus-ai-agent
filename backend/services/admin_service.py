"""Service helpers for the minimal admin backend API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.admin_models import (
    AdminOperationLog,
    CrawlTask,
    EventReviewLog,
    SystemLog,
    User,
    UserFeedback,
)
from backend.models import EventComment, ProcessedPost, PublicEvent, RawPost, UserSubmission
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
        # —— 今日工作台扩展（全部实时查询，零 LLM）——
        "pending_submissions_count": (
            db.query(UserSubmission).filter(UserSubmission.status == "pending").count()
        ),
        # 被举报评论：有举报计数的都值得复核（含自动隐藏的）
        "reported_comments_count": (
            db.query(EventComment).filter(EventComment.report_count > 0).count()
        ),
        "curated_events_count": (
            db.query(PublicEvent).filter(PublicEvent.curated.is_(True)).count()
        ),
        # 语料体检：新鲜度是播种计划的验收 KPI，直接上墙
        "corpus": _corpus_health(db),
        # 最近一次事件生成 run：比「最近采集任务」信息量高（事件数/状态/耗时/警告）
        "last_agent_run": _last_agent_run(db),
        # LLM 用量（进程内计数器，服务启动以来）
        "llm_usage": _llm_usage(),
    }


def _corpus_health(db: Session) -> dict[str, Any]:
    from datetime import timedelta

    query = db.query(ProcessedPost).filter(ProcessedPost.excluded.is_(False))
    total = query.count()
    recent = query.filter(
        ProcessedPost.publish_time >= datetime.utcnow() - timedelta(days=30)
    ).count()
    return {
        "total": total,
        "recent_30d": recent,
        "recent_ratio": round(recent / total, 3) if total else 0.0,
        "excluded": db.query(ProcessedPost).filter(ProcessedPost.excluded.is_(True)).count(),
    }


def _last_agent_run(db: Session) -> dict[str, Any] | None:
    from backend.admin_models import AgentRunLog

    row = db.query(AgentRunLog).order_by(AgentRunLog.id.desc()).first()
    if row is None:
        return None
    # warnings 藏在 output_summary 的 JSON 里（insert_agent_run_log 写入的形状）；
    # 解析不动就当 0——概览是速览，不为一个计数抛错。
    warnings_count = 0
    try:
        summary = json.loads(row.output_summary or "{}")
        warnings = summary.get("warnings")
        if isinstance(warnings, list):
            warnings_count = len(warnings)
    except (ValueError, AttributeError):
        pass
    return {
        "id": row.id,
        "status": row.status or "",
        "event_count": int(row.output_count or 0),
        "input_count": int(row.input_count or 0),
        "duration_ms": int(row.duration_ms or 0),
        "finished_at": _format_datetime(getattr(row, "created_at", None)),
        "warnings_count": warnings_count,
    }


def _llm_usage() -> dict[str, Any]:
    try:
        from backend.services.llm_client import get_llm_usage

        return dict(get_llm_usage())
    except Exception:
        return {}


def raw_post_item(row: RawPost, processed: "ProcessedPost | None" = None) -> dict[str, Any]:
    """一行原始采集帖 + 它在下游（processed_posts）的**剔除状态**。

    ## 为什么要带 processed_post_id

    数据管理页读的是 `raw_posts`，而剔除标记在 `processed_posts` 上（下游——舆情分析页 /
    事件聚类 / agent 检索——查的都是那张表）。**两张表的主键不是同一个**：拿 raw_post.id
    去 PATCH 剔除接口，会剔掉另一条毫不相干的帖子。

    `processed_post_id=None` = 这条还没跑清洗流水线，下游根本没有它——前端把剔除按钮
    禁掉，不能假装能剔一个还不存在的东西。
    """

    return {
        "id": row.id,
        # 剔除按钮要 PATCH 的是它，不是上面那个 id
        "processed_post_id": processed.id if processed is not None else None,
        "excluded": bool(processed.excluded) if processed is not None else False,
        "excluded_reason": (processed.excluded_reason or "") if processed is not None else "",
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
    excluded: str | None = None,
) -> dict[str, Any]:
    query = db.query(RawPost)

    # 「已剔除 / 未剔除」筛选：管理员要能复核自己剔了什么（不然也谈不上恢复）。
    # 剔除标记在 processed_posts 上，所以按子查询过滤。
    # 注意 "未剔除" 要包含**还没跑清洗流水线**的帖子（它们在下游根本不存在，谈不上被剔除）。
    clean_excluded = (excluded or "").strip().lower()
    if clean_excluded in ("true", "1"):
        excluded_raw_ids = select(ProcessedPost.raw_post_id).where(
            ProcessedPost.excluded.is_(True)
        )
        query = query.filter(RawPost.id.in_(excluded_raw_ids))
    elif clean_excluded in ("false", "0"):
        excluded_raw_ids = select(ProcessedPost.raw_post_id).where(
            ProcessedPost.excluded.is_(True)
        )
        query = query.filter(RawPost.id.not_in(excluded_raw_ids))

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

    # 一次查完这一页所有帖子的下游状态（避免 N+1）
    processed_by_raw_id: dict[int, ProcessedPost] = {}
    if rows:
        processed_rows = (
            db.query(ProcessedPost)
            .filter(ProcessedPost.raw_post_id.in_([row.id for row in rows]))
            .all()
        )
        processed_by_raw_id = {post.raw_post_id: post for post in processed_rows}

    return {
        "items": [raw_post_item(row, processed_by_raw_id.get(row.id)) for row in rows],
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


def user_item(row: User) -> dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "role": row.role,
        "display_name": row.display_name,
        "status": row.status,
        "is_active": row.is_active,
        "created_at": _format_datetime(row.created_at),
        "last_login_at": _format_datetime(row.last_login_at),
    }


def list_users_data(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    query = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(User.username.like(like), User.display_name.like(like)))
    if role:
        query = query.filter(User.role == role)
    if status:
        query = query.filter(User.status == status)
    query = query.order_by(User.id.asc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [user_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_user_status_data(
    db: Session,
    *,
    user_id: int,
    status: str,
    operator: User,
) -> User | None:
    row = db.query(User).filter(User.id == user_id).first()
    if row is None:
        return None
    before = {"id": row.id, "status": row.status, "is_active": row.is_active}
    row.status = status
    row.is_active = status == "active"
    after = {"id": row.id, "status": row.status, "is_active": row.is_active}
    write_admin_operation(
        db,
        admin_user_id=str(operator.id),
        action="update_user_status",
        target_type="user",
        target_id=str(row.id),
        before=before,
        after=after,
    )
    db.flush()
    return row


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
