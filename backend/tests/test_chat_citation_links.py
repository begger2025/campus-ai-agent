"""引用角标和关联事件必须能点开——溯源链路的"最后一米"。

## 为什么改（2026-07-15 实测截图）

简报正文里满是 [来源:e1] [来源:p3]，用户根本不知道这是什么：编号是给
生成/校验/审校三方对口径用的内部记号，却以原始文本形式漏给了读者。
cite_map（编号 → 标题/原帖 url）其实一直随响应返回，但里面缺两样东西，
前端拿到也点不开：

    eN 条目：url 恒为空串，也没有事件 id —— 事件级引用无处可跳；
    done.events：只有标题/风险/热度，没有 id —— 「关联事件」卡片点不动。

## 修法

    _row_to_event 把 public_events.id 落进 OpinionEvent.extra["event_id"]
    （字段本来就是给这种"应用侧附加信息"留的，核心 schema 不用加列）；
    聊天响应两处带上它：cite_map["eN"]["event_id"] 与 done.events[]["id"]。
    帖子层兜底的规则聚类事件没有落库 id —— id 为 None，前端保持不可点，
    绝不能拿一个编造的 id 让用户跳到错误的事件。
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.database import Base
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.critic import ReviewResult
from backend.services.event_read_model import query_published_events
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


class ReadModelCarriesEventIdTests(unittest.TestCase):
    """事件层读出来的 OpinionEvent 必须带落库 id——前端跳工作台全靠它。"""

    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        event = PublicEvent(
            event_key="sem:link0001",
            title="东校区宿舍搬迁",
            summary="搬迁讨论。",
            status="published",
            risk_level="medium",
            heat_score=100.0,
            source_count=1,
            date_range_json=json.dumps(
                {
                    "event_time": (NOW - timedelta(days=3)).isoformat(),
                    "member_times": [(NOW - timedelta(days=3)).isoformat()],
                }
            ),
        )
        self.db.add(event)
        self.db.commit()
        self.event_id = event.id

    def test_the_database_id_rides_along_in_extra(self) -> None:
        events = query_published_events(self.db, keyword="搬迁", now=NOW)

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0].extra.get("event_id"),
            self.event_id,
            "public_events.id 必须随 OpinionEvent.extra 带出来，否则聊天没法给出可跳转的事件链接",
        )


def _published_event(event_id: int | None) -> OpinionEvent:
    return OpinionEvent(
        event_key="sem:link0001",
        title="东校区宿舍搬迁",
        summary="搬迁讨论。",
        category="campus",
        risk_level="medium",
        sentiment="negative",
        heat_score=1142.5,
        source_count=1,
        representative_notes=[
            OpinionNote(
                note_id="xhs:1",
                title="搬迁看法",
                content="通知太仓促。",
                url="https://example.com/note/1",
            )
        ],
        extra={"event_id": event_id} if event_id is not None else {},
    )


class ChatResponseLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)

    def _report(self, event: OpinionEvent) -> dict:
        service = OpinionChatService(db=None)
        with (
            patch.object(OpinionChatService, "_published_events", return_value=[event]),
            patch(
                "backend.services.opinion_chat_service.generate_llm_report",
                return_value="搬迁风险为中 [来源:e1]，帖子提到仓促 [来源:p1]。",
            ),
            patch(
                "backend.services.opinion_chat_service.review_report",
                MagicMock(return_value=ReviewResult(verdict="pass", issues=[])),
            ),
            patch(
                "backend.services.opinion_chat_service.route_intent",
                return_value=IntentRoute(intent="report", keyword="搬迁", source="llm"),
            ),
        ):
            return service.chat("给我一份搬迁简报", user_id="u1")

    def test_event_citations_carry_the_event_id(self) -> None:
        response = self._report(_published_event(49))

        self.assertEqual(
            response["citations"]["e1"].get("event_id"),
            49,
            "eN 引用必须带事件 id——事件级论断的角标才有地方可跳（工作台 ?event_id=）",
        )
        self.assertEqual(
            response["citations"]["p1"]["url"],
            "https://example.com/note/1",
            "pN 引用的原帖 url 要照旧带上",
        )

    def test_related_events_carry_the_event_id(self) -> None:
        response = self._report(_published_event(49))

        self.assertEqual(
            response["events"][0].get("id"),
            49,
            "「关联事件」卡片要能点去工作台，done.events 必须带落库 id",
        )

    def test_a_rule_clustered_event_stays_unlinkable(self) -> None:
        """帖子层兜底的规则聚类事件没有落库 id——绝不能编一个让用户跳错地方。"""

        response = self._report(_published_event(None))

        self.assertIsNone(response["events"][0].get("id"))
        self.assertNotIn(
            "event_id",
            response["citations"]["e1"],
            "没有落库 id 就别给 eN 挂跳转——宁可不可点，不可点错",
        )


if __name__ == "__main__":
    unittest.main()
