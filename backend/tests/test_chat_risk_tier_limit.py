"""风险问答的截断必须发生在**风险排序之后**。

## 线上实况（2026-07-13 审核，S10 样例）

问「最近有什么风险」，返回的 8 个事件里有 low 风险的「中大火箭试验成功」，
却没有 high 风险的「刘一阳去世」（published）。

机制：`_events()` 按**展示优先级**（severity × recency × lifecycle）截断到
EVENT_TIER_LIMIT=8，`_risk_sorted_events` 再在截断后的名单里按风险重排。
一个年头久的 high 事件（时效权重 0.5^(age/21) 趋零）在优先级序里垫底，先被截掉；
它压根进不了风险排序的候选。

问风险的人要的是**风险全集**，不是时效加权后的前 8——截断键和排序键必须一致。
published 事件量级很小（几十个），风险问答全量取回再按风险截断，代价可忽略。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.opinion_chat_service import EVENT_TIER_LIMIT, OpinionChatService


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


class RiskTierLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()

        # 8 个"新但低风险"的事件：时效权重高 → 优先级序里占满前 8 个坑
        for i in range(EVENT_TIER_LIMIT):
            self.db.add(
                PublicEvent(
                    event_key=f"sem:recent{i:02d}",
                    title=f"近期低风险事件{i}",
                    summary="近期讨论。",
                    status="published",
                    risk_level="low",
                    risk_score=10.0,
                    heat_score=100.0 + i,
                    source_count=2,
                    date_range_json=json.dumps({"event_time": _iso(2), "member_times": [_iso(2)]}),
                )
            )
        # 1 个"老但高风险"的事件：0.5^(300/21) 让它的优先级趋零 → 老实现里先被截掉
        self.db.add(
            PublicEvent(
                event_key="sem:oldhigh1",
                title="刘一阳去世",
                summary="中大体育部副教授去世相关讨论。",
                status="published",
                risk_level="high",
                risk_score=85.0,
                heat_score=50.0,
                source_count=5,
                date_range_json=json.dumps({"event_time": _iso(300), "member_times": [_iso(300)]}),
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_an_old_high_risk_event_survives_into_the_risk_answer(self):
        service = OpinionChatService(self.db)

        titles = [event.title for event in service._risk_sorted_events("")[:EVENT_TIER_LIMIT]]

        self.assertIn(
            "刘一阳去世",
            titles,
            "high 风险事件被展示优先级的截断挡在风险问答之外了（low 的新事件反而在列）——"
            "截断必须发生在风险排序之后",
        )
        self.assertEqual(
            titles[0],
            "刘一阳去世",
            "风险问答按风险从高到低排，唯一的 high 必须排第一",
        )


if __name__ == "__main__":
    unittest.main()
