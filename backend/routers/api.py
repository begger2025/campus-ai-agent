import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.recency import (
    age_in_days,
    event_time_from_payload,
    lifecycle_from_payload,
    priority_score,
    recency_weight,
)
from backend.database import DATABASE_URL, get_db
from backend.models import EventPostLink, ProcessedPost, PublicEvent, RawPost
from backend.schemas import PingData, PostItem, PostListData, ok

router = APIRouter(tags=["api"])


def _now() -> datetime:
    """时效性排序的"现在"：**每次请求取一次**，往下传参。

    绝不在纯函数里调 datetime.now()——`sort_event_rows` / `_recency_fields` 都收 now 参数，
    所以它们可复现、可单测（见 backend/tests/test_events_api_recency.py）。
    """

    return datetime.now(UTC)


def _recency_fields(row: PublicEvent, now: datetime) -> dict:
    """一个已发布事件的时效性 + 生命周期字段（**读时现算**，不读数据库里的陈年快照）。

    库里只存两个**事实**：`date_range_json.event_time`（成员帖发布时间的中位数）和
    `date_range_json.lifecycle`（+ 理由；LLM 读帖子判出的"这件事完了没有"）。年龄、时效权重和
    优先级是 `now` 的函数——冻进数据库第二天就是错的，所以每次请求按当前时刻重算。
    没有 event_time 的老数据：age 未知（None），权重 1.0——"不知道多老" ≠ "很老"，不许凭空沉底。
    没有 lifecycle 的老数据：因子 1.0——"不知道结没结" ≠ "已经结了"，同样不许凭空打折。
    """

    event_time = event_time_from_payload(row.date_range_json)
    age = age_in_days(event_time, now)
    weight = recency_weight(age)
    lifecycle, lifecycle_reason = lifecycle_from_payload(row.date_range_json)
    return {
        "event_time": event_time,
        "age_days": None if age is None else round(age, 1),
        "recency_weight": round(weight, 6),
        "lifecycle": lifecycle,
        "lifecycle_reason": lifecycle_reason,
        "priority_score": priority_score(_risk_level(row), weight, lifecycle),
    }


def sort_event_rows(rows: list[PublicEvent], now: datetime) -> list[PublicEvent]:
    """前端看板的顺序：**展示优先级**（严重性 × 时效性 × 生命周期）优先，同优先级按热度。

    与核心 `clustering.sort_events` 同一口径
    （severity_weight × recency_weight × lifecycle_weight），只是这里的输入是数据库行。
    **必须在这里也排一遍**：核心的排序只决定写库顺序，写完就被 `ORDER BY created_at DESC`
    冲掉了——前端 `fetchPublishedEvents()` 拿到的是这个查询的顺序，所以"近期舆情优先"和
    "悬而未决的事不沉底"这两件事，只有在这里生效才算数。

    严重性和热度**不被时间或状态打折**（它们照原样返回给用户展示）；时效性和生命周期只影响顺序。
    """

    return sorted(
        rows,
        key=lambda row: (
            priority_score(
                _risk_level(row),
                recency_weight(
                    age_in_days(event_time_from_payload(row.date_range_json), now)
                ),
                lifecycle_from_payload(row.date_range_json)[0],
            ),
            float(row.heat_score or 0.0),
            int(row.id or 0),
        ),
        reverse=True,
    )


def _database_name() -> str:
    try:
        return make_url(DATABASE_URL).database or ""
    except Exception:
        return ""


def _risk_level(row: PublicEvent) -> str:
    if row.risk_level:
        return row.risk_level
    score = row.heat_score or 0
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _risk_label(level: str) -> str:
    return {"high": "高风险", "medium": "中风险", "low": "低风险"}.get(level, level)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M")


def _json_value(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _normalize_platform(platform: str | None) -> str:
    text = (platform or "").strip()
    lower = text.lower()
    if "weibo" in lower or "微博" in text:
        return "weibo"
    if "xhs" in lower or "小红书" in text:
        return "xhs"
    if "tieba" in lower or "贴吧" in text:
        return "tieba"
    if "zhihu" in lower or "知乎" in text:
        return "zhihu"
    if "kuaishou" in lower or lower == "ks" or "快手" in text:
        return "ks"
    # 证据采集交付写入的平台码。必须放在 weibo 判断之后并用精确匹配：
    # "web" 是 "weibo" 的前缀，子串匹配会把微博错判成 web。
    if lower == "web" or "网页" in text:
        return "web"
    return lower or text


def _representative_post_item(link: EventPostLink) -> dict:
    processed = link.processed_post
    raw = link.raw_post
    platform = ""
    title = ""
    content = ""
    author = ""
    publish_time = None
    url = ""
    raw_url = ""
    counts = {
        "like_count": 0,
        "collect_count": 0,
        "comment_count": 0,
        "share_count": 0,
    }

    if processed is not None:
        platform = processed.platform
        title = processed.title
        content = processed.content
        author = processed.author_name or processed.author
        publish_time = processed.publish_time
        url = processed.note_url
        raw_url = processed.raw_note_url
        counts = {
            "like_count": processed.like_count or 0,
            "collect_count": processed.collect_count or 0,
            "comment_count": processed.comment_count or 0,
            "share_count": processed.share_count or 0,
        }
    elif raw is not None:
        platform = raw.platform
        title = raw.title
        content = raw.content
        author = raw.author
        publish_time = raw.publish_time
        url = raw.url
        raw_url = raw.raw_url
        counts = {
            "like_count": raw.like_count or 0,
            "collect_count": raw.collect_count or 0,
            "comment_count": raw.comment_count or 0,
            "share_count": raw.share_count or 0,
        }

    return {
        "rank": link.rank,
        "role": link.role,
        "processed_post_id": link.processed_post_id,
        "raw_post_id": link.raw_post_id,
        "platform": _normalize_platform(platform),
        "title": title,
        "content": content,
        "author": author,
        "publish_time": _format_datetime(publish_time),
        "url": url,
        "raw_url": raw_url,
        **counts,
    }


def _representative_posts(
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
) -> list[dict]:
    posts = [_representative_post_item(link) for link in sorted(links, key=lambda item: item.rank)]
    if posts or fallback_processed is None:
        return posts
    return [
        {
            "rank": 1,
            "role": "source",
            "processed_post_id": fallback_processed.id,
            "raw_post_id": fallback_processed.raw_post_id,
            "platform": _normalize_platform(fallback_processed.platform),
            "title": fallback_processed.title,
            "content": fallback_processed.content,
            "author": fallback_processed.author_name or fallback_processed.author,
            "publish_time": _format_datetime(fallback_processed.publish_time),
            "url": fallback_processed.note_url,
            "raw_url": fallback_processed.raw_note_url,
            "like_count": fallback_processed.like_count or 0,
            "collect_count": fallback_processed.collect_count or 0,
            "comment_count": fallback_processed.comment_count or 0,
            "share_count": fallback_processed.share_count or 0,
        }
    ]


def _event_item(
    row: PublicEvent,
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
    now: datetime | None = None,
) -> dict:
    risk_level = _risk_level(row)
    # 年龄要**看得见**：不能只是把旧事件默默沉底，用户得能看到「5 年前」。
    # now 由调用方注入（列表/详情各取一次请求时刻）；缺省时才自己取，方便老调用方。
    recency = _recency_fields(row, now or _now())
    source_post_ids: list[int] = []
    source_platforms: list[str] = []

    for link in sorted(links, key=lambda item: item.rank):
        if link.raw_post_id and link.raw_post_id not in source_post_ids:
            source_post_ids.append(link.raw_post_id)
        platform = None
        if link.raw_post is not None:
            platform = link.raw_post.platform
        elif link.processed_post is not None:
            platform = link.processed_post.platform
        normalized = _normalize_platform(platform)
        if normalized and normalized not in source_platforms:
            source_platforms.append(normalized)

    if not links and fallback_processed is not None:
        if fallback_processed.raw_post_id:
            source_post_ids.append(fallback_processed.raw_post_id)
        normalized = _normalize_platform(fallback_processed.platform)
        if normalized:
            source_platforms.append(normalized)

    source_count = row.source_count or len(source_post_ids)

    return {
        "id": f"EVT-{row.id}",
        "raw_id": row.id,
        "event_key": row.event_key,
        "title": row.title,
        "summary": row.summary,
        "topic": row.topic,
        "event_type": row.event_type,
        "sentiment": row.sentiment,
        "status": row.status,
        "heatScore": row.heat_score,
        "heat_score": row.heat_score,
        "riskLevel": risk_level,
        "risk_level": risk_level,
        "riskLabel": _risk_label(risk_level),
        "risk_score": row.risk_score,
        # 时效性（第三根轴）：事件代表时间 + 年龄（天）+ 时效权重 + 展示优先级。
        # heat_score / risk_score 就在上面几行——它们是**没有被时间打折**的原值：
        # 火灾不会因为过了三个月变得不严重，热度是实测事实。时效性只影响顺序和"多旧"的展示。
        "event_time": recency["event_time"],
        "age_days": recency["age_days"],
        "recency_weight": recency["recency_weight"],
        # 生命周期（第四根轴）：这件事**完了没有** + 凭什么这么判。
        # 「已了结」的 3.5 个月前的火情该沉下去，「悬而未决」的 2 个月前的举报不该——
        # 管理员在看板上必须能看到理由，否则"为什么这条老事件还在最上面"没人解释得了。
        # "" = 未研判（LLM 关掉/失败/老数据）：因子 1.0，排序与改造前相同。
        "lifecycle": recency["lifecycle"],
        "lifecycle_reason": recency["lifecycle_reason"],
        "priority_score": recency["priority_score"],
        "confidence": row.confidence,
        "source_count": source_count,
        "sourcePlatforms": source_platforms,
        "source_platforms": source_platforms,
        "source_post_ids": source_post_ids,
        "representativeCount": source_count,
        "representative_count": source_count,
        "date_range_json": row.date_range_json,
        "source_keywords_json": row.source_keywords_json,
        "top_tags_json": row.top_tags_json,
        "concerns_json": row.concerns_json,
        "risk_reasons_json": row.risk_reasons_json,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "review_comment": row.review_comment,
        "tags": [row.topic] if row.topic else [],
        "trend": [],
        "updatedAt": _format_datetime(row.updated_at or row.created_at),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _event_detail_item(
    row: PublicEvent,
    links: list[EventPostLink],
    fallback_processed: ProcessedPost | None = None,
    now: datetime | None = None,
) -> dict:
    item = _event_item(row, links, fallback_processed, now=now)
    item.update(
        {
            "date_range": _json_value(row.date_range_json, {}),
            "source_keywords": _json_value(row.source_keywords_json, []),
            "top_tags": _json_value(row.top_tags_json, []),
            "concerns": _json_value(row.concerns_json, []),
            "risk_reasons": _json_value(row.risk_reasons_json, []),
            "representative_posts": _representative_posts(links, fallback_processed),
        }
    )
    return item


@router.get("/ping")
def ping():
    return ok(
        PingData(
            pong=True,
            timestamp=datetime.utcnow(),
            database=_database_name(),
        ).model_dump()
    )


@router.get("/posts")
def list_posts(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(RawPost).order_by(RawPost.publish_time.desc(), RawPost.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [PostItem.model_validate(row).model_dump() for row in rows]
    return ok(PostListData(items=items, total=total, page=page, page_size=page_size).model_dump())


@router.get("/events")
def list_events(
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    now = _now()
    query = db.query(PublicEvent).filter(PublicEvent.status == "published")

    # 排序在 Python 里做，不在 SQL 里：优先级 = 严重性 × 时效权重，而时效权重是"现在"的函数
    # （`0.5 ** (age/half_life)`），SQL 里既没有这个列也不该有——它一落库就会腐坏。
    # 所以先把**全部**已发布事件取出来排好，再切页：只有排序覆盖全集，分页才是对的
    # （用 SQL 的 OFFSET/LIMIT 再在页内排序，等于每页各排各的）。已发布事件是**几十条**的量级
    # （线上 15 条），全量取出的代价可以忽略；status 上的索引照旧生效。
    # 老口径 `ORDER BY created_at DESC` 排的是"这行是什么时候写进库的"，和"这件事什么时候发生的"
    # 毫无关系——五年前的处分和昨天的火情在同一次分析里入库，created_at 完全相同。
    rows = sort_event_rows(query.all(), now)
    total = len(rows)
    start = (page - 1) * page_size
    rows = rows[start : start + page_size]
    event_ids = [row.id for row in rows]

    links_by_event: dict[int, list[EventPostLink]] = {event_id: [] for event_id in event_ids}
    if event_ids:
        links = (
            db.query(EventPostLink)
            .filter(EventPostLink.event_id.in_(event_ids))
            .order_by(EventPostLink.event_id.asc(), EventPostLink.rank.asc())
            .all()
        )
        for link in links:
            links_by_event.setdefault(link.event_id, []).append(link)

    fallback_processed = {}
    fallback_ids = [row.source_post_id for row in rows if row.source_post_id]
    if fallback_ids:
        fallback_processed = {
            post.id: post
            for post in db.query(ProcessedPost).filter(ProcessedPost.id.in_(fallback_ids)).all()
        }

    items = [
        _event_item(
            row,
            links_by_event.get(row.id, []),
            fallback_processed.get(row.source_post_id) if row.source_post_id else None,
            now=now,
        )
        for row in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/events/{event_id}")
def get_event_detail(event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(PublicEvent)
        .filter(PublicEvent.id == event_id, PublicEvent.status == "published")
        .first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")

    links = (
        db.query(EventPostLink)
        .filter(EventPostLink.event_id == event.id)
        .order_by(EventPostLink.rank.asc())
        .all()
    )
    fallback = None
    if event.source_post_id:
        fallback = db.query(ProcessedPost).filter(ProcessedPost.id == event.source_post_id).first()
    return ok(_event_detail_item(event, links, fallback, now=_now()))
