"""智能选题聚合层：从 chat_query_log / processed_posts 取四路信号，调核心 planner。

只读，不写任何表。算法本体在 backend/agent/public_opinion_core/keyword_planner.py
（主项目是唯一源，直接改这里；改完用 scripts/sync_opinion_core.py 反向移植回子项目）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.keyword_planner import (
    ContentStat,
    QueryRecord,
    plan_keywords,
)
from backend.models import ChatQueryLog, ProcessedPost

CONTENT_WINDOW_DAYS = 14

_EPOCH = datetime(1970, 1, 1)


def _parse_tags(tags_json: str) -> list[str]:
    try:
        data = json.loads(tags_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for tag in data:
        # 兼容 xhs 旧数据的字典标签 [{"name":..., "type":...}]
        if isinstance(tag, dict):
            name = str(tag.get("name") or "").strip()
        else:
            name = str(tag).strip()
        if name:
            names.append(name)
    return names


def _load_crawler_history(
    db: Session, *, now: datetime
) -> tuple[set[str], dict[str, datetime]]:
    """读 crawler_run_history（MediaCrawler 侧建表），返回 (贫瘠词集合, 每词最新爬取时间)。

    - 窗口：近 CONTENT_WINDOW_DAYS 天（按 finished_at 毫秒过滤；finished_at 为 0/None
      的行退回用 started_at）。
    - 贫瘠判定：每个 source_keyword 取窗口内最新一次 run（跨平台合并），
      items_stored == 0 → 贫瘠。
    - 所有窗口内行的 finished_at 转 datetime 后按词取 max，供并入 crawled_at_by_keyword
      ——零产出的爬取从此也能触发常规降权。
    - 表不存在（共享库尚未建表 / SQLite 测试库）→ 优雅降级为空，行为与现状一致。
    """
    cutoff_ms = int((now - timedelta(days=CONTENT_WINDOW_DAYS) - _EPOCH).total_seconds() * 1000)
    sql = text(
        "SELECT source_keyword, started_at, finished_at, items_stored "
        "FROM crawler_run_history "
        "WHERE source_keyword IS NOT NULL AND source_keyword != '' "
        "AND COALESCE(NULLIF(finished_at, 0), started_at) >= :cutoff_ms"
    )
    try:
        rows = db.execute(sql, {"cutoff_ms": cutoff_ms}).fetchall()
    except (OperationalError, ProgrammingError):
        # MySQL 表不存在报 ProgrammingError(1146)，SQLite 报 OperationalError
        db.rollback()
        return set(), {}

    latest_run_by_keyword: dict[str, tuple[int, int]] = {}  # 词 -> (毫秒时间, items_stored)
    crawled_at_by_keyword: dict[str, datetime] = {}
    for keyword, started_at, finished_at, items_stored in rows:
        effective_ms = finished_at or started_at
        if not effective_ms:
            continue
        crawled_at = datetime.utcfromtimestamp(effective_ms / 1000.0)
        previous = crawled_at_by_keyword.get(keyword)
        if previous is None or crawled_at > previous:
            crawled_at_by_keyword[keyword] = crawled_at
        latest = latest_run_by_keyword.get(keyword)
        # 时间并列时按 items_stored 大者优先：同一时刻既有零产出又有有产出记录，
        # 不判贫瘠（宁可少降权也不误伤），且结果与行序无关
        candidate = (effective_ms, items_stored or 0)
        if latest is None or candidate > latest:
            latest_run_by_keyword[keyword] = candidate

    barren = {kw for kw, (_, stored) in latest_run_by_keyword.items() if stored == 0}
    return barren, crawled_at_by_keyword


def get_keyword_suggestions(
    db: Session,
    *,
    days: int = 30,
    top: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()

    logs = (
        db.query(ChatQueryLog)
        .filter(ChatQueryLog.created_at >= now - timedelta(days=days))
        .all()
    )
    queries = [
        QueryRecord(keyword=log.keyword, asked_at=log.created_at, hit_count=log.hit_count or 0)
        for log in logs
        if log.keyword
    ]

    posts = (
        db.query(ProcessedPost)
        .filter(ProcessedPost.created_at >= now - timedelta(days=CONTENT_WINDOW_DAYS))
        .all()
    )
    content_stats: list[ContentStat] = []
    for post in posts:
        published = post.publish_time or post.created_at or now
        engagement = (
            (post.like_count or 0)
            + (post.collect_count or 0)
            + (post.comment_count or 0)
            + (post.share_count or 0)
        )
        words = set(_parse_tags(post.tags_json))
        if post.source_keyword:
            words.add(post.source_keyword)
        for word in words:
            content_stats.append(ContentStat(keyword=word, engagement=engagement, published_at=published))

    # 上次爬取时间查全表（不限 14 天窗），reason 里的"N天前爬过"才准确。
    crawled_rows = (
        db.query(ProcessedPost.source_keyword, func.max(ProcessedPost.created_at))
        .filter(ProcessedPost.source_keyword != "")
        .group_by(ProcessedPost.source_keyword)
        .all()
    )
    crawled_at_by_keyword = {keyword: crawled_at for keyword, crawled_at in crawled_rows}

    # 爬取历史：零产出的词进贫瘠集合强降权；finished_at 与内容表倒推值取 max
    barren_keywords, history_crawled_at = _load_crawler_history(db, now=now)
    for keyword, crawled_at in history_crawled_at.items():
        existing = crawled_at_by_keyword.get(keyword)
        if existing is None or crawled_at > existing:
            crawled_at_by_keyword[keyword] = crawled_at

    suggestions = plan_keywords(
        queries,
        content_stats,
        crawled_at_by_keyword,
        now=now,
        top_n=top,
        barren_keywords=barren_keywords,
    )
    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "meta": {
            "query_count": len(queries),
            "post_count": len(posts),
            "query_window_days": days,
            "content_window_days": CONTENT_WINDOW_DAYS,
            "barren_count": len(barren_keywords),
        },
    }
