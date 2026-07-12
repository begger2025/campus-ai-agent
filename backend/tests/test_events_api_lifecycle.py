"""GET /api/events：生命周期必须**到达前端真正消费的那个顺序**，并且把状态和理由交出去。

前端 `fetchPublishedEvents()` 按返回顺序直接渲染（frontend/src/api/events.js -> OpinionView.vue），
所以"事件排序"只在 `sort_event_rows` 里生效——核心的 `sort_events` 只决定写库顺序，写完就被
`ORDER BY created_at DESC` 冲掉了（这是上一次改造实测出来的坑，两处都得改到）。

状态是**事实级判断**（读一遍帖子得出的"这事完了没有"），和 event_time 一样落在
`date_range_json` 里；年龄/权重/优先级仍然读时现算。

零网络：内存 sqlite。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models import PublicEvent
from backend.routers import api as api_router

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def date_range(event_time: str, lifecycle: str = "", reason: str = "") -> str:
    payload = {
        "first_seen_at": event_time,
        "last_seen_at": event_time,
        "event_time": event_time,
    }
    if lifecycle:
        payload["lifecycle"] = lifecycle
        payload["lifecycle_reason"] = reason
    return json.dumps(payload, ensure_ascii=False)


class EventsApiLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        db = self.session_factory()
        db.add_all(
            [
                # 3.5 个月前的火情：high/95，但**已了结**（已通报、无伤亡、已立案）。
                PublicEvent(
                    title="东校区宿舍火情",
                    status="published",
                    risk_level="high",
                    risk_score=95.0,
                    heat_score=17.0,
                    source_count=3,
                    date_range_json=date_range(
                        "2026-03-29T10:00:00", "resolved", "明火已扑灭、校方已通报、无人员伤亡"
                    ),
                ),
                # 2.1 个月前的实名举报：high/90，**悬而未决**（调查无结论）。
                PublicEvent(
                    title="中大杰青实名举报",
                    status="published",
                    risk_level="high",
                    risk_score=90.0,
                    heat_score=12.0,
                    source_count=2,
                    date_range_json=date_range(
                        "2026-05-09T10:00:00", "ongoing", "举报两月未见调查结论，校方未回应"
                    ),
                ),
                # 老数据：没有状态（改造前入库）。不许被当成"已了结"打折。
                # 与举报事件**同龄同险**，但热度高得多——改造前它靠热度兜底排在第一；
                # 只有生命周期这根轴能把"悬而未决"抬到它前面（否则这个测试不成立）。
                PublicEvent(
                    title="无状态的旧事件",
                    status="published",
                    risk_level="high",
                    risk_score=90.0,
                    heat_score=5000.0,
                    source_count=2,
                    date_range_json=date_range("2026-05-09T10:00:00"),
                ),
            ]
        )
        db.commit()
        db.close()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def rows(self) -> list[PublicEvent]:
        db = self.session_factory()
        try:
            return db.query(PublicEvent).filter(PublicEvent.status == "published").all()
        finally:
            db.close()

    def test_unresolved_event_outranks_the_resolved_older_one(self) -> None:
        ordered = api_router.sort_event_rows(self.rows(), now=NOW)

        self.assertEqual(ordered[0].title, "中大杰青实名举报")
        self.assertEqual(ordered[-1].title, "东校区宿舍火情")

    def test_unassessed_legacy_row_sits_between_them(self) -> None:
        """没有状态 = 因子 1.0（不打折也不加成）：同龄的 ongoing 压过它，它压过已了结的旧事件。"""

        ordered = [row.title for row in api_router.sort_event_rows(self.rows(), now=NOW)]

        self.assertEqual(ordered, ["中大杰青实名举报", "无状态的旧事件", "东校区宿舍火情"])

    def test_payload_exposes_lifecycle_and_reason(self) -> None:
        items = {item["title"]: item for item in self.client.get("/api/events").json()["data"]["items"]}
        report = items["中大杰青实名举报"]
        fire = items["东校区宿舍火情"]

        self.assertEqual(report["lifecycle"], "ongoing")
        self.assertEqual(report["lifecycle_reason"], "举报两月未见调查结论，校方未回应")
        self.assertEqual(fire["lifecycle"], "resolved")
        self.assertEqual(items["无状态的旧事件"]["lifecycle"], "")
        # 严重性与热度不被状态改写：展示的仍是实测值。
        self.assertEqual(fire["risk_level"], "high")
        self.assertEqual(fire["risk_score"], 95.0)
        self.assertEqual(fire["heat_score"], 17.0)

    def test_event_detail_also_carries_lifecycle(self) -> None:
        db = self.session_factory()
        event_id = db.query(PublicEvent).filter(PublicEvent.title == "中大杰青实名举报").first().id
        db.close()

        data = self.client.get(f"/api/events/{event_id}").json()["data"]

        self.assertEqual(data["lifecycle"], "ongoing")
        self.assertIn("调查结论", data["lifecycle_reason"])

    def test_priority_score_carries_the_lifecycle_factor(self) -> None:
        items = {item["title"]: item for item in self.client.get("/api/events").json()["data"]["items"]}

        # 同龄同险的两行，只差状态：优先级比正好是 2.0 / 1.0（ongoing / 未研判）。
        self.assertAlmostEqual(
            items["中大杰青实名举报"]["priority_score"],
            items["无状态的旧事件"]["priority_score"] * 2.0,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
