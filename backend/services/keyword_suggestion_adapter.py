"""智能选题聚合层：从 chat_query_log / processed_posts / **public_events** 取五路信号，调核心 planner。

只读，不写任何表。算法本体在 backend/agent/public_opinion_core/keyword_planner.py
（主项目是唯一源，直接改这里；改完用 scripts/sync_opinion_core.py 反向移植回子项目）。

**本轮新增的第五路：事件流水线。** 缺陷是刺眼的——系统一边把「中大杰青实名举报」判成
high(91) / 悬而未决 / 全库第一优先级，一边让选题器继续推荐「食堂」。左手不知道右手。
两个半边，分别站在同一条原则的两侧：

    算术：事件的 severity / lifecycle / recency **早就算好并落库了**，把它们乘起来喂给
          planner 是**接线**（`EventRecord` -> `plan_keywords(events=...)`）。这里没有 LLM。
    LLM ：事件该用**什么词**去搜。「学术不端」不在任何标题/标签/提问里，排序器**结构上**
          排不出一个它没见过的词——这才是 LLM 的位置（`llm_keywords` + `event_keywords`）。

**只读 published 事件**：草稿事件还没有经过管理员那道闸门，不许它去左右爬取计划。
（而生成出来的词同样只是**建议**：入队仍然要管理员点一下。AI 提议，人来决定。）
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
    EventRecord,
    QueryRecord,
    plan_keywords,
)
from backend.agent.public_opinion_core.llm_keywords import (
    KeywordProposer,
    generate_event_keywords,
)
from backend.agent.public_opinion_core.recency import (
    effective_lifecycle,
    event_time_from_payload,
    growth_signal,
    lifecycle_judgement_from_payload,
    member_times_from_payload,
    parse_time,
    recency_config,
)
from backend.models import ChatQueryLog, EventPostLink, ProcessedPost, PublicEvent
from backend.services.llm_config import EVENT_KEYWORD_MAX, EVENT_KEYWORD_TOP_EVENTS

CONTENT_WINDOW_DAYS = 14

# 一个事件送给 LLM 的代表帖上限（代表帖已经够判"该用什么词搜"了；读完 91 条纯属烧钱）。
EVENT_MAX_TEXTS = 5
EVENT_TEXT_MAX_CHARS = 120

# 一个标签至少要出现在这么多条成员帖上，才算这件事的证据（见 _parse_top_tags）。
MIN_TAG_POSTS = 2

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


def _parse_top_tags(top_tags_json: str) -> dict[str, float]:
    """top_tags_json（`[{"tag": "学术", "count": 3}]`）-> {标签: 权重}。

    两道关，都是**算术**（count 早就在库里：`clustering._top_tags` 数的就是"有几条成员帖带它"）：

      1. **门槛**：`count >= MIN_TAG_POSTS`（=2）。**出现一次的标签是噪音，不是信号。**
      2. **权重**：`count / max_count`（分母是**事件自己的** max，不是过关者里的 max——
         删掉噪音不该让剩下的词凭空涨分）。

    **为什么必须有门槛（而权重不够）。** 线上两份真实分布：

        《中大杰青实名举报》 学术(3) 热点(1) 新闻(1) 热点新闻事件(1) 社会新闻(1)
                            学术论文(1) 真实案件(1) 医学(1) 上海(1) 广州(1)
        《中大火箭试验成功》 宿舍(1)                                  ← 它**唯一**的标签

    权重那一版（上一轮）把「上海」压到 1/3 分——它照样上了首屏（实测第 16 名，1.00 分）。
    可 count=1 的意思是：**全事件只有一个发帖人打过这个 hashtag**。那是他一个人的贴标签习惯，
    不是"这件事该拿这个词去搜"的证据。「学术」(3 条帖子都打了) 是信号，「上海」(1 条) 不是。

    **为什么门槛必须是绝对下限，而不是"占最大值的比例"。** 火箭事件把 share-of-max 这条路堵死了：
    它的 `max_count` 本身就是 1，于是 宿舍(1)/1 = **1.0 满分**——任何比例阈值都放它过。
    分母是 1 的比例说明不了任何事。绝对下限的答案很干脆：**这个事件一个标签都提不出来**
    （它的 `source_keywords`——真的拿去爬过的词——不受影响）。两个互不相识的发帖人对同一件事
    都想到了同一个词，这是"标签能构成证据"的最小形态；一个人想到过，什么都不是。

    **不是黑名单**：这里没有一个词被点名。下一个事件的噪音是「深圳」「珠海」，同一条算术照拦。
    """

    try:
        data = json.loads(top_tags_json or "[]")
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    counts: dict[str, float] = {}
    for item in data:
        if isinstance(item, dict):
            name = str(item.get("tag") or "").strip()
            count = float(item.get("count") or 1)
        else:
            name, count = str(item).strip(), 1.0
        if name:
            counts[name] = max(counts.get(name, 0.0), count)
    top = max(counts.values(), default=0.0)
    if not top:
        return {}
    return {
        name: count / top
        for name, count in counts.items()
        if count >= MIN_TAG_POSTS
    }


def _parse_json_list(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item or "").strip()]


def _load_events(db: Session, *, now: datetime, half_life_days: float) -> list[EventRecord]:
    """已发布事件 -> planner 的只读投影。

    生命周期用**读侧合成**的那个（`escalating` = LLM 的 ongoing ∧ 算术测出的 growing），
    和 GET /api/events 完全同一个口径——否则看板说「持续发酵」、选题器却按「悬而未决」加权，
    两个界面会互相打脸。`escalating` 不落库（它是 now 的函数），所以必须在这里现算。
    """

    events = (
        db.query(PublicEvent)
        .filter(PublicEvent.status == "published")
        .all()
    )
    if not events:
        return []

    # 代表帖正文：只给 LLM 读。算术那一路一个字都不看。
    links = (
        db.query(EventPostLink.event_id, ProcessedPost.title, ProcessedPost.content)
        .join(ProcessedPost, EventPostLink.processed_post_id == ProcessedPost.id)
        .filter(EventPostLink.event_id.in_([event.id for event in events]))
        .order_by(EventPostLink.rank)
        .all()
    )
    texts_by_event: dict[int, list[str]] = {}
    for event_id, title, content in links:
        bucket = texts_by_event.setdefault(event_id, [])
        text_value = (title or content or "").strip()
        if text_value and len(bucket) < EVENT_MAX_TEXTS:
            bucket.append(text_value[:EVENT_TEXT_MAX_CHARS])

    records: list[EventRecord] = []
    for event in events:
        payload = event.date_range_json
        judgement, _ = lifecycle_judgement_from_payload(payload)
        growth = growth_signal(
            member_times_from_payload(payload), now, window_days=half_life_days
        )
        tag_weights = _parse_top_tags(event.top_tags_json)
        # source_keywords 是**真的拿去爬过**的词（不是顺手打的标签），不打折。
        source_keywords = _parse_json_list(event.source_keywords_json)
        records.append(
            EventRecord(
                event_id=str(event.id),
                title=event.title or "",
                risk_level=event.risk_level or "low",
                lifecycle=effective_lifecycle(judgement, growth["growing"]),
                event_time=parse_time(event_time_from_payload(payload)),
                keywords=[*tag_weights, *source_keywords],
                keyword_weights=tag_weights,
                texts=texts_by_event.get(event.id, []),
            )
        )
    return records


def get_keyword_suggestions(
    db: Session,
    *,
    days: int = 30,
    top: int = 10,
    now: datetime | None = None,
    keyword_proposer: KeywordProposer | None = None,
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

    # E：事件流水线。半衰期取事件侧**同一个** .env 值（21 天），选题器和看板不许各用一套年龄。
    half_life_days = recency_config()["half_life_days"]
    events = _load_events(db, now=now, half_life_days=half_life_days)

    # LLM 那一半：从事件生成检索词。proposer=None（未配置 / 显式关掉）-> 这一步是 no-op，
    # 事件的标签词照常进候选池（算术那一半完全不依赖 LLM）。
    warnings: list[str] = []
    stats = generate_event_keywords(
        events,
        keyword_proposer,
        now=now,
        half_life_days=half_life_days,
        warnings=warnings,
        top_events=EVENT_KEYWORD_TOP_EVENTS,
        max_per_event=EVENT_KEYWORD_MAX,
    )

    suggestions = plan_keywords(
        queries,
        content_stats,
        crawled_at_by_keyword,
        now=now,
        top_n=top,
        barren_keywords=barren_keywords,
        events=events,
        event_half_life_days=half_life_days,
    )
    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "meta": {
            "query_count": len(queries),
            "post_count": len(posts),
            "query_window_days": days,
            "content_window_days": CONTENT_WINDOW_DAYS,
            "barren_count": len(barren_keywords),
            "event_count": len(events),
            "event_half_life_days": half_life_days,
            "llm_events": stats["events"],
            "generated_keywords": stats["accepted"],
            "rejected_keywords": stats["rejected"],
            "warnings": warnings,
        },
    }
