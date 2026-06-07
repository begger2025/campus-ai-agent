"""Minimal administrator backend API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.schemas import ok
from backend.services.admin_service import (
    list_crawl_tasks_data,
    list_event_review_logs_data,
    list_feedback_data,
    list_operation_logs_data,
    list_raw_posts_data,
    list_system_logs_data,
    overview_data,
    update_feedback_status_data,
)
from backend.services.auth_service import require_admin

router = APIRouter(tags=["admin"])


class FeedbackStatusPatch(BaseModel):
    status: str
    handle_note: str = ""


@router.get("/admin/overview")
def overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return ok(overview_data(db))


@router.get("/admin/raw-posts")
def list_admin_raw_posts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    platform: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    return ok(
        list_raw_posts_data(
            db,
            page=page,
            page_size=page_size,
            platform=platform,
            keyword=keyword,
            start_date=start_date,
            end_date=end_date,
        )
    )


@router.get("/admin/crawl-tasks")
def list_admin_crawl_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    platform: str | None = None,
    task_type: str | None = None,
):
    return ok(
        list_crawl_tasks_data(
            db,
            page=page,
            page_size=page_size,
            status=status,
            platform=platform,
            task_type=task_type,
        )
    )


@router.get("/admin/feedback")
def list_admin_feedback(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
):
    return ok(list_feedback_data(db, page=page, page_size=page_size, status=status))


@router.patch("/admin/feedback/{feedback_id}/status")
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if payload.status not in {"pending", "handling", "resolved", "ignored", "handled"}:
        raise HTTPException(status_code=400, detail="invalid feedback status")
    row = update_feedback_status_data(
        db,
        feedback_id=feedback_id,
        status=payload.status,
        handled_by=current_user.username,
        handle_note=payload.handle_note,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="feedback not found")
    db.commit()
    return ok({"id": row.id, "status": row.status, "handled_by": row.handled_by})


@router.get("/admin/system-logs")
def list_admin_system_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    level: str | None = None,
    module: str | None = None,
):
    return ok(
        list_system_logs_data(
            db,
            page=page,
            page_size=page_size,
            level=level,
            module=module,
        )
    )


@router.get("/admin/operation-logs")
def list_admin_operation_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    target_type: str | None = None,
):
    return ok(
        list_operation_logs_data(
            db,
            page=page,
            page_size=page_size,
            action=action,
            target_type=target_type,
        )
    )


@router.get("/admin/events/{event_id}/review-logs")
def list_event_review_logs(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return ok(list_event_review_logs_data(db, event_id=event_id, page=page, page_size=page_size))
