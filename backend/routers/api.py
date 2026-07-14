import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import DATABASE_URL, get_db
from backend.models import EventPostLink, ProcessedPost, PublicEvent, RawPost
from backend.schemas import PingData, PostItem, PostListData, ok
from backend.services.auth_service import get_current_user

# 「一行 public_events 此刻是什么状态」的唯一口径——事件看板和舆情助手共用。
# 各写一份必然漂移成两个世界，而那正是这次改造要消灭的东西：改造前事件页展示
# 「东校区宿舍搬迁 medium 风险」，用户在聊天里问同一件事却被告知"未检索到"。
from backend.services.event_read_model import (
    recency_fields as _recency_fields,
    risk_level_of as _risk_level,
    sort_event_rows,
)

router = APIRouter(tags=["api"])


def _now() -> datetime:
    """时效性排序的"现在"：**每次请求取一次**，往下传参。

    绝不在纯函数里调 datetime.now()——`sort_event_rows` / `_recency_fields` 都收 now 参数，
    所以它们可复现、可单测（见 backend/tests/test_events_api_recency.py）。
    """

    return datetime.now(UTC)


def _database_name() -> str:
    try:
        return make_url(DATABASE_URL).database or ""
    except Exception:
        return ""


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


# 来源平台的**展示顺序**。全站共用这一份——前端各自排一遍，迟早排出两个世界。
#
# 为什么需要它：`source_platforms` 原本是按**代表帖的热度排名**首次出现的顺序拼出来的，
# 于是"哪个平台排前面"取决于"哪个平台的帖子更火"——同一组平台在不同事件里排出不同顺序，
# 看板看起来是乱的（用户截图实证：有的事件小红书在前，有的快手在前）。那是一个**关于热度
# 的事实**，却被摆在了一个**关于来源构成的**位置上，读者会以为顺序有含义，其实没有。
#
# 顺序本身按语料量级排（xhs/ks 是主力，web 是证据采集交付的，最少）。
PLATFORM_DISPLAY_ORDER: tuple[str, ...] = ("xhs", "ks", "zhihu", "weibo", "tieba", "web")


def _sort_platforms(platforms: list[str]) -> list[str]:
    """按展示顺序排列、去重。没见过的平台码排到最后，但**绝不丢弃**。"""

    unique = list(dict.fromkeys(platforms))
    return sorted(
        unique,
        key=lambda p: (
            PLATFORM_DISPLAY_ORDER.index(p) if p in PLATFORM_DISPLAY_ORDER else len(PLATFORM_DISPLAY_ORDER),
            p,
        ),
    )


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

    # 按固定展示顺序排（见 PLATFORM_DISPLAY_ORDER）：拼出来的顺序跟着代表帖的热度走，
    # 那是"哪个平台的帖子更火"，不是"这个事件有哪些来源"——摆在来源列上会被读成后者。
    source_platforms = _sort_platforms(source_platforms)

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
        # 「持续发酵」的算术证据（近 21 天几条 / 一共几条 / 速率 / 结论）。
        # 徽标必须能被追问："凭什么说它在发酵？"——因为它近 21 天来了 3 条新帖，而它历史上
        # 平均 3 周才来 2 条。这是一个**可以复核的测量**，不是模型的语气判断。
        "growth": recency["growth"],
        "priority_score": recency["priority_score"],
        # 排序分的分解：severity × recency × lifecycle == priority_score。
        # 「凭什么这条 3 个月前的事排第一」——工作台把这三个因子摆出来，管理员自己复核。
        "priority_breakdown": recency["priority_breakdown"],
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
        # 生串保留（老调用方在读），同时给**解析好的**版本：一个接口不该把"我存的是
        # JSON 字符串"这个实现细节漏给每一个调用方。处置台要聚合所有中高风险事件的诉求，
        # 没有这个就得为了拿一个数组去逐个打详情接口。
        "concerns_json": row.concerns_json,
        "risk_reasons_json": row.risk_reasons_json,
        "concerns": _json_value(row.concerns_json, []),
        "risk_reasons": _json_value(row.risk_reasons_json, []),
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
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """原始采集帖（raw_posts）。**要登录。**

    帖子和事件需要的不是同一种门：
      - 事件是 **AI 的结论**（LLM 研判的风险/生命周期）—— AI 会错，所以必须人工审核；
        审过之后它就是对外公开的舆情结论，任何人可以看（`/events` 无需登录）。
      - 帖子是 **公开网络内容的搬运** —— 不需要"审核才能公开"，但它是平台的内部原始
        数据，不该让未登录的人随手 curl 走全库。

    改造前这个接口完全没有认证依赖：前端 router 里标的 roles 只是前端的门，后端不设防。
    """

    query = db.query(RawPost).order_by(RawPost.publish_time.desc(), RawPost.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [PostItem.model_validate(row).model_dump() for row in rows]
    return ok(PostListData(items=items, total=total, page=page, page_size=page_size).model_dump())


@router.get("/sentiment/posts")
def list_sentiment_posts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=100),
    sentiment: str = Query("", max_length=16),
    risk: str = Query("", max_length=16),
):
    """舆情分析页的帖子：查 **processed_posts**（已清洗、已打分的帖子）。

    为什么不复用 `/posts`：那个接口查的是 `raw_posts`——爬虫抓回来的原始帖，
    **没有 sentiment、没有 risk_level**。一个叫「舆情分析」的页面读它，结果就是
    每条帖子的风险徽章永远显示「—」、风险筛选器对帖子完全失效。
    `/posts`（首页的"最新动态"）继续读 raw_posts，语义不变。

    检索和筛选**必须在服务端做**：原实现把前 100 条捞到浏览器里做前端过滤，
    于是"搜索"只覆盖那 100 条——库里第 101 条之后的帖子永远搜不到，而页面看起来
    像是搜了全库。这是一个**静默**的错误答案，正是本项目最忌讳的那种 bug。
    """

    # 被管理员剔除的帖子（同名的台湾中山大学、蹭校名的广告…）不进这里。
    # 见 admin_events.exclude_processed_post：剔除必须切断**所有**下游，漏一条就是假剔除。
    query = db.query(ProcessedPost).filter(ProcessedPost.excluded.is_(False))

    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        # 匹配范围和搜索框的 placeholder 一字不差：标题、平台、作者。
        # 刻意**不**匹配 source_keyword（那是"爬虫搜索时用的词"，不是"帖子在讲什么"——
        # 拿它做匹配会把一堆凑数的泛化帖子捞进来，见 public_opinion_adapter 的注释）。
        query = query.filter(
            or_(
                ProcessedPost.title.like(like),
                ProcessedPost.platform.like(like),
                ProcessedPost.author_name.like(like),
                ProcessedPost.author.like(like),
            )
        )

    # 情绪是帖子身上**有信息量**的那根轴：真实分布 positive 155 / neutral 128 /
    # negative 84 / controversial 30。`controversial`（争议：正负声音都不少）是核心
    # 情绪聚合的第四种取值，不是拼写错误——漏掉它，那 30 条帖子的徽章就会变成「—」。
    sentiment = (sentiment or "").strip()
    if sentiment in {"positive", "neutral", "negative", "controversial"}:
        query = query.filter(ProcessedPost.sentiment == sentiment)

    # 风险这根轴在帖子级上几乎是常量：low 385 / medium 12 / **high 0**。
    # 帖子级风险是规则算的（词表 + 热度阈值），真正的风险研判在**事件级**、由 LLM 做——
    # 所以页面上帖子不再显示风险徽章，只有事件显示。**当前 UI 不传这个参数**；
    # 接口能力保留：帖子级风险模型若改进（例如接 LLM 分类），这个筛选立刻可用。
    risk = (risk or "").strip()
    if risk in {"high", "medium", "low"}:
        query = query.filter(ProcessedPost.risk_level == risk)

    # total 是**筛选后的全库条数**，不是这一页装了多少条——前端那张「帖子总数」卡片
    # 曾经拿 items.length 当总数，而 page_size 上限恰好是 100，于是它永远显示 100。
    total = query.count()
    rows = (
        query.order_by(ProcessedPost.publish_time.desc(), ProcessedPost.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": row.id,
            "platform": row.platform,
            "title": row.title,
            # 摘要供列表展开用；全文没必要进列表接口（详情要看原帖）。
            "content": (row.content or "")[:300],
            "author": row.author_name or row.author or "",
            "publish_time": row.publish_time.isoformat() if row.publish_time else "",
            "url": row.note_url or "",
            # 这三样正是 raw_posts 给不了的——风险徽章、情绪、热度都靠它们。
            "sentiment": row.sentiment or "neutral",
            "risk_level": row.risk_level or "low",
            "heat_score": float(row.heat_score or 0.0),
        }
        for row in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


# 情绪的四个档位。**四个，不是三个**：`controversial`（争议——正负声音都不少）是核心
# 情绪聚合的第四种取值。少一个档，图上就缺一块，而那一块有 30 条帖子。
SENTIMENT_BUCKETS = ("negative", "controversial", "neutral", "positive")

# 发帖趋势的窗口（天）。末端锚在**库里最新的数据日**而不是 datetime.now()——
# 语料的最近数据日可能是几天前，锚在今天会画出一条尾巴全是 0 的假趋势线。
# （首页的趋势图早就这么做了，图上明写着"截至 X · 最近数据日"。）
STATS_TREND_DAYS = 30

# 热度榜取几条。
STATS_TOP_POSTS = 5


@router.get("/sentiment/stats")
def sentiment_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """舆情分析页的**帖子层统计**：情绪分布 / 平台分布 / 发帖趋势 / 热度榜。

    这个接口是页面重新分工的产物。改造前舆情分析页有一半版面是**事件列表**——而事件
    列表在「事件列表」「舆情工作台」「舆情关注」里各有一份，全站出现了 4 次。
    重新划分后每页 = 唯一的（数据层 × 动词）：

        首页       概览层 × 看
        舆情分析   **帖子层 × 统计**   ← 就是这里
        事件列表   事件层 × 检索
        舆情工作台 单事件 × 研判
        舆情关注   中高风险 × 处置

    聚合必须在服务端做：前端只看得见"已经加载进来的那一页"（8 条），算不出全库 395 条
    的分布。
    """

    # 剔除的帖子不进统计——否则「帖子总数」和左边的列表对不上（列表已经过滤了）。
    rows = (
        db.query(
            ProcessedPost.sentiment,
            ProcessedPost.platform,
            ProcessedPost.publish_time,
        )
        .filter(ProcessedPost.excluded.is_(False))
        .all()
    )
    total = len(rows)

    # —— 情绪分布：四个档位一个都不能少，没有的补 0（否则图上缺一块） ——
    sentiment_counts = {bucket: 0 for bucket in SENTIMENT_BUCKETS}
    platform_counts: dict[str, int] = {}
    for sentiment, platform, _publish_time in rows:
        key = sentiment if sentiment in sentiment_counts else "neutral"
        sentiment_counts[key] += 1
        if platform:
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

    platforms = [
        {"platform": name, "count": count}
        for name, count in sorted(platform_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # —— 发帖趋势：按天聚合，空白天补 0 ——
    # 在 Python 里做而不是 SQL GROUP BY DATE()：SQLite 返回字符串、MySQL 返回 date 对象，
    # 方言差异要额外归一化；而数据量是几百行，代价可以忽略。
    times = [t for _s, _p, t in rows if t is not None]
    daily_trend: list[dict] = []
    if times:
        last_day = max(times).date()
        counts_by_day: dict[str, int] = {}
        for moment in times:
            counts_by_day[moment.date().isoformat()] = (
                counts_by_day.get(moment.date().isoformat(), 0) + 1
            )
        for offset in range(STATS_TREND_DAYS - 1, -1, -1):
            day = (last_day - timedelta(days=offset)).isoformat()
            daily_trend.append({"date": day, "count": counts_by_day.get(day, 0)})

    top_rows = (
        db.query(ProcessedPost)
        .filter(ProcessedPost.excluded.is_(False))  # 剔除的帖子不上热度榜
        .order_by(ProcessedPost.heat_score.desc(), ProcessedPost.id.desc())
        .limit(STATS_TOP_POSTS)
        .all()
    )
    top_posts = [
        {
            "id": row.id,
            "title": row.title,
            "platform": row.platform,
            "sentiment": row.sentiment or "neutral",
            "heat_score": float(row.heat_score or 0.0),
            "url": row.note_url or "",
        }
        for row in top_rows
    ]

    return ok(
        {
            "total": total,
            "sentiment": sentiment_counts,
            "platforms": platforms,
            "daily_trend": daily_trend,
            "top_posts": top_posts,
            "trend_days": STATS_TREND_DAYS,
        }
    )


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
