"""Adapter between processed_posts and the portable public opinion Agent core."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.admin_models import AgentRunLog
from backend.agent.public_opinion_core import (
    AnalyzeRequest,
    JsonMemoryStore,
    OpinionNote,
    PublicOpinionAgentService,
    build_agent_run_log_payload,
    build_event_post_link_payloads,
    build_public_event_payloads,
    processed_posts_to_notes,
)
from backend.database import DATA_DIR
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.comment_loader import fetch_top_comments
from backend.services.embedding import get_embedder
from backend.services.llm_config import (
    EMBEDDING_ALIGN_THRESHOLD,
    EMBEDDING_CLUSTER_THRESHOLD,
    EMBEDDING_MERGE_THRESHOLD,
    EVENT_MIN_CLUSTER_SIZE,
)
from backend.services.log_service import write_event_review_log
from backend.services.sentiment_llm import get_sentiment_classifier


logger = logging.getLogger(__name__)

REVIEW_LOCKED_STATUSES = {"published", "rejected", "archived"}

# 跨次运行事件记忆（趋势标注、语义簇中心对齐）；preview 运行不更新。
MEMORY_SNAPSHOT_PATH = DATA_DIR / "public_opinion_memory.json"


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[str] = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _datetime_to_text(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def processed_post_to_agent_row(post: ProcessedPost) -> dict[str, Any]:
    """Convert one ProcessedPost ORM row to the Agent's processed-post mapping."""

    return {
        "id": post.id,
        "processed_post_id": post.id,
        "raw_post_id": post.raw_post_id,
        "platform": post.platform,
        "note_id": post.note_id,
        "title": post.title,
        "content": post.content,
        "source_keyword": post.source_keyword,
        "publish_date": post.publish_date,
        "publish_time": post.publish_time_raw or _datetime_to_text(post.publish_time),
        "author_name": post.author_name or post.author,
        "author": post.author_name or post.author,
        "keywords": _json_list(post.tags_json),
        "url": post.note_url,
        "note_url": post.note_url,
        "raw_url": post.raw_note_url,
        "raw_note_url": post.raw_note_url,
        "like_count": post.like_count,
        "collect_count": post.collect_count,
        "comment_count": post.comment_count,
        "share_count": post.share_count,
        # heat_score 展示用（web 行没有互动量，它的值来自来源权威度，不能靠 Agent 重算）；
        # heat_rank 是平台内百分位，排序/选 top-N/加权重要性都用它。
        "heat_score": post.heat_score,
        "heat_rank": post.heat_rank,
        "sentiment": post.sentiment,
        "risk_level": post.risk_level,
    }


def _filtered_post_query(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
):
    """processed_posts 的过滤查询（不含排序/limit），供取数和计数共用。"""

    query = db.query(ProcessedPost)
    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                ProcessedPost.title.like(like),
                ProcessedPost.content.like(like),
                ProcessedPost.source_keyword.like(like),
                ProcessedPost.author_name.like(like),
                ProcessedPost.tags_json.like(like),
            )
        )

    clean_platforms = [platform.strip() for platform in platforms or [] if platform.strip()]
    if clean_platforms:
        query = query.filter(ProcessedPost.platform.in_(clean_platforms))
    return query


def count_agent_rows(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
) -> int:
    """本次过滤条件下**总共**有多少条 processed_posts（用来发现 limit 截断）。"""

    return _filtered_post_query(db, keyword=keyword, platforms=platforms).count()


def query_agent_rows(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Load processed_posts rows as dictionaries accepted by the Agent core.

    ``limit <= 0`` 表示不设上限（全量）。历史实现把 limit 钳到 ``max(limit, 1)``，
    于是"全量"根本没法表达，而默认值又只取最新的一段——旧帖被无声丢掉。
    """

    query = _filtered_post_query(db, keyword=keyword, platforms=platforms)
    query = query.order_by(ProcessedPost.id.desc())
    if limit and limit > 0:
        query = query.limit(limit)
    rows = query.all()
    agent_rows = [processed_post_to_agent_row(row) for row in rows]

    # 附高赞评论摘录（评论区风向进情绪/风险分析与简报语料）；表缺失时为空。
    # processed_posts.note_id 带 "xhs:" 平台前缀，原生评论表是裸 note_id——按裸 ID 关联。
    def bare_note_id(value: str) -> str:
        return (value or "").split(":", 1)[-1]

    comments_by_ref = fetch_top_comments(
        db,
        [
            (row["platform"], bare_note_id(row["note_id"]))
            for row in agent_rows
            if row.get("note_id")
        ],
    )
    for row in agent_rows:
        row["top_comments"] = comments_by_ref.get(
            (row["platform"], bare_note_id(row.get("note_id") or "")), []
        )
    return agent_rows


def load_opinion_notes_from_db(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
) -> list[OpinionNote]:
    """Load processed_posts and convert them to portable OpinionNote objects."""

    rows = query_agent_rows(db, keyword=keyword, platforms=platforms, limit=limit)
    return processed_posts_to_notes(rows)


def upsert_public_events(
    db: Session,
    event_payloads: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, str]]:
    """Insert or update public_events and return event ids/statuses by event_key."""

    event_id_by_temp_id: dict[str, int] = {}
    event_status_by_temp_id: dict[str, str] = {}
    review_fields = {"reviewed_by", "reviewed_at", "review_comment"}

    for payload in event_payloads:
        event_key = str(payload.get("event_key") or "").strip()
        event = db.query(PublicEvent).filter(PublicEvent.event_key == event_key).first()

        if event is None:
            event = PublicEvent(**payload)
            db.add(event)
        else:
            old_status = event.status
            old_reviewed_by = event.reviewed_by
            old_reviewed_at = event.reviewed_at
            old_review_comment = event.review_comment
            for key, value in payload.items():
                if key in review_fields:
                    continue
                if hasattr(event, key):
                    setattr(event, key, value)
            if old_status in REVIEW_LOCKED_STATUSES:
                event.status = old_status
                event.reviewed_by = old_reviewed_by
                event.reviewed_at = old_reviewed_at
                event.review_comment = old_review_comment

        db.flush()
        event_id_by_temp_id[event_key] = event.id
        event_status_by_temp_id[event_key] = event.status

    return event_id_by_temp_id, event_status_by_temp_id


def replace_event_post_links(
    db: Session,
    link_payloads: list[dict[str, Any]],
    event_id_by_temp_id: dict[str, int],
) -> None:
    """Replace representative post links for the events touched by this run."""

    event_ids = list(event_id_by_temp_id.values())
    if event_ids:
        db.query(EventPostLink).filter(EventPostLink.event_id.in_(event_ids)).delete(
            synchronize_session=False
        )

    for payload in link_payloads:
        event_temp_id = str(payload.pop("event_temp_id", "") or "")
        event_id = event_id_by_temp_id.get(event_temp_id)
        if event_id is None:
            continue
        payload["event_id"] = event_id
        db.add(EventPostLink(**payload))
    db.flush()


def write_back_note_analysis(db: Session, notes: list[Any]) -> int:
    """把逐帖情绪/风险标注回写 processed_posts。

    不回写的话，这些列永远停留在处理脚本写入的占位值（全库 neutral/low），
    直接查表会得出"零负面"的错误结论。按 processed_post_id 精确更新。
    """

    updated = 0
    for note in notes:
        post_id = getattr(note, "processed_post_id", None)
        if not post_id:
            continue
        row = db.get(ProcessedPost, int(post_id))
        if row is None:
            continue
        row.sentiment = note.sentiment or "neutral"
        row.sentiment_score = float(note.sentiment_score or 0.0)
        row.risk_level = note.risk_level or "low"
        row.risk_score = float(note.risk_score or 0.0)
        row.risk_reasons_json = json.dumps(list(note.risk_reasons or []), ensure_ascii=False)
        row.concerns_json = json.dumps(list(note.concerns or []), ensure_ascii=False)
        updated += 1
    db.flush()
    return updated


def archive_stale_draft_events(db: Session, active_event_keys: set[str]) -> int:
    """归档本次全量分析不再出现的草稿事件（上一代聚类留下的"幽灵草稿"）。

    只碰 draft：published/rejected 是管理员决定，archived 已经出局。
    调用方负责确认本次运行"看全了"（无关键词/平台过滤、未被 limit 截断），
    否则子集运行会把无关草稿误判为失活。归档动作写审核日志留痕。
    """

    query = db.query(PublicEvent).filter(PublicEvent.status == "draft")
    if active_event_keys:
        query = query.filter(~PublicEvent.event_key.in_(active_event_keys))
    stale_events = query.all()

    for event in stale_events:
        old_status = event.status
        event.status = "archived"
        event.reviewed_by = "system"
        event.reviewed_at = datetime.utcnow()
        event.review_comment = "自动归档：本次全量分析未再出现（陈旧草稿）"
        write_event_review_log(
            db,
            event_id=event.id,
            admin_user_id="system",
            from_status=old_status,
            to_status="archived",
            review_comment=event.review_comment,
        )
    db.flush()
    return len(stale_events)


def insert_agent_run_log(db: Session, payload: dict[str, Any]) -> AgentRunLog:
    row = AgentRunLog(
        agent_type=payload.get("agent_type", "public_opinion"),
        keyword=payload.get("keyword", ""),
        input_count=int(payload.get("input_count") or 0),
        output_count=int(payload.get("output_count") or 0),
        input_summary=payload.get("input_summary", ""),
        output_summary=payload.get("output_summary", ""),
        status=payload.get("status", "success"),
        error_message=payload.get("error_message", ""),
        duration_ms=int(payload.get("duration_ms") or 0),
        created_by=payload.get("created_by", ""),
        started_at=_parse_datetime(payload.get("started_at")) or datetime.utcnow(),
        finished_at=_parse_datetime(payload.get("finished_at")),
    )
    db.add(row)
    db.flush()
    return row


def insert_failed_agent_run_log(
    db: Session,
    *,
    keyword: str,
    error_message: str,
    created_by: str = "system",
) -> AgentRunLog:
    now = datetime.utcnow()
    row = AgentRunLog(
        agent_type="public_opinion",
        keyword=keyword or "",
        input_count=0,
        output_count=0,
        input_summary="{}",
        output_summary="{}",
        status="failed",
        error_message=error_message,
        duration_ms=0,
        created_by=created_by,
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _merge_output_summary(raw_summary: Any, result: Any) -> str:
    """Append trend/mode info to the run log's output_summary JSON.

    public_events 表没有 extra 列，趋势与分析模式记录在 agent_run_logs 里。
    """

    try:
        summary = json.loads(raw_summary) if raw_summary else {}
    except (json.JSONDecodeError, TypeError):
        summary = {}
    if not isinstance(summary, dict):
        summary = {"original": summary}
    extra = result.run_log.extra or {}
    summary["trend_counts"] = extra.get("trend_counts", {})
    summary["sentiment_mode"] = extra.get("sentiment_mode", "rules")
    summary["clustering_mode"] = extra.get("clustering_mode", "rules")
    summary["sentiment_overridden"] = extra.get("sentiment_overridden", 0)
    return json.dumps(summary, ensure_ascii=False)


def run_public_opinion_analysis(
    db: Session,
    *,
    keyword: str = "",
    platforms: list[str] | None = None,
    limit: int = 50,
    start_time: str = "",
    end_time: str = "",
    persist: bool = True,
    created_by: str = "system",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run the public opinion Agent and optionally persist its payloads."""

    matched_total = count_agent_rows(db, keyword=keyword, platforms=platforms)
    rows = query_agent_rows(db, keyword=keyword, platforms=platforms, limit=limit)

    # 截断必须被数出来：limit 只取最新的一段，丢掉的是最旧的帖子。以前这里一声不吭，
    # "全量分析"其实只看了一部分数据（297 条 / 默认 limit=200 → 97 条老帖静默消失）。
    dropped = max(matched_total - len(rows), 0)
    truncation: dict[str, int] | None = None
    truncation_warnings: list[str] = []
    if dropped > 0:
        truncation = {"matched": matched_total, "analyzed": len(rows), "dropped": dropped}
        truncation_warnings.append(
            f"输入被 limit={limit} 截断：匹配 {matched_total} 条 processed_posts，"
            f"仅分析最新 {len(rows)} 条，丢弃最旧 {dropped} 条。"
            f"想跑全量请传 limit=0（脚本默认即全量）。"
        )
        logger.warning(truncation_warnings[-1])

    request = AnalyzeRequest(
        keyword=keyword or "",
        # AnalyzeRequest.limit 会把 <1 钳成 1，这里 limit<=0（全量）时用实际取到的行数，
        # 免得核心把 notes 截成 1 条。
        limit=limit if limit and limit > 0 else max(len(rows), 1),
        platforms=platforms or [],
        start_time=start_time or "",
        end_time=end_time or "",
    )
    memory_store = JsonMemoryStore(MEMORY_SNAPSHOT_PATH)
    result = PublicOpinionAgentService().analyze_from_rows(
        rows,
        request,
        previous_snapshot=memory_store.load(),
        # 未配 key / 未装 sentence-transformers 时返回 None，自动退回规则路径。
        sentiment_classifier=get_sentiment_classifier() if use_llm else None,
        embedder=get_embedder(),
        # 阈值随数据分布标定：真实小红书帖带话题标签/表情，基线相似度偏高，见 .env。
        cluster_threshold=EMBEDDING_CLUSTER_THRESHOLD,
        # 贪心之后再把质心足够像的簇合并：没有这一步，同一个话题会裂成多个同名事件。
        merge_threshold=EMBEDDING_MERGE_THRESHOLD,
        align_threshold=EMBEDDING_ALIGN_THRESHOLD,
        # 单帖不成事件（默认 2）：一条帖子自成一簇时不产出 public_event。
        min_cluster_size=EVENT_MIN_CLUSTER_SIZE,
    )
    result.warnings = truncation_warnings + list(result.warnings)
    if persist and result.snapshot is not None:
        memory_store.save(result.snapshot)

    event_payloads = build_public_event_payloads(result)
    link_payloads = build_event_post_link_payloads(result)
    run_log_payload = build_agent_run_log_payload(result)
    run_log_payload["created_by"] = created_by
    run_log_payload["output_summary"] = _merge_output_summary(run_log_payload.get("output_summary"), result)

    event_id_by_temp_id: dict[str, int] = {}
    event_status_by_temp_id: dict[str, str] = {}
    run_log_id = None

    if persist:
        event_id_by_temp_id, event_status_by_temp_id = upsert_public_events(db, event_payloads)
        replace_event_post_links(db, link_payloads, event_id_by_temp_id)
        write_back_note_analysis(db, result.notes)
        # 全量运行（无过滤且未被 limit 截断=看全了帖子）才有资格判定草稿失活
        run_is_full = not (keyword or "").strip() and not (platforms or []) and dropped == 0
        if run_is_full:
            archive_stale_draft_events(db, {str(p.get("event_key") or "") for p in event_payloads})
        run_log = insert_agent_run_log(db, run_log_payload)
        run_log_id = run_log.id

    events = []
    for event in result.events:
        status = event_status_by_temp_id.get(event.event_key, "draft")
        events.append(
            {
                "id": event_id_by_temp_id.get(event.event_key),
                "event_key": event.event_key,
                "title": event.title,
                "summary": event.summary,
                "topic": event.category,
                "event_type": event.category,
                "sentiment": event.sentiment,
                "risk_level": event.risk_level,
                "risk_score": event.risk_score,
                "heat_score": event.heat_score,
                "source_count": event.source_count,
                "status": status,
                # 跨次运行记忆标注（week3 记忆模块）
                "trend": event.trend,
                "heat_delta": event.heat_delta,
                "risk_escalated": event.risk_escalated,
            }
        )

    extra = result.run_log.extra or {}
    return {
        "status": result.run_log.status,
        "input_count": result.run_log.input_count,
        "event_count": len(result.events),
        "warnings": result.warnings,
        # None = 本次看全了；否则 {matched, analyzed, dropped}，调用方必须把它显示出来。
        "input_truncated": truncation,
        # 被压制的单帖簇（min_cluster_size 以下），不是事件但也不是"丢了"。
        "min_cluster_size": extra.get("min_cluster_size", 1),
        "suppressed_clusters": extra.get("suppressed_clusters", 0),
        "events": events,
        # 前端图表数据（week3 可视化数据层：日趋势/词云/情绪/风险/平台分布/事件趋势）
        "visualization": result.visualization,
        "trend_counts": extra.get("trend_counts", {}),
        "analysis_modes": {
            "sentiment": extra.get("sentiment_mode", "rules"),
            "clustering": extra.get("clustering_mode", "rules"),
            "sentiment_overridden": extra.get("sentiment_overridden", 0),
        },
        "payload_counts": {
            "public_events": len(event_payloads),
            "event_post_links": len(link_payloads),
            "agent_run_logs": 1,
        },
        "run_log_id": run_log_id,
        "payload_preview": None
        if persist
        else {
            "public_events": event_payloads,
            "event_post_links": link_payloads,
            "agent_run_logs": run_log_payload,
        },
    }
