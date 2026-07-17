"""人工事件修正：重命名 / 创建 / 删除 / 合并 / 帖子加入 / 帖子移出。

AI 提议（聚类/研判）、人工裁决（status 闸门）之后的最后一块：**人工修正**。
LLM 精修和合并裁决都会犯错，管理员必须能直接改，而不是只能驳回重来。

## 核心语义：人工编辑 = 锁（curated=True）

延续「机器绝不覆盖人的决定」（同 actor 归档语义）：任何人工修正把事件上锁——
再生成管线对 curated 行只读（persist 跳过 upsert），其成员帖退出聚类池
（否则下轮同一批帖又聚出重复事件，人工合并白做）。

## 聚合重算是纯算术

成员变化后现算：source_count=链接数、heat_score=成员热度之和、
member_times/event_time（中位数）从成员帖发布时间取。**LLM 的研判保留原值**
（risk_level/risk_reasons/lifecycle_judgement 是对内容的判断，成员微调不重跑；
管理员认为判断过时，走既有审核流程处理）。

所有函数只改 ORM 对象不 commit——事务边界在路由层（audit 与数据同事务）。
业务违规抛 CurationError（路由译成 4xx），绝不静默吞。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from backend.admin_models import EventReviewLog
from backend.models import EventComment, EventPostLink, ProcessedPost, PublicEvent


class CurationError(Exception):
    """业务违规（空标题/删已发布/空壳事件……）；携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _member_posts(db: Session, event_id: int) -> list[ProcessedPost]:
    """事件的成员帖（按链接，剔除的不算证据）。"""

    rows = (
        db.query(ProcessedPost)
        .join(EventPostLink, EventPostLink.processed_post_id == ProcessedPost.id)
        .filter(EventPostLink.event_id == event_id, ProcessedPost.excluded.is_(False))
        .all()
    )
    return rows


def recompute_event_aggregates(db: Session, event: PublicEvent) -> None:
    """成员变化后重算算术聚合；保留 date_range_json 里 LLM 研判的键。"""

    db.flush()  # 挂起的链接增删要先落到会话，否则下面的 join 数的是旧账（autoflush=False）
    posts = _member_posts(db, event.id)
    event.source_count = len(posts)
    event.heat_score = float(sum(post.heat_score or 0.0 for post in posts))

    times = sorted(
        post.publish_time for post in posts if isinstance(post.publish_time, datetime)
    )
    try:
        payload = json.loads(event.date_range_json or "{}")
    except ValueError:
        payload = {}
    if times:
        payload["member_times"] = [moment.isoformat() for moment in times]
        payload["event_time"] = times[len(times) // 2].isoformat()  # 中位数：与聚类侧同口径
        payload["first_seen_at"] = times[0].isoformat()
        payload["last_seen_at"] = times[-1].isoformat()
    event.date_range_json = json.dumps(payload, ensure_ascii=False)


def _lock(event: PublicEvent) -> None:
    event.curated = True


def rename_event(db: Session, event: PublicEvent, title: str) -> None:
    clean = (title or "").strip()
    if not clean:
        raise CurationError("事件标题不能为空")
    event.title = clean
    _lock(event)


def create_event(db: Session, title: str, post_ids: list[int]) -> PublicEvent:
    clean = (title or "").strip()
    if not clean:
        raise CurationError("事件标题不能为空")
    unique_ids = list(dict.fromkeys(int(pid) for pid in post_ids or []))
    if not unique_ids:
        raise CurationError("至少需要一条帖子作为事件证据")
    posts = (
        db.query(ProcessedPost)
        .filter(ProcessedPost.id.in_(unique_ids), ProcessedPost.excluded.is_(False))
        .all()
    )
    if len(posts) != len(unique_ids):
        raise CurationError("包含不存在或已被剔除的帖子——被剔除的帖子不能作为事件证据")

    digest = hashlib.sha1(("|".join(map(str, sorted(unique_ids))) + clean).encode()).hexdigest()[:12]
    event = PublicEvent(
        # man: 前缀：人工事件不参与快照对齐（sem: 是语义聚类的身份空间）
        event_key=f"man:{digest}",
        title=clean,
        summary=f"{clean}（管理员手工创建）",
        status="draft",  # 人工创建也走审核闸门才能对外
        curated=True,
        risk_level="low",
        date_range_json="{}",
    )
    db.add(event)
    db.flush()  # 拿 id 建链接
    by_id = {post.id: post for post in posts}
    for rank, pid in enumerate(unique_ids, start=1):
        db.add(
            EventPostLink(
                event_id=event.id,
                processed_post_id=pid,
                raw_post_id=by_id[pid].raw_post_id,
                rank=rank,
                role="manual",
            )
        )
    recompute_event_aggregates(db, event)
    return event


def delete_event(db: Session, event: PublicEvent) -> dict:
    """硬删（仅限非 published）；返回删除前快照供审计。"""

    if event.status == "published":
        raise CurationError("已发布事件是对外结论，不许直接删除——请先归档", status_code=409)
    snapshot = {
        "id": event.id,
        "event_key": event.event_key,
        "title": event.title,
        "status": event.status,
        "source_count": event.source_count,
        "heat_score": event.heat_score,
    }
    db.query(EventPostLink).filter(EventPostLink.event_id == event.id).delete()
    # 站内评论随事件一起删（不留孤儿行）：评论的语境就是这个事件，事件没了它无处安放
    db.query(EventComment).filter(EventComment.event_id == event.id).delete()
    # 审核日志也随事件删：event_id 是指向 public_events 的外键，rejected/archived 事件
    # 必带审核日志——不删则 MySQL commit 时外键违约 500（SQLite 外键默认关，测不出）
    db.query(EventReviewLog).filter(EventReviewLog.event_id == event.id).delete()
    db.delete(event)
    return snapshot


def merge_events(db: Session, target: PublicEvent, source: PublicEvent, actor: str) -> None:
    """source 的证据并入 target（去重）；source 归档注明去向——保留审计轨迹，不硬删。"""

    if target.id == source.id:
        raise CurationError("不能把事件并入它自己")
    existing = {
        link.processed_post_id
        for link in db.query(EventPostLink).filter(EventPostLink.event_id == target.id)
    }
    moved = 0
    for link in db.query(EventPostLink).filter(EventPostLink.event_id == source.id).all():
        if link.processed_post_id in existing:
            db.delete(link)  # 两边都有的帖子：留 target 的，删 source 的
            continue
        link.event_id = target.id
        link.role = "manual"
        moved += 1

    source.status = "archived"
    source.reviewed_by = actor
    source.reviewed_at = datetime.utcnow()
    source.review_comment = f"已并入事件 #{target.id}「{target.title}」（人工合并，迁移 {moved} 条证据）"
    _lock(source)  # source 也上锁：不许下一轮再生成把它从 archived 里复活

    recompute_event_aggregates(db, target)
    _lock(target)


def add_post(db: Session, event: PublicEvent, post_id: int) -> None:
    post = db.query(ProcessedPost).filter(ProcessedPost.id == post_id).first()
    if post is None:
        raise CurationError("帖子不存在", status_code=404)
    if post.excluded:
        raise CurationError("该帖已被剔除——被剔除的帖子不能作为事件证据")
    duplicate = (
        db.query(EventPostLink)
        .filter(EventPostLink.event_id == event.id, EventPostLink.processed_post_id == post_id)
        .first()
    )
    if duplicate is not None:
        raise CurationError("该帖已在事件中")
    max_rank = (
        db.query(EventPostLink.rank)
        .filter(EventPostLink.event_id == event.id)
        .order_by(EventPostLink.rank.desc())
        .first()
    )
    db.add(
        EventPostLink(
            event_id=event.id,
            processed_post_id=post.id,
            raw_post_id=post.raw_post_id,
            rank=(max_rank[0] if max_rank else 0) + 1,
            role="manual",  # 人工加入的证据，审计和展示都要能区分
        )
    )
    recompute_event_aggregates(db, event)
    _lock(event)


def remove_post(db: Session, event: PublicEvent, post_id: int) -> None:
    link = (
        db.query(EventPostLink)
        .filter(EventPostLink.event_id == event.id, EventPostLink.processed_post_id == post_id)
        .first()
    )
    if link is None:
        raise CurationError("该帖不在事件中", status_code=404)
    remaining = (
        db.query(EventPostLink).filter(EventPostLink.event_id == event.id).count()
    )
    if remaining <= 1:
        raise CurationError("这是事件的最后一条证据——没有证据的事件不是事件，请改用删除/归档")
    db.delete(link)
    recompute_event_aggregates(db, event)
    _lock(event)
