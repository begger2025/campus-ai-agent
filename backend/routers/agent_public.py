"""Public opinion Agent execution endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.schemas import ok
from backend.services.llm_client import get_llm_usage, llm_available
from backend.services.llm_config import LLM_CACHE_ENABLED, LLM_CACHE_PATH, OPENAI_MODEL
from backend.services.opinion_chat_service import OpinionChatService
from backend.services.public_opinion_adapter import (
    insert_failed_agent_run_log,
    run_public_opinion_analysis,
)
from backend.services.auth_service import get_current_user, require_admin
from backend.services.log_service import record_chat_query, write_admin_operation, write_system_log

router = APIRouter(tags=["public-opinion-agent"])


class PublicAnalyzeRequest(BaseModel):
    keyword: str = ""
    limit: int = Field(default=50, ge=1, le=500)
    platforms: list[str] = Field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    persist: bool = True
    created_by: str = "system"
    # LLM 情绪分析开关；未配 API key 时即使为 True 也自动退回规则。
    use_llm: bool = True


@router.get("/agent/public/usage")
def llm_usage(current_user: User = Depends(require_admin)):
    """LLM 用量监控（进程级计数器，服务重启归零；不是账单）。"""

    cache_entries = 0
    if LLM_CACHE_ENABLED and LLM_CACHE_PATH.exists():
        try:
            cache_entries = len(json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            cache_entries = -1  # 缓存文件损坏，仅作提示，不影响接口
    return ok(
        {
            "usage": get_llm_usage(),
            "scope": "process",
            "model": OPENAI_MODEL,
            "llm_enabled": llm_available(),
            "cache": {
                "enabled": LLM_CACHE_ENABLED,
                "entries": cache_entries,
                "path": str(LLM_CACHE_PATH),
            },
        }
    )


class PublicChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    # true 时先清空该用户的会话记忆（话题词 + 最近对话）再处理本条。
    reset: bool = False


@router.post("/agent/public/chat")
def chat_public_opinion(
    payload: PublicChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对话式舆情助手：意图路由 + ReAct 多步工具循环，只读不写库。"""

    try:
        service = OpinionChatService(db)
        data = service.chat(payload.message, user_id=str(current_user.id), reset=payload.reset)
        # 智能选题信号：成功路径落一条提问日志；写失败绝不影响对话主流程。
        try:
            if data.get("intent") == "search":
                hit_count = len(data.get("notes") or [])
            else:
                hit_count = len(data.get("events") or [])
            keyword = str(data.get("keyword") or "")
            # search 兜底会把整句回显为 keyword；整句不是话题词，置空让 planner 忽略（防污染需求信号）。
            if keyword == payload.message:
                keyword = ""
            record_chat_query(
                db,
                user_id=str(current_user.id),
                message=payload.message,
                intent=str(data.get("intent") or ""),
                keyword=keyword,
                hit_count=hit_count,
            )
            db.commit()
        except Exception:
            db.rollback()
        return ok(data)
    except Exception as exc:
        db.rollback()
        try:
            write_system_log(
                db,
                level="error",
                module="agent",
                message="public opinion chat failed",
                detail={"message": payload.message[:100], "error": str(exc)},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
            use_llm=payload.use_llm,
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
