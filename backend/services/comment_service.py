"""事件评论区的业务规则（参与感 V1）。

评论的身份：**平台自己的用户内容**——不是爬来的客观事实（不进 raw/processed），
也不是 AI 主张（不走事件审核闸门）。平台对它负责，管控口径两段式：

    前置自动挡   注入清洗（prompt_guard）+ 长度 1..300 + 每用户 10s 冷却
    后置管控     举报满 5 条自动隐藏待复核；管理员隐藏/恢复留审计；
                 软隐藏不硬删（与帖子剔除同一哲学）

「站内声音」情绪在写入时用规则算好（复用核心的 analyze_note_sentiment_and_risk，
零新词表零 LLM）。V1 刻意不进聚类/LLM 语料——防自产自销回路（站内讨论影响
事件热度，事件展示又引导讨论）；V2 若进语料，用 HEAT_PLATFORM_WEIGHTS 钳制。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.agent.public_opinion_core.sentiment_risk import analyze_note_sentiment_and_risk
from backend.models import EventComment, PublicEvent
from backend.services.prompt_guard import sanitize_text


MAX_CONTENT_CHARS = 300
# 每用户发言冷却（秒）。防刷是参与感功能的底线设施——没有它，一个脚本就能把
# 评论区灌成垃圾场。进程内实现（单机部署够用；多 worker 时换 Redis，同记忆持久层）。
POST_COOLDOWN_SECONDS = 10.0
# 举报自动隐藏阈值：满 N 条先下架待复核——错误不对称（多挂 10 分钟一条垃圾评论
# 的伤害 < 一条人身攻击挂一晚上），先隐藏后复核。
AUTO_HIDE_REPORTS = 5

_last_post_at: dict[int, float] = {}
_rate_lock = threading.Lock()


class CommentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def reset_comment_rate_limit() -> None:
    with _rate_lock:
        _last_post_at.clear()


def _check_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    with _rate_lock:
        last = _last_post_at.get(user_id)
        if last is not None and now - last < POST_COOLDOWN_SECONDS:
            raise CommentError("发言太快了，歇 10 秒再来", status_code=429)
        _last_post_at[user_id] = now


def _rule_sentiment(text: str) -> str:
    """写入时算好的规则情绪（站内声音统计用）。复用核心分析器，零新词表。"""

    note = analyze_note_sentiment_and_risk(OpinionNote(note_id="comment", title="", content=text))
    return note.sentiment or "neutral"


def create_comment(
    db: Session, *, event_id: int, user_id: int, username: str, content: str, parent_id: int | None
) -> EventComment:
    event = db.query(PublicEvent).filter(PublicEvent.id == event_id).first()
    if event is None:
        raise CommentError("事件不存在", status_code=404)
    if event.status != "published":
        raise CommentError("只有已发布的事件可以评论")

    clean = sanitize_text((content or "").strip())  # 注入语句进库前清洗（评论未来可能进语料）
    if not clean:
        raise CommentError("评论内容不能为空")
    if len(clean) > MAX_CONTENT_CHARS:
        raise CommentError(f"评论最长 {MAX_CONTENT_CHARS} 字")

    if parent_id is not None:
        parent = db.query(EventComment).filter(EventComment.id == parent_id).first()
        if parent is None or parent.event_id != event_id:
            raise CommentError("回复的评论不存在", status_code=404)
        if parent.parent_id is not None:
            raise CommentError("只支持一层回复——请直接回复顶层评论")

    _check_rate_limit(user_id)

    comment = EventComment(
        event_id=event_id,
        user_id=user_id,
        username=username or f"用户{user_id}",
        parent_id=parent_id,
        content=clean,
        sentiment=_rule_sentiment(clean),
    )
    db.add(comment)
    db.flush()
    return comment


def report_comment(db: Session, comment_id: int) -> EventComment:
    comment = db.query(EventComment).filter(EventComment.id == comment_id).first()
    if comment is None:
        raise CommentError("评论不存在", status_code=404)
    comment.report_count = int(comment.report_count or 0) + 1
    if comment.status == "visible" and comment.report_count >= AUTO_HIDE_REPORTS:
        comment.status = "hidden"
        comment.hidden_reason = f"举报满 {AUTO_HIDE_REPORTS} 条自动隐藏，待管理员复核"
    return comment


def comment_item(comment: EventComment) -> dict:
    return {
        "id": comment.id,
        "event_id": comment.event_id,
        "parent_id": comment.parent_id,
        "username": comment.username,
        "content": comment.content,
        "sentiment": comment.sentiment,
        "status": comment.status,
        "report_count": comment.report_count,
        "created_at": comment.created_at.isoformat() if comment.created_at else "",
    }


def list_event_comments(db: Session, event_id: int) -> dict:
    """公开读：可见评论按顶层+内嵌回复组织，附「站内声音」情绪聚合（纯算术）。"""

    rows = (
        db.query(EventComment)
        .filter(EventComment.event_id == event_id, EventComment.status == "visible")
        .order_by(EventComment.created_at.asc(), EventComment.id.asc())
        .all()
    )
    tops = [comment_item(row) for row in rows if row.parent_id is None]
    by_id = {item["id"]: item for item in tops}
    for item in tops:
        item["replies"] = []
    for row in rows:
        if row.parent_id is not None and row.parent_id in by_id:
            by_id[row.parent_id]["replies"].append(comment_item(row))

    distribution: dict[str, int] = {}
    for row in rows:
        distribution[row.sentiment or "neutral"] = distribution.get(row.sentiment or "neutral", 0) + 1
    return {
        "items": tops,
        "total": len(rows),
        "voice": {"total": len(rows), "distribution": distribution},
    }
