"""GET /api/events：前端真正消费的那个顺序，必须按时效性排，并且把年龄交给前端。

前端 `fetchPublishedEvents()` 直接把这个列表按返回顺序渲染（frontend/src/api/events.js
-> OpinionView.vue），所以"事件排序"这件事**只在这里生效**——核心里的 `sort_events` 只决定
写库顺序，写完就被 `ORDER BY created_at DESC` 冲掉了。

年龄在**读时**现算（`now` 由请求处理函数注入），不落库：age_days 是 now 的函数，冻进数据库
第二天就是错的。库里只存 `date_range_json.event_time` 这个**事实**。

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


def date_range(event_time: str, first: str = "", last: str = "") -> str:
    return json.dumps(
        {
            "first_seen_at": first or event_time,
            "last_seen_at": last or event_time,
            "event_time": event_time,
        },
        ensure_ascii=False,
    )


class EventsApiRecencyTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        db = self.session_factory()
        db.add_all(
            [
                # 线上现况：五年前的高风险事件排在最前面（用户以为这是今天的舆情）。
                PublicEvent(
                    title="中大学生诽谤被开除",
                    status="published",
                    risk_level="high",
                    risk_score=90.0,
                    heat_score=1800.0,
                    source_count=2,
                    date_range_json=date_range("2021-06-18T12:00:00"),
                ),
                PublicEvent(
                    title="本周食堂涨价争议",
                    status="published",
                    risk_level="medium",
                    risk_score=45.0,
                    heat_score=30.0,
                    source_count=3,
                    date_range_json=date_range("2026-07-09T12:00:00"),
                ),
                PublicEvent(
                    title="宿舍热水检修",
                    status="published",
                    risk_level="low",
                    risk_score=10.0,
                    heat_score=12.0,
                    source_count=2,
                    date_range_json=date_range("2026-07-11T12:00:00"),
                ),
                PublicEvent(title="草稿事件", status="draft"),
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

    def test_recent_events_outrank_a_five_year_old_high_risk_event(self) -> None:
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json()["data"]["items"]]

        self.assertEqual(titles[-1], "中大学生诽谤被开除", titles)
        self.assertIn("本周食堂涨价争议", titles[:2])

    def test_payload_exposes_age_so_the_ui_can_show_five_years_ago(self) -> None:
        response = self.client.get("/api/events")
        items = {item["title"]: item for item in response.json()["data"]["items"]}
        stale = items["中大学生诽谤被开除"]

        self.assertEqual(stale["event_time"], "2021-06-18T12:00:00")
        self.assertGreater(stale["age_days"], 1800)
        self.assertLess(stale["recency_weight"], 0.01)
        # 严重性与热度不被时间打折：展示给用户的仍是实测值。
        self.assertEqual(stale["risk_level"], "high")
        self.assertEqual(stale["risk_score"], 90.0)
        self.assertEqual(stale["heat_score"], 1800.0)

    def test_event_detail_also_carries_age(self) -> None:
        db = self.session_factory()
        event_id = db.query(PublicEvent).filter(PublicEvent.title == "中大学生诽谤被开除").first().id
        db.close()

        response = self.client.get(f"/api/events/{event_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertGreater(data["age_days"], 1800)
        self.assertEqual(data["event_time"], "2021-06-18T12:00:00")

    def test_events_without_event_time_are_not_buried(self) -> None:
        """没有时间戳的老事件（改造前入库的行）：不知道多老 ≠ 很老，不许凭空沉底。"""

        db = self.session_factory()
        db.add(
            PublicEvent(
                title="无时间戳的旧事件",
                status="published",
                risk_level="high",
                risk_score=95.0,
                heat_score=500.0,
                date_range_json="",
            )
        )
        db.commit()
        db.close()

        response = self.client.get("/api/events")
        items = {item["title"]: item for item in response.json()["data"]["items"]}
        unknown = items["无时间戳的旧事件"]
        self.assertIsNone(unknown["age_days"])
        self.assertEqual(unknown["recency_weight"], 1.0)

        titles = [item["title"] for item in response.json()["data"]["items"]]
        self.assertEqual(titles[0], "无时间戳的旧事件", titles)

    def test_ranking_is_computed_against_the_injected_now(self) -> None:
        """排序里的"现在"来自请求时刻，不是模块导入时刻——时间必须是可注入的。"""

        rows = self.session_factory().query(PublicEvent).filter(
            PublicEvent.status == "published"
        ).all()
        ordered = api_router.sort_event_rows(
            rows, now=datetime(2021, 6, 19, tzinfo=timezone.utc)
        )
        # 站在 2021-06-19 看，诽谤事件才是"当天的舆情"，另外两条还没发生。
        self.assertEqual(ordered[0].title, "中大学生诽谤被开除")


if __name__ == "__main__":
    unittest.main()
