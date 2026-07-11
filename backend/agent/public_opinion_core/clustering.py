"""Rule-based event clustering for campus public opinion notes."""

from __future__ import annotations

from collections import Counter, defaultdict

from .normalizer import note_text
from .platform_weights import note_ranking_score
from .schemas import OpinionEvent, OpinionNote
from .sentiment_risk import aggregate_risk_level, aggregate_sentiment


EVENT_RULES: list[tuple[str, str, set[str]]] = [
    (
        "campus_safety",
        "校园安全与防诈骗提醒",
        {"校园安全", "诈骗", "防诈骗", "短信", "缴费", "路灯", "夜间", "巡逻", "门禁", "陌生人", "尾随", "安全讲座"},
    ),
    (
        "canteen_life",
        "食堂排队与价格反馈",
        {"食堂", "饭堂", "价格", "卫生", "错峰", "窗口", "餐盘", "轻食", "套餐"},
    ),
    (
        "course_schedule",
        "课程安排与教务反馈",
        {"课程安排", "课表", "考试", "选课", "补退选", "教务", "作业", "实验课", "问卷", "维护"},
    ),
    (
        "dorm_life",
        "宿舍热水与后勤维修反馈",
        {"宿舍", "热水", "后勤", "维修", "洗衣房", "停水"},
    ),
]


def _note_search_text(note: OpinionNote) -> str:
    extra_values = []
    if isinstance(note.extra, dict):
        extra_values.extend(str(value) for value in note.extra.values())
    return " ".join([note_text(note), " ".join(extra_values)])


def classify_event(note: OpinionNote) -> tuple[str, str]:
    text = _note_search_text(note)
    for category, title, words in EVENT_RULES:
        if any(word in text for word in words):
            return category, title
    if note.source_keyword:
        return f"keyword:{note.source_keyword}", f"{note.source_keyword}相关讨论"
    return "general", "其他校园公共信息"


def _date_range(notes: list[OpinionNote]) -> tuple[str, str]:
    values = sorted(
        value
        for note in notes
        for value in [note.publish_time or note.publish_date]
        if value
    )
    if not values:
        return "", ""
    return values[0], values[-1]


def _top_tags(notes: list[OpinionNote]) -> list[dict[str, int | str]]:
    counter: Counter[str] = Counter()
    for note in notes:
        counter.update(note.tags or note.keywords)
    return [{"tag": tag, "count": count} for tag, count in counter.most_common(10)]


def _source_keywords(notes: list[OpinionNote]) -> list[str]:
    counter: Counter[str] = Counter()
    for note in notes:
        if note.source_keyword:
            counter[note.source_keyword] += 1
    return [keyword for keyword, _ in counter.most_common()]


def note_rank_key(note: OpinionNote) -> tuple[float, float, float]:
    """帖子之间比大小的统一口径：ranking_score -> heat_rank -> heat_score。

    - `ranking_score` = 平台先验权重 × 平台内百分位（见 platform_weights）。它是**唯一**
      同时兼顾"平台内公平"和"跨平台真实触达"的量：heat_score 跨平台不可比（xhs 中位 3924 /
      weibo 3，拿它挑代表帖等于代表帖永远来自小红书），而裸 heat_rank 又把量级全丢了
      （3 赞的 weibo 95 分位帖 == 10 万赞的 xhs 95 分位帖）。
    - 后两级是**老数据兜底**：未归一化的行 heat_rank 为 0，ranking_score 随之为 0，此时
      退回 heat_rank、再退回 heat_score 比——不会因为改造把既有顺序打乱成随机。
    """

    return (note_ranking_score(note), note.heat_rank, note.heat_score)


def _summary(event_title: str, notes: list[OpinionNote]) -> str:
    top_note = max(notes, key=note_rank_key)
    platforms = sorted({note.platform for note in notes if note.platform})
    platform_text = "、".join(platforms) if platforms else "多平台"
    return f"{event_title}共聚合 {len(notes)} 条内容，来源覆盖 {platform_text}，代表内容为“{top_note.title}”。"


def _agent_summary(category: str, risk_level: str, concerns: list[str]) -> str:
    concern_text = "、".join(concerns[:3]) if concerns else "校园公共反馈"
    action_map = {
        "campus_safety": "建议优先由保卫处或学院发布正式提醒，并持续跟踪处置反馈。",
        "canteen_life": "建议后勤部门核查高峰排队、价格说明和卫生反馈，并公开优化进度。",
        "course_schedule": "建议教务部门集中回应课表、考试和补退选问题，降低信息不确定性。",
        "dorm_life": "建议后勤部门核查宿舍设施状态，并通过稳定渠道同步维修进度。",
    }
    action = action_map.get(category, "建议相关部门持续观察讨论变化并及时回应。")
    return f"风险等级为 {risk_level}，主要关注点为 {concern_text}。{action}"


def build_event_from_group(event_key: str, title: str, category: str, group_notes: list[OpinionNote]) -> OpinionEvent:
    """Aggregate one group of notes into an OpinionEvent.

    Shared by rule clustering and semantic clustering so both paths produce
    structurally identical events.
    """

    # 代表帖是"选 top-N"，按可跨平台比较的 ranking_score 挑。
    sorted_notes = sorted(group_notes, key=note_rank_key, reverse=True)
    first_seen, last_seen = _date_range(group_notes)
    risk_level, risk_score, risk_reasons, concerns = aggregate_risk_level(group_notes)
    # heat_score 仍是成员原始热度之和（展示用，公式不动）；heat_rank 是成员百分位之和；
    # ranking_score 是成员加权排序分之和，事件之间排序用它——同样保留"帖子越多越热"的语义，
    # 但既不被高互动量平台绑架（heat_score 的毛病），也不把量级抹平（裸 heat_rank 的毛病）。
    heat_score = round(sum(note.heat_score for note in group_notes), 2)
    heat_rank = round(sum(note.heat_rank for note in group_notes), 2)
    ranking = round(sum(note_ranking_score(note) for note in group_notes), 2)

    return OpinionEvent(
        event_key=event_key,
        title=title,
        summary=_summary(title, group_notes),
        category=category,
        risk_level=risk_level,
        sentiment=aggregate_sentiment(group_notes),
        heat_score=heat_score,
        heat_rank=heat_rank,
        ranking_score=ranking,
        source_count=len(group_notes),
        risk_score=risk_score,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        source_keywords=_source_keywords(group_notes),
        top_tags=_top_tags(group_notes),
        concerns=concerns,
        risk_reasons=risk_reasons,
        representative_notes=sorted_notes[:5],
        agent_summary=_agent_summary(category, risk_level, concerns),
    )


def sort_events(events: list[OpinionEvent]) -> list[OpinionEvent]:
    """事件排序：风险优先，同风险按 ranking_score（平台权重 × 平台内百分位）。

    兜底链和帖子一致：ranking_score -> heat_rank -> heat_score，老数据不会退化成随机顺序。
    """

    risk_rank = {"high": 3, "medium": 2, "low": 1}
    return sorted(
        events,
        key=lambda event: (
            risk_rank.get(event.risk_level, 0),
            event.ranking_score,
            event.heat_rank,
            event.heat_score,
        ),
        reverse=True,
    )


def cluster_notes(notes: list[OpinionNote]) -> list[OpinionEvent]:
    groups: dict[tuple[str, str], list[OpinionNote]] = defaultdict(list)
    for note in notes:
        groups[classify_event(note)].append(note)

    events = [
        build_event_from_group(category, title, category, group_notes)
        for (category, title), group_notes in groups.items()
    ]
    return sort_events(events)
