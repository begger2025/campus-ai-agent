"""智能选题聚合层：从 chat_query_log / processed_posts 取四路信号，调核心 planner。

只读，不写任何表。算法本体在 backend/agent/public_opinion_core/keyword_planner.py
（由子项目单向同步，勿在主项目直接改）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.keyword_planner import (
    ContentStat,
    QueryRecord,
    plan_keywords,
)
from backend.models import ChatQueryLog, ProcessedPost

CONTENT_WINDOW_DAYS = 14


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

    suggestions = plan_keywords(queries, content_stats, crawled_at_by_keyword, now=now, top_n=top)
    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "meta": {
            "query_count": len(queries),
            "post_count": len(posts),
            "query_window_days": days,
            "content_window_days": CONTENT_WINDOW_DAYS,
        },
    }
