"""已发布事件的**读模型**：一行 `public_events` → 它此刻的状态。

这个模块是「事件长什么样」的**唯一口径**。事件看板（routers/api.py）和舆情助手
（services/opinion_chat_service.py）都从这里取——各写一份必然漂移成两个世界，而那正是
这次改造要消灭的东西：改造前事件页展示「东校区宿舍搬迁 medium 风险 6 条帖」，
用户在聊天里问同一件事却被告知"未检索到代表性内容"。

## 读时现算 vs 落库

库里只存**事实**和**判断**：
  - `date_range_json.event_time` / `member_times` —— 成员帖的发布时间（事实）
  - `date_range_json.lifecycle_judgement` —— LLM 读帖子判出的"这件事还悬着吗"（判断）
  - `risk_level` / `risk_score` / `risk_reasons_json` —— LLM 的风险研判（判断）

年龄、时效权重、"是否仍在增长"、最终生命周期、优先级**全是 `now` 的函数**——冻进数据库
第二天就是错的，所以每次读的时候按当前时刻重算。一个上周还在发酵的事件，不该因为快照
过期就**永远**挂着「持续发酵」的徽标。
"""

from __future__ import annotations

from datetime import datetime
import json
import threading
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.recency import (
    age_in_days,
    effective_lifecycle,
    event_time_from_payload,
    growth_signal,
    lifecycle_judgement_from_payload,
    member_times_from_payload,
    priority_score,
    recency_weight,
)
from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.embedding import get_embedder
from backend.services.event_judge import judge_event_match
from backend.services.llm_config import (
    EVENT_JUDGE_ENABLED,
    EVENT_SEMANTIC_LOW_THRESHOLD,
    EVENT_SEMANTIC_MATCH_ENABLED,
    EVENT_SEMANTIC_MATCH_THRESHOLD,
)


# 一个事件最多带几条代表帖进 prompt。event_post_links 本来也只存 top-5
# （role='representative'），而 opinion_report.compact_events_for_llm 也只取这么多——
# 三处对齐，别让某一处偷偷截断。
MAX_REPRESENTATIVE_NOTES = 5


def json_value(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def risk_level_of(row: PublicEvent) -> str:
    """事件的风险等级。有 LLM 研判就用它；老数据没有才按热度粗分。"""

    if row.risk_level:
        return row.risk_level
    score = row.heat_score or 0
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def lifecycle_now(row: PublicEvent, now: datetime) -> tuple[str, str, dict]:
    """一行的**当下**状态 = LLM 的判断 + 此刻的增长测量，现场合成。

        escalating = ongoing（判断：这件事悬而未决）∧ growing（测量：新帖还在来）

    **为什么在读侧合成、而不是读一个落库的 escalating**：「还在不在长」是 `now` 的函数
    （和 age_days / recency_weight 一模一样）。把它冻进数据库，一个上周还在发酵的事件就会
    **永远**挂着「持续发酵」的徽标，哪怕早就没人再发帖了。现算 ⇒ 看板自我纠正。

    库里存的两样东西都不是 now 的函数，所以都是安全的：
      - `lifecycle_judgement`（模型读帖子判出的"有没有待办动作"）——**判断**；
      - `member_times`（成员帖的发布时间）——**事实**。
    老数据（没有这两个键）：judgement 退回读 `lifecycle`（并把老版本落库的 `escalating`
    降回 `ongoing`，见 effective_lifecycle），member_times 为空 -> growing=False ->
    不会有任何东西被凭空提升。
    """

    judgement, reason = lifecycle_judgement_from_payload(row.date_range_json)
    growth = growth_signal(member_times_from_payload(row.date_range_json), now)
    return effective_lifecycle(judgement, growth["growing"]), reason, growth


def recency_fields(row: PublicEvent, now: datetime) -> dict:
    """一个已发布事件的时效性 + 生命周期字段（**读时现算**，不读数据库里的陈年快照）。

    没有 event_time 的老数据：age 未知（None），权重 1.0——"不知道多老" ≠ "很老"，不许凭空沉底。
    没有 lifecycle 的老数据：因子 1.0——"不知道结没结" ≠ "已经结了"，同样不许凭空打折。
    """

    event_time = event_time_from_payload(row.date_range_json)
    age = age_in_days(event_time, now)
    weight = recency_weight(age)
    lifecycle, lifecycle_reason, growth = lifecycle_now(row, now)
    return {
        "event_time": event_time,
        "age_days": None if age is None else round(age, 1),
        "recency_weight": round(weight, 6),
        "lifecycle": lifecycle,
        "lifecycle_reason": lifecycle_reason,
        # 「持续发酵」的**证据**：近 21 天几条 / 一共几条 / 速率。徽标背后必须有"凭什么"——
        # 一个说不出依据的徽标只是一句主张。管理员点开就能看到"近 21 天 3/4 帖"。
        "growth": growth,
        "priority_score": priority_score(risk_level_of(row), weight, lifecycle),
    }


def sort_event_rows(rows: list[PublicEvent], now: datetime) -> list[PublicEvent]:
    """事件的顺序：**展示优先级**（严重性 × 时效性 × 生命周期）优先，同优先级按热度。

    与核心 `clustering.sort_events` 同一口径。**必须在读侧也排一遍**：核心的排序只决定
    写库顺序，写完就被 `ORDER BY created_at DESC` 冲掉了。
    严重性和热度**不被时间或状态打折**（它们照原样返回给用户展示）；时效性和生命周期只影响顺序。
    """

    return sorted(
        rows,
        key=lambda row: (
            priority_score(
                risk_level_of(row),
                recency_weight(age_in_days(event_time_from_payload(row.date_range_json), now)),
                lifecycle_now(row, now)[0],
            ),
            float(row.heat_score or 0.0),
            int(row.id or 0),
        ),
        reverse=True,
    )


# --------------------------------------------------------------------------- 事件层检索


def query_published_events(
    db: Session,
    *,
    keyword: str = "",
    limit: int = 8,
    now: datetime | None = None,
) -> list[OpinionEvent]:
    """舆情助手的**第一层检索**：已发布（= 人工审核过）的、LLM 研判过的事件。

    命中就用它的结论；一个都不命中时调用方回落到帖子层（见 opinion_chat_service._events）。

    ## 匹配什么

    标题 / 摘要——"这个事件是关于什么的"。
    **外加它的代表帖在讲什么**，这一条是整个改造的关键：它让字面检索**传递**到语义簇。

        用户问「搬宿舍」
          → 事件标题「东校区宿舍搬迁」里没有这三个字，字面匹配不上
          → 但它的代表帖「中大东校区搬宿舍的原因找到了」有
          → 上浮到整个事件，连带拿到「宿舍搬迁」「封闭管理」这些字面毫无关系的成员

    同一件事三种说法，embedding 离线时已经认出它们是一体的；这里用一次廉价的字面命中
    去够到那个语义簇，而**不需要在请求路径上加载 embedding 模型**（那要 10~30 秒冷启动）。

    ## 刻意**不**匹配 source_keywords_json 和 top_tags_json

    同一个错误的两种写法——**弱信号不是话题证据**：

        "爬虫搜过这个词"     ≠ "帖子在讲这个词"    （source_keywords_json）
        "一条帖子打过这个标签" ≠ "这个事件是关于它的" （top_tags_json）

    `source_keywords_json` 记的是爬虫搜索时用的词。小红书搜不到「东校宿舍搬迁」就拿泛泛的
    中大帖凑数，那些帖子被盖上这个 source_keyword —— 拿它做匹配，「中山大学」一问就能
    命中搬迁事件。

    `top_tags_json` 是成员帖标签的**词频聚合**，尾巴上全是 count=1 的噪声。线上实测：
    「中大康某论文调查」的簇里有一条帖子随手打了个 #食堂（count=1），于是用户问「食堂」
    就捞回了一个论文调查事件——而它的代表帖里一条含「食堂」的都没有。

    代表帖自己的 `tags_json` 照常匹配：那是**这条帖子自己打的标签**，属于"它在讲什么"，
    不是聚合出来的词频尾巴。
    """

    now = now or datetime.now(tz=None).astimezone()
    query = db.query(PublicEvent).filter(PublicEvent.status == "published")

    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        # 代表帖命中 → 该事件命中（"上浮"）。子查询而非 join：join 会因为一个事件有多条
        # 代表帖命中而返回重复行。
        events_with_matching_note = (
            select(EventPostLink.event_id)
            .join(ProcessedPost, ProcessedPost.id == EventPostLink.processed_post_id)
            .where(
                or_(
                    ProcessedPost.title.like(like),
                    ProcessedPost.content.like(like),
                    ProcessedPost.tags_json.like(like),
                )
            )
        )
        query = query.filter(
            or_(
                PublicEvent.title.like(like),
                PublicEvent.summary.like(like),
                PublicEvent.id.in_(events_with_matching_note),
            )
        )

    rows = query.all()

    # —— 第二道：语义匹配（只在字面**颗粒无收**时才跑）——
    #
    # 字面检索的天花板：用户问「东校宿舍搬迁」，库里的事件叫「东校**区**宿舍搬迁」。
    # 差一个「区」字，LIKE 就整个匹配不上——标题、摘要、5 条代表帖，没有一个含这个
    # 连续子串。事件层返回 0，兜底层用同样的 LIKE 查帖子也是 0，用户拿到"events 为空"。
    #
    # 实测（BAAI/bge-small-zh，余弦）：
    #     东校宿舍搬迁  → 东校区宿舍搬迁  0.98   （次高 0.50）
    #     东校区换宿舍  → 东校区宿舍搬迁  0.88   ← 完全不同的说法也认得出
    #     食堂         → （无食堂事件）   0.43   ← 阈值 0.70 能正确拒绝
    #
    # **为什么字面优先、语义补位，而不是反过来**：实测「学术不端」的语义最高分是**错的**
    # 事件（课间缩短争议 0.52 > 康某论文调查 0.49），而字面通过代表帖上浮能正确命中。
    # 语义只该在字面找不到任何东西时补位——它是"认得出改写"，不是"比字面更准"。
    if not rows and keyword:
        rows = _semantic_event_rows(db, keyword)

    rows = sort_event_rows(rows, now)
    if limit and limit > 0:
        rows = rows[:limit]
    if not rows:
        return []

    notes_by_event = _representative_notes(db, [row.id for row in rows])
    return [_row_to_event(row, notes_by_event.get(row.id, []), now) for row in rows]


# 事件标题的向量缓存。标题很少变，每次提问重新 embed 7 个标题是纯浪费。
_title_vectors: dict[str, list[float]] = {}
_title_lock = threading.Lock()


def reset_title_embeddings() -> None:
    """丢弃标题向量缓存（重跑事件生成后标题会变；测试隔离也用它）。"""

    with _title_lock:
        _title_vectors.clear()


def _semantic_event_rows(db: Session, keyword: str) -> list[PublicEvent]:
    """语义匹配：把提问和事件标题都 embed，取余弦 ≥ 阈值的。

    降级路径（任一失败都返回空 -> 调用方回落到帖子层，绝不让对话报错）：
      - 关掉语义匹配（EVENT_SEMANTIC_MATCH_ENABLED=false）
      - 没装 sentence-transformers（get_embedder() 返回 None）
      - 模型加载/推理抛异常
    """

    if not EVENT_SEMANTIC_MATCH_ENABLED:
        return []
    embedder = get_embedder()
    if embedder is None:
        return []

    rows = db.query(PublicEvent).filter(PublicEvent.status == "published").all()
    if not rows:
        return []

    try:
        with _title_lock:
            missing = [row.title for row in rows if row.title and row.title not in _title_vectors]
            if missing:
                for title, vector in zip(missing, embedder(missing)):
                    _title_vectors[title] = vector
            title_vectors = {row.title: _title_vectors.get(row.title) for row in rows}
        query_vector = embedder([keyword])[0]
    except Exception:
        return []  # 模型挂了 -> 回落帖子层，对话照常

    # embed_texts 已经归一化（normalize_embeddings=True），余弦 == 点积。
    scored: list[tuple[float, PublicEvent]] = []
    for row in rows:
        vector = title_vectors.get(row.title)
        if not vector:
            continue
        scored.append((sum(a * b for a, b in zip(query_vector, vector)), row))
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))

    confident = [(score, row) for score, row in scored if score >= EVENT_SEMANTIC_MATCH_THRESHOLD]
    if confident:
        return [row for _score, row in confident]  # 算术已经很确定了，不必惊动 LLM

    # —— 第三道：LLM 裁决，只判算术拿不准的那条模糊带 ——
    #
    # 标定出的无解重叠：该命中的最低分（论文造假 0.54）比该拒绝的最高分（宿舍热水 0.56）
    # 还低。**没有任何阈值能分开它们**——因为余弦回答的是「有多像」（标量），而用户真正
    # 问的是「**是不是**这件事」（判断）。宿舍热水和宿舍火情很像但不是一回事；论文造假和
    # 康某论文调查一点不像却就是一回事。
    #
    #     可测量的用算术（余弦筛掉明显的两头）；需要判断的用 AI（只判中间那条带）。
    #
    # 带外的两头不花这个钱：≥0.65 已在上面直接采纳（8/8 全对），<0.45 直接拒绝
    # （天气 0.32 / 图书馆 0.39 / 食堂 0.43，3/3 全对）。
    top_score = scored[0][0]
    if not EVENT_JUDGE_ENABLED or top_score < EVENT_SEMANTIC_LOW_THRESHOLD:
        return []

    try:
        verdict = judge_event_match(keyword, [row.title for _score, row in scored])
    except Exception:
        return []  # 裁决挂了 -> 按余弦的原判（拒绝）-> 回落帖子层，对话照常

    if not verdict:
        return []
    return [row for _score, row in scored if row.title == verdict]


def _representative_notes(db: Session, event_ids: list[int]) -> dict[int, list[OpinionNote]]:
    """一次查完所有事件的代表帖（避免 N+1）。按 rank 升序，即热度序。"""

    from backend.services.public_opinion_adapter import processed_posts_to_notes

    if not event_ids:
        return {}

    rows = (
        db.query(EventPostLink, ProcessedPost)
        .join(ProcessedPost, ProcessedPost.id == EventPostLink.processed_post_id)
        .filter(EventPostLink.event_id.in_(event_ids))
        .order_by(EventPostLink.event_id, EventPostLink.rank)
        .all()
    )

    grouped: dict[int, list[ProcessedPost]] = {}
    for link, post in rows:
        bucket = grouped.setdefault(link.event_id, [])
        if len(bucket) < MAX_REPRESENTATIVE_NOTES:
            bucket.append(post)

    from backend.services.public_opinion_adapter import processed_post_to_agent_row

    return {
        event_id: processed_posts_to_notes(
            [processed_post_to_agent_row(post) for post in posts], warnings=[]
        )
        for event_id, posts in grouped.items()
    }


def _row_to_event(row: PublicEvent, notes: list[OpinionNote], now: datetime) -> OpinionEvent:
    """一行 `public_events` → 一个 OpinionEvent（聊天的下游全都吃这个类型）。

    LLM 研判的三样东西原样带过去：`risk_level`（不重算！）、`risk_reasons`、
    `lifecycle_judgement`。规则聚类算出来的风险是"六个电诈词 + 互动量加分"，
    重算一遍等于把 LLM 的判断扔掉。
    """

    fields = recency_fields(row, now)
    return OpinionEvent(
        event_key=row.event_key or "",
        title=row.title or "",
        summary=row.summary or "",
        category=row.topic or "",
        risk_level=risk_level_of(row),  # ← LLM 的研判，不重算
        risk_score=float(row.risk_score or 0.0),
        sentiment=row.sentiment or "neutral",
        heat_score=float(row.heat_score or 0.0),
        source_count=int(row.source_count or 0),
        first_seen_at=str(json_value(row.date_range_json, {}).get("first_seen_at") or ""),
        last_seen_at=str(json_value(row.date_range_json, {}).get("last_seen_at") or ""),
        event_time=fields["event_time"],
        age_days=fields["age_days"],
        recency_weight=fields["recency_weight"],
        member_times=member_times_from_payload(row.date_range_json),
        lifecycle=fields["lifecycle"],
        lifecycle_judgement=lifecycle_judgement_from_payload(row.date_range_json)[0],
        lifecycle_reason=fields["lifecycle_reason"],
        growth=fields["growth"],
        priority_score=fields["priority_score"],
        source_keywords=list(json_value(row.source_keywords_json, [])),
        top_tags=list(json_value(row.top_tags_json, [])),
        concerns=list(json_value(row.concerns_json, [])),
        risk_reasons=list(json_value(row.risk_reasons_json, [])),
        representative_notes=notes,
        agent_summary=row.summary or "",
    )


__all__ = [
    "MAX_REPRESENTATIVE_NOTES",
    "json_value",
    "lifecycle_now",
    "query_published_events",
    "recency_fields",
    "risk_level_of",
    "sort_event_rows",
]
