"""Unified task and log writing helpers for Week2 operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.admin_models import (
    AdminOperationLog,
    CrawlTask,
    EventReviewLog,
    SystemLog,
)


def _json_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def create_crawl_task(
    db: Session,
    *,
    task_name: str,
    task_type: str = "sync",
    platform: str = "all",
    keyword: str = "",
    created_by: str = "system",
    status: str = "running",
) -> CrawlTask:
    now = datetime.utcnow()
    task = CrawlTask(
        task_name=task_name,
        task_type=task_type,
        platform=platform or "all",
        keyword=keyword or "",
        status=status,
        started_by=created_by,
        created_by=created_by,
        started_at=now,
    )
    db.add(task)
    db.flush()
    return task


def finish_crawl_task(
    db: Session,
    task: CrawlTask,
    *,
    status: str,
    total_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    error_message: str = "",
    output_path: str = "",
) -> CrawlTask:
    task.status = status
    task.finished_at = datetime.utcnow()
    task.total_count = max(int(total_count or 0), 0)
    task.success_count = max(int(success_count or 0), 0)
    task.failed_count = max(int(failed_count or 0), 0)
    task.error_message = error_message or ""
    task.report_path = output_path or task.report_path or ""
    db.flush()
    return task


def write_system_log(
    db: Session,
    *,
    level: str,
    module: str,
    message: str,
    detail: Any = None,
    trace_id: str = "",
    related_task_id: int | None = None,
) -> SystemLog:
    detail_payload = detail
    if related_task_id is not None:
        if isinstance(detail_payload, dict):
            detail_payload = {**detail_payload, "related_task_id": related_task_id}
        else:
            detail_payload = {"detail": detail_payload, "related_task_id": related_task_id}

    row = SystemLog(
        level=(level or "info").lower(),
        module=module or "",
        message=message or "",
        detail=_json_text(detail_payload),
        request_id=trace_id or "",
    )
    db.add(row)
    db.flush()
    return row


def write_admin_operation(
    db: Session,
    *,
    admin_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str = "",
    user_agent: str = "",
) -> AdminOperationLog:
    detail = _json_text({"before_json": before or {}, "after_json": after or {}})
    row = AdminOperationLog(
        admin_user_id=admin_user_id,
        user_id=admin_user_id,
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


def write_event_review_log(
    db: Session,
    *,
    event_id: int,
    admin_user_id: str,
    from_status: str,
    to_status: str,
    review_comment: str = "",
) -> EventReviewLog:
    row = EventReviewLog(
        event_id=event_id,
        reviewer_id=admin_user_id,
        old_status=from_status,
        new_status=to_status,
        review_comment=review_comment,
        comment=review_comment,
    )
    db.add(row)
    db.flush()
    return row
