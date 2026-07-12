"""事件列表上的两个可见缺陷（答辩前发现，两个都出现在已发布的事件列表里）：

1. **事件情感取"正面压倒负面"而不是取多数**（`aggregate_sentiment`）：
   原实现里 `positive` 只和 `negative` 比大小，**完全无视 neutral**。于是
   「东校区宿舍火灾」（3 条中性事实播报 + 1 条被误聚进来的无关正面帖）被标成
   `positive`——一条正面帖能压过任意多条中性帖（1 正 + 99 中 也是 positive）。
   舆情平台把宿舍火灾标成"正面"，答辩第一次点击就会挂。

2. **被系统自动归档的事件永远回不来**（`upsert_public_events` / `archive_stale_draft_events`）：
   `archive_stale_draft_events` 用 `admin_user_id="system"` 自动归档失活草稿，而
   `REVIEW_LOCKED_STATUSES` 又把 `archived` 一律视为"人类决定"锁死。结果机器自己
   归档的事件，即使下一轮分析重新检出（内容更好、标题更好），状态也永远停在 archived。
   「中大校区与宿舍环境」「中大开学省凳走红」今天就是这样被卡住、只能手工救回的。
   锁的本意是**机器不能覆盖人的决定**——机器自己的决定不该享受同样的保护。
"""

from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.agent.public_opinion_core.sentiment_risk import aggregate_sentiment
from backend.admin_models import EventReviewLog
from backend.database import Base
from backend.models import PublicEvent
from backend.services.public_opinion_adapter import (
    SYSTEM_REVIEWER,
    archive_stale_draft_events,
    upsert_public_events,
)


def note(sentiment: str, note_id: str = "n") -> OpinionNote:
    return OpinionNote(note_id=note_id, title="t", content="c", sentiment=sentiment)


def notes(*labels: str) -> list[OpinionNote]:
    return [note(label, f"n{i}") for i, label in enumerate(labels)]


class AggregateSentimentTest(unittest.TestCase):
    """事件情感 = 真实多数派；负面放大规则保留；平票必须确定性。"""

    def test_fire_event_with_three_neutral_one_positive_is_neutral(self) -> None:
        """线上复现：「东校区宿舍火灾」3 中性事实播报 + 1 条无关正面帖。"""
        self.assertEqual(aggregate_sentiment(notes("neutral", "neutral", "neutral", "positive")), "neutral")

    def test_one_positive_cannot_outweigh_many_neutral(self) -> None:
        """1 正 + 99 中：原实现返回 positive（positive 只和 negative 比）。"""
        self.assertEqual(aggregate_sentiment(notes("positive", *(["neutral"] * 99))), "neutral")

    def test_positive_majority_is_still_positive(self) -> None:
        self.assertEqual(aggregate_sentiment(notes("positive", "positive", "positive", "neutral")), "positive")

    def test_negative_amplification_is_preserved(self) -> None:
        """少数负面照样放大成 negative（这条规则是**故意**的，不许弱化）。"""
        # 2 负 + 2 正：negative_total=2 >= max(2, 4//3)=2
        self.assertEqual(aggregate_sentiment(notes("negative", "positive", "positive", "negative")), "negative")
        # 10 条里 4 条负面（其余全正）：4 >= max(2, 3)
        self.assertEqual(aggregate_sentiment(notes(*(["negative"] * 4), *(["positive"] * 6))), "negative")
        # controversial 计入负面总量
        self.assertEqual(
            aggregate_sentiment(notes("controversial", "controversial", "positive", "positive")), "negative"
        )

    def test_tie_is_deterministic_and_does_not_depend_on_insertion_order(self) -> None:
        """平票不许由 Counter.most_common 的插入顺序决定——这是要落库、要展示的值。"""
        first = aggregate_sentiment(notes("neutral", "neutral", "positive", "positive"))
        second = aggregate_sentiment(notes("positive", "positive", "neutral", "neutral"))
        self.assertEqual(first, second, "同样的票数，换个顺序就换答案")
        # 平票时取更保守的一侧：不能因为顺序碰巧就宣布"正面"
        self.assertEqual(first, "neutral")

    def test_empty_notes_stay_neutral(self) -> None:
        self.assertEqual(aggregate_sentiment([]), "neutral")


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def event_payload(event_key: str, title: str) -> dict:
    return {
        "event_key": event_key,
        "title": title,
        "summary": "新一轮分析的摘要",
        "topic": "campus",
        "event_type": "campus",
        "sentiment": "neutral",
        "risk_level": "low",
        "risk_score": 1.0,
        "heat_score": 2.0,
        "source_count": 7,
        "status": "draft",
        "reviewed_by": "",
        "reviewed_at": None,
        "review_comment": "",
    }


class ReviewLockTest(unittest.TestCase):
    """人的决定锁死；机器自己的自动归档在被重新检出时必须放行回 draft。"""

    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        self.db = self.session_factory()
        self.addCleanup(self.db.close)

    def seed(self, **kwargs) -> PublicEvent:
        event = PublicEvent(
            event_key=kwargs.pop("event_key", "sem:x"),
            title=kwargs.pop("title", "旧标题"),
            summary="旧摘要",
            source_count=2,
            **kwargs,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def test_system_archived_event_returns_to_draft_when_redetected(self) -> None:
        """「中大校区与宿舍环境」的真实遭遇：机器归档 → 重新检出 → 必须回 draft。"""
        self.seed(
            event_key="sem:dorm",
            status="archived",
            reviewed_by=SYSTEM_REVIEWER,
            reviewed_at=datetime(2026, 7, 11, 10, 0, 0),
            review_comment="自动归档：本次全量分析未再出现（陈旧草稿）",
        )

        _, statuses = upsert_public_events(self.db, [event_payload("sem:dorm", "中大校区与宿舍环境")])

        self.assertEqual(statuses["sem:dorm"], "draft", "系统自动归档的事件被重新检出后必须回到草稿待人工复核")
        row = self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:dorm").one()
        self.assertEqual(row.status, "draft")
        self.assertEqual(row.title, "中大校区与宿舍环境", "复活的事件必须带上新一轮的内容")
        # 系统留下的归档批注必须清掉，否则草稿上挂着一条"已自动归档"的评语
        self.assertEqual(row.reviewed_by, "")
        self.assertIsNone(row.reviewed_at)
        self.assertEqual(row.review_comment, "")
        # 复活要留痕
        logs = self.db.query(EventReviewLog).filter(EventReviewLog.event_id == row.id).all()
        self.assertEqual(
            [(log.old_status, log.new_status, log.reviewer_id) for log in logs],
            [("archived", "draft", SYSTEM_REVIEWER)],
        )

    def test_human_archived_event_is_never_resurrected(self) -> None:
        self.seed(
            event_key="sem:junk",
            status="archived",
            reviewed_by="alice",
            reviewed_at=datetime(2026, 7, 11, 10, 0, 0),
            review_comment="人工归档：与校园无关",
        )

        _, statuses = upsert_public_events(self.db, [event_payload("sem:junk", "新标题")])

        self.assertEqual(statuses["sem:junk"], "archived", "人工归档的事件不许被机器复活")
        row = self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:junk").one()
        self.assertEqual(row.status, "archived")
        self.assertEqual(row.reviewed_by, "alice")
        self.assertEqual(row.review_comment, "人工归档：与校园无关")

    def test_human_published_and_rejected_events_stay_locked(self) -> None:
        self.seed(event_key="sem:pub", status="published", reviewed_by="bob", review_comment="发布")
        self.seed(event_key="sem:rej", status="rejected", reviewed_by="bob", review_comment="驳回")

        _, statuses = upsert_public_events(
            self.db, [event_payload("sem:pub", "新标题"), event_payload("sem:rej", "新标题")]
        )

        self.assertEqual(statuses["sem:pub"], "published")
        self.assertEqual(statuses["sem:rej"], "rejected")
        rows = {row.event_key: row for row in self.db.query(PublicEvent).all()}
        self.assertEqual(rows["sem:pub"].reviewed_by, "bob")
        self.assertEqual(rows["sem:rej"].reviewed_by, "bob")

    def test_auto_archive_stamps_the_system_actor_on_the_event(self) -> None:
        """自动归档必须把 actor 写在事件行上——不然事后分不清是谁归档的。"""
        self.seed(event_key="sem:stale", status="draft")

        archived = archive_stale_draft_events(self.db, {"sem:other"})

        self.assertEqual(archived, 1)
        row = self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:stale").one()
        self.assertEqual(row.status, "archived")
        self.assertEqual(row.reviewed_by, SYSTEM_REVIEWER)

    def test_auto_archived_then_redetected_round_trip(self) -> None:
        """端到端：草稿被自动归档 → 下一轮重新检出 → 回到 draft。"""
        self.seed(event_key="sem:bench", title="中大开学省凳走红", status="draft")
        archive_stale_draft_events(self.db, {"sem:other"})

        _, statuses = upsert_public_events(self.db, [event_payload("sem:bench", "中大开学省凳走红")])

        self.assertEqual(statuses["sem:bench"], "draft")


if __name__ == "__main__":
    unittest.main()
