"""Public opinion Agent execution endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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


def _log_chat_query(db: Session, user_id: str, message: str, data: dict) -> None:
    """智能选题信号：成功路径落一条提问日志；写失败绝不影响对话主流程。"""

    try:
        if data.get("intent") == "search":
            # search 命中事件层升级作答时响应里是 events（没有 notes）——计数要跟着数
            # events，否则"答得很好的问题"被记成 0 命中，选题 planner 会误判为数据缺口。
            hit_count = len(data.get("notes") or data.get("events") or [])
        else:
            hit_count = len(data.get("events") or [])
        keyword = str(data.get("keyword") or "")
        # search 兜底会把整句回显为 keyword；整句不是话题词，置空让 planner 忽略（防污染需求信号）。
        if keyword == message:
            keyword = ""
        record_chat_query(
            db,
            user_id=user_id,
            message=message,
            intent=str(data.get("intent") or ""),
            keyword=keyword,
            hit_count=hit_count,
        )
        db.commit()
    except Exception:
        db.rollback()


@router.post("/agent/public/chat")
def chat_public_opinion(
    payload: PublicChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对话式舆情助手：意图路由 + ReAct 多步工具循环，只读不写库。

    非流式版：整篇生成完才返回。前端默认走 /agent/public/chat/stream（流式），
    这条保留给不支持流式的调用方，也是流式失败时的回退路径。
    """

    try:
        service = OpinionChatService(db)
        data = service.chat(payload.message, user_id=str(current_user.id), reset=payload.reset)
        _log_chat_query(db, str(current_user.id), payload.message, data)
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


def _sse(event: str, payload: dict) -> str:
    """一条 SSE 记录。

    data 必须压成**单行** JSON：SSE 用换行分隔字段、空行分隔事件，正文里的裸换行
    会把一条消息劈成两条。json.dumps 默认就会把 \\n 转义成 \\\\n，所以只要不开 indent 即可。
    """

    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/agent/public/chat/stream")
def chat_public_opinion_stream(
    payload: PublicChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对话式舆情助手（流式）。

    实测：简报意图非流式要 43 秒才出现第一个字（路由 4.2s + 生成 19.4s + AI 审校 19.4s），
    用户全程盯着一个按秒数猜出来的假进度条。流式后 2.7 秒开始出字，进度条说的是真话。

    事件：meta（意图）→ step（ReAct 每步）→ delta（正文增量）→ done（事件/引用/审校）。
    """

    user_id = str(current_user.id)

    def event_stream():
        final: dict = {}
        try:
            service = OpinionChatService(db)
            for event, data in service.chat_stream(payload.message, user_id=user_id, reset=payload.reset):
                if event == "done":
                    final = data
                yield _sse(event, data)
        except Exception as exc:
            # 已经开始流了，HTTP 状态码早就发出去了——只能把错误作为一个事件送下去。
            db.rollback()
            try:
                write_system_log(
                    db,
                    level="error",
                    module="agent",
                    message="public opinion chat stream failed",
                    detail={"message": payload.message[:100], "error": str(exc)},
                )
                db.commit()
            except Exception:
                db.rollback()
            yield _sse("error", {"message": str(exc)})
            return

        if final:
            _log_chat_query(db, user_id, payload.message, final)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx 默认会缓冲上游响应，缓冲住了流式就等于没有——必须显式关掉。
            "X-Accel-Buffering": "no",
        },
    )


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
