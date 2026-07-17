"""P2 审核工作台增强：批量审核 + 审核优先排序 + LLM 预审建议。

契约：
- 批量审核逐条留痕（EventReviewLog + admin_operations），单条失败不拖垮整批；
- sort=review 按"风险等级 > 热度 > 新建时间"排，专供 draft 审核动线；
- LLM 预审是建议不是决定：即算即显不落库，非法输出退回 hold（失败朝安全侧），
  未配置 LLM 时接口明确说不可用而不是 500。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import EventReviewLog, User
from backend.database import Base, get_db
from backend.main import app
from backend.models import PublicEvent
from backend.services.auth_service import get_current_user, require_admin


NOW = datetime(2026, 7, 17, 12, 0, 0)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        admin = User(id=1, username="admin", role="admin")
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        self.db = self.session_factory()
        self.addCleanup(self.db.close)

    def _event(self, title: str, *, status: str = "draft", risk: str = "low",
               heat: float = 0.0, risk_reasons: list[str] | None = None) -> PublicEvent:
        event = PublicEvent(
            event_key=f"sem:{title}", title=title, summary=f"{title}。", status=status,
            risk_level=risk, heat_score=heat,
            risk_reasons_json=json.dumps(risk_reasons or [], ensure_ascii=False),
            date_range_json=json.dumps(
                {"event_time": NOW.isoformat(), "lifecycle_judgement": "ongoing",
                 "lifecycle_reason": "仍有新帖"},
                ensure_ascii=False,
            ),
        )
        self.db.add(event)
        self.db.commit()
        return event

    def _fresh(self, event_id: int) -> PublicEvent:
        db = self.session_factory()
        try:
            return db.query(PublicEvent).filter(PublicEvent.id == event_id).one()
        finally:
            db.close()


class BatchStatusTests(_Fixture):
    def test_batch_publish_writes_per_event_review_logs(self):
        a = self._event("宿舍搬迁争议")
        b = self._event("食堂价格争议")

        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": [a.id, b.id], "status": "published",
                  "review_comment": "批量审核通过"},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["succeeded"], 2)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(self._fresh(a.id).status, "published")
        self.assertEqual(self._fresh(b.id).status, "published")

        db = self.session_factory()
        try:
            logs = db.query(EventReviewLog).all()
        finally:
            db.close()
        self.assertEqual(len(logs), 2, "批量也必须逐条留审核日志")

    def test_batch_missing_event_fails_that_item_only(self):
        a = self._event("真实事件")

        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": [a.id, 99999], "status": "rejected",
                  "review_comment": "批量驳回"},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["succeeded"], 1)
        self.assertEqual(data["failed"], 1)
        by_id = {item["id"]: item for item in data["results"]}
        self.assertTrue(by_id[a.id]["ok"])
        self.assertFalse(by_id[99999]["ok"])
        self.assertEqual(self._fresh(a.id).status, "rejected")

    def test_batch_invalid_status_is_400(self):
        a = self._event("事件")
        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": [a.id], "status": "nonsense"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_batch_empty_or_oversized_is_400(self):
        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": [], "status": "published"},
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": list(range(1, 102)), "status": "published"},
        )
        self.assertEqual(resp.status_code, 400)


class SortReviewTests(_Fixture):
    def test_sort_review_orders_risk_then_heat(self):
        low_hot = self._event("低风险高热", risk="low", heat=999.0)
        high_cold = self._event("高风险低热", risk="high", heat=1.0)
        medium = self._event("中风险", risk="medium", heat=10.0)

        resp = self.client.get("/api/admin/events", params={"sort": "review", "status": "draft"})

        self.assertEqual(resp.status_code, 200)
        titles = [item["title"] for item in resp.json()["data"]["items"]]
        self.assertEqual(titles, ["高风险低热", "中风险", "低风险高热"])

    def test_invalid_sort_is_400(self):
        resp = self.client.get("/api/admin/events", params={"sort": "bogus"})
        self.assertEqual(resp.status_code, 400)


class PrescreenServiceTests(unittest.TestCase):
    """服务层：LLM 输出的形状校验与安全兜底。"""

    def _items(self):
        return [
            {"id": 11, "title": "宿舍火灾", "summary": "东校区起火", "risk_level": "high",
             "risk_reasons": ["涉及安全"], "lifecycle": "ongoing", "source_count": 4,
             "sample_titles": ["宿舍起火了", "消防到场"]},
            {"id": 22, "title": "校园猫咪日常", "summary": "萌宠视频", "risk_level": "low",
             "risk_reasons": [], "lifecycle": "", "source_count": 1,
             "sample_titles": ["猫猫"]},
        ]

    def test_valid_output_maps_back_to_event_ids(self):
        from backend.services import event_prescreen

        fake = mock.Mock()
        fake.content = json.dumps({"items": [
            {"index": 1, "suggestion": "publish", "reason": "真实安全事件，证据充分"},
            {"index": 2, "suggestion": "reject", "reason": "个人日常内容，非舆情"},
        ]})
        with mock.patch.object(event_prescreen, "call_llm", return_value=fake):
            result = event_prescreen.prescreen_events(self._items())

        self.assertEqual(
            result,
            [
                {"id": 11, "suggestion": "publish", "reason": "真实安全事件，证据充分"},
                {"id": 22, "suggestion": "reject", "reason": "个人日常内容，非舆情"},
            ],
        )

    def test_invalid_suggestion_and_missing_index_fall_back_to_hold(self):
        from backend.services import event_prescreen

        fake = mock.Mock()
        fake.content = json.dumps({"items": [
            {"index": 1, "suggestion": "delete_everything", "reason": "??"},
        ]})
        with mock.patch.object(event_prescreen, "call_llm", return_value=fake):
            result = event_prescreen.prescreen_events(self._items())

        self.assertEqual(result[0]["suggestion"], "hold")
        self.assertEqual(result[1]["suggestion"], "hold", "模型漏答的事件必须退回 hold")

    def test_unusable_llm_output_returns_none(self):
        from backend.services import event_prescreen

        fake = mock.Mock()
        fake.content = "这不是 JSON"
        with mock.patch.object(event_prescreen, "call_llm", return_value=fake):
            self.assertIsNone(event_prescreen.prescreen_events(self._items()))

    def test_empty_input_returns_empty(self):
        from backend.services import event_prescreen

        self.assertEqual(event_prescreen.prescreen_events([]), [])


class PrescreenEndpointTests(_Fixture):
    def test_endpoint_returns_suggestions_when_available(self):
        a = self._event("宿舍火灾", risk="high", risk_reasons=["安全"])

        from backend.services import event_prescreen

        with mock.patch.object(event_prescreen, "prescreen_available", return_value=True), \
             mock.patch.object(
                 event_prescreen, "prescreen_events",
                 return_value=[{"id": a.id, "suggestion": "publish", "reason": "真实事件"}],
             ):
            resp = self.client.post(
                "/api/admin/events/prescreen", json={"event_ids": [a.id]}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["available"])
        self.assertEqual(data["items"][0]["suggestion"], "publish")

    def test_endpoint_reports_unavailable_without_key(self):
        a = self._event("事件")

        from backend.services import event_prescreen

        with mock.patch.object(event_prescreen, "prescreen_available", return_value=False):
            resp = self.client.post(
                "/api/admin/events/prescreen", json={"event_ids": [a.id]}
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertFalse(data["available"])
        self.assertEqual(data["items"], [])

    def test_endpoint_caps_batch_at_20(self):
        resp = self.client.post(
            "/api/admin/events/prescreen", json={"event_ids": list(range(1, 22))}
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
