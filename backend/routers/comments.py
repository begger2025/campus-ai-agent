"""事件评论区端点（参与感 V1）：公开读、登录写、管理员管控。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.models import EventComment
from backend.schemas import ok
from backend.services.auth_service import get_current_user, require_admin
from backend.services.comment_service import (
    CommentError,
    comment_item,
    create_comment,
    list_event_comments,
    report_comment,
)
from backend.services.log_service import write_admin_operation

router = APIRouter(tags=["comments"])


class CommentBody(BaseModel):
    content: str
    parent_id: int | None = None


@router.get("/events/{event_id}/comments")
def get_event_comments(event_id: int, db: Session = Depends(get_db)):
    """公开读（与事件本身的可见性口径一致：已发布事件游客可见）。"""

    return ok(list_event_comments(db, event_id))


@router.post("/events/{event_id}/comments")
def post_event_comment(
    event_id: int,
    payload: CommentBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(status_code=401, detail="login required")
    try:
        comment = create_comment(
            db,
            event_id=event_id,
            user_id=int(current_user.id),
            username=str(current_user.username or ""),
            content=payload.content,
            parent_id=payload.parent_id,
        )
    except CommentError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    db.commit()
    db.refresh(comment)
    return ok(comment_item(comment))


@router.post("/comments/{comment_id}/report")
def report_event_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(status_code=401, detail="login required")
    try:
        comment = report_comment(db, comment_id)
    except CommentError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    db.commit()
    return ok({"id": comment.id, "report_count": comment.report_count, "status": comment.status})


class CommentModerationPatch(BaseModel):
    status: str  # visible / hidden
    reason: str = ""


@router.get("/admin/comments")
def list_admin_comments(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
    reported: bool = Query(False),
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(EventComment)
    if reported:
        query = query.filter(EventComment.report_count > 0)
    if status != "all":
        query = query.filter(EventComment.status == status)
    query = query.order_by(EventComment.report_count.desc(), EventComment.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return ok({"items": [comment_item(row) for row in rows], "total": total, "page": page})


@router.patch("/admin/comments/{comment_id}")
def moderate_comment(
    comment_id: int,
    payload: CommentModerationPatch,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if payload.status not in ("visible", "hidden"):
        raise HTTPException(status_code=400, detail="invalid status")
    comment = db.query(EventComment).filter(EventComment.id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="comment not found")

    before = {"status": comment.status, "hidden_reason": comment.hidden_reason}
    comment.status = payload.status
    # 恢复时清理由——挂着旧理由会误导下一个管理员（与帖子剔除恢复同口径）
    comment.hidden_reason = payload.reason.strip() if payload.status == "hidden" else ""
    write_admin_operation(
        db,
        admin_user_id=str(admin_user.id) if isinstance(admin_user, User) else "admin",
        action="hide_comment" if payload.status == "hidden" else "restore_comment",
        target_type="event_comment",
        target_id=str(comment.id),
        before=before,
        after={"status": comment.status, "hidden_reason": comment.hidden_reason},
    )
    db.commit()
    return ok(comment_item(comment))
