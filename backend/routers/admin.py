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
    list_users_data,
    overview_data,
    update_feedback_status_data,
    update_user_status_data,
    user_item,
)
from backend.services.auth_service import require_admin
from backend.services.event_keywords import get_keyword_proposer
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions

router = APIRouter(tags=["admin"])

VALID_USER_STATUSES = {"active", "disabled"}


class FeedbackStatusPatch(BaseModel):
    status: str
    handle_note: str = ""


class UserStatusPatch(BaseModel):
    status: str


@router.get("/admin/overview")
def overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return ok(overview_data(db))


@router.get("/admin/keyword-suggestions")
def keyword_suggestions(
    days: int = Query(default=30, ge=1, le=365),
    top: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """智能选题：五信号融合的爬取关键词推荐（设计见 docs/superpowers/specs/2026-07-10）。

    第五路是**事件流水线**：已发布事件按 severity × recency × lifecycle 加权进候选池（算术），
    并由 LLM 从事件正文生成「学术不端」这类**语料里根本不存在**的检索词（判断）。

    **这里仍然只是建议**：把词放进爬取队列必须由管理员再点一下。AI 提议，人来决定。
    """

    return ok(
        get_keyword_suggestions(
            db, days=days, top=top, keyword_proposer=get_keyword_proposer()
        )
    )


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
    excluded: str | None = None,
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
            excluded=excluded,
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


@router.get("/admin/users")
def list_admin_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    role: str | None = None,
    status: str | None = None,
):
    return ok(
        list_users_data(db, page=page, page_size=page_size, keyword=keyword, role=role, status=status)
    )


@router.patch("/admin/users/{user_id}/status")
def update_user_status(
    user_id: int,
    payload: UserStatusPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if payload.status not in VALID_USER_STATUSES:
        raise HTTPException(status_code=400, detail="invalid user status")
    if user_id == current_user.id and payload.status != "active":
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    row = update_user_status_data(db, user_id=user_id, status=payload.status, operator=current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    db.commit()
    return ok(user_item(row))


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
