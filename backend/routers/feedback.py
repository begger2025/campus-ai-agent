"""Feedback endpoints.

登录门 + 身份取自登录态（审计修复 2026-07-17）：此前这是全站唯一无鉴权的
写端点，且 user_id 由请求体提供——任何人可匿名批量写入并冒充任意用户。
与评论/投稿同族看齐：写操作一律要登录，身份只认 token。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.admin_models import User, UserFeedback
from backend.database import get_db
from backend.schemas import ok
from backend.services.auth_service import get_current_user

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    # 注意没有 user_id 字段：客户端多传会被 pydantic 忽略，身份只认登录态
    feedback_type: str = "suggestion"
    content: str = Field(min_length=1, max_length=5000)
    contact: str = ""
    target_type: str = "system"
    target_id: str = ""


@router.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = UserFeedback(
        user_id=current_user.username,
        target_type=payload.target_type or "system",
        target_id=payload.target_id or "",
        feedback_type=payload.feedback_type or "suggestion",
        content=payload.content,
        contact=payload.contact or "",
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(
        {
            "id": row.id,
            "status": row.status,
            "feedback_type": row.feedback_type,
            "created_at": row.created_at,
        }
    )
