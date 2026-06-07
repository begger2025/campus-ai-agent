"""Public feedback endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.admin_models import UserFeedback
from backend.database import get_db
from backend.schemas import ok

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    feedback_type: str = "suggestion"
    content: str = Field(min_length=1, max_length=5000)
    contact: str = ""
    user_id: str = "anonymous"
    target_type: str = "system"
    target_id: str = ""


@router.post("/feedback")
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    row = UserFeedback(
        user_id=payload.user_id or "anonymous",
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
