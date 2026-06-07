"""Public opinion Agent execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.schemas import ok
from backend.services.public_opinion_adapter import (
    insert_failed_agent_run_log,
    run_public_opinion_analysis,
)
from backend.services.auth_service import require_admin
from backend.services.log_service import write_admin_operation, write_system_log

router = APIRouter(tags=["public-opinion-agent"])


class PublicAnalyzeRequest(BaseModel):
    keyword: str = ""
    limit: int = Field(default=50, ge=1, le=500)
    platforms: list[str] = Field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    persist: bool = True
    created_by: str = "system"


@router.post("/agent/public/analyze")
def analyze_public_opinion(
    payload: PublicAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    actor = current_user.username if isinstance(current_user, User) else payload.created_by
    try:
        data = run_public_opinion_analysis(
            db,
            keyword=payload.keyword,
            platforms=payload.platforms,
            limit=payload.limit,
            start_time=payload.start_time,
            end_time=payload.end_time,
            persist=payload.persist,
            created_by=actor,
        )
        write_admin_operation(
            db,
            admin_user_id=str(current_user.id) if isinstance(current_user, User) else actor,
            action="run_public_opinion_analysis",
            target_type="agent",
            target_id="public_opinion",
            before={"keyword": payload.keyword, "limit": payload.limit, "persist": payload.persist},
            after={
                "input_count": data.get("input_count"),
                "event_count": data.get("event_count"),
                "run_log_id": data.get("run_log_id"),
            },
        )
        db.commit()
        return ok(data)
    except Exception as exc:
        db.rollback()
        try:
            insert_failed_agent_run_log(
                db,
                keyword=payload.keyword,
                error_message=str(exc),
                created_by=actor,
            )
            write_system_log(
                db,
                level="error",
                module="agent",
                message="public opinion analysis failed",
                detail={
                    "keyword": payload.keyword,
                    "limit": payload.limit,
                    "error": str(exc),
                },
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
