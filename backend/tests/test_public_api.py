from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import UserFeedback
from backend.database import Base, get_db
from backend.main import app
from backend.models import PublicEvent


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class PublicApiTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        db = self.session_factory()
        db.add_all(
            [
                PublicEvent(title="已发布事件A", status="published", heat_score=90, risk_level="high"),
                PublicEvent(title="已发布事件B", status="published", heat_score=50),
                PublicEvent(title="草稿事件", status="draft"),
                PublicEvent(title="已驳回事件", status="rejected"),
            ]
        )
        db.commit()
        self.draft_id = db.query(PublicEvent).filter(PublicEvent.status == "draft").first().id
        self.published_id = (
            db.query(PublicEvent).filter(PublicEvent.status == "published").first().id
        )
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


class PublicEventsApiTest(PublicApiTestBase):
    def test_events_list_only_returns_published(self) -> None:
        response = self.client.get("/api/events")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        titles = {item["title"] for item in data["items"]}
        self.assertEqual(titles, {"已发布事件A", "已发布事件B"})

    def test_event_detail_returns_published_event(self) -> None:
        response = self.client.get(f"/api/events/{self.published_id}")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["raw_id"], self.published_id)
        self.assertIn("representative_posts", data)

    def test_draft_event_detail_is_hidden_from_public(self) -> None:
        response = self.client.get(f"/api/events/{self.draft_id}")

        self.assertEqual(response.status_code, 404)

    def test_unknown_event_detail_is_404(self) -> None:
        response = self.client.get("/api/events/99999")

        self.assertEqual(response.status_code, 404)

    def test_events_are_public_without_token(self) -> None:
        # 游客浏览是产品承诺：这些端点不得要求认证
        self.assertEqual(self.client.get("/api/events").status_code, 200)
        self.assertEqual(self.client.get(f"/api/events/{self.published_id}").status_code, 200)


class FeedbackApiTest(PublicApiTestBase):
    def test_submit_feedback_persists_pending_row(self) -> None:
        response = self.client.post(
            "/api/feedback",
            json={
                "feedback_type": "correction",
                "content": "事件描述有误",
                "user_id": "tester",
                "target_type": "public_event",
                "target_id": str(self.published_id),
            },
        )

        self.assertEqual(response.status_code, 200)
        db = self.session_factory()
        row = db.query(UserFeedback).one()
        db.close()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.content, "事件描述有误")
        self.assertEqual(row.target_type, "public_event")

    def test_empty_content_is_422(self) -> None:
        response = self.client.post("/api/feedback", json={"content": ""})

        self.assertEqual(response.status_code, 422)


class AdminAuthGateTest(PublicApiTestBase):
    """管理端点必须拒绝无 token 请求（各端点抽查）。"""

    def test_admin_endpoints_require_token(self) -> None:
        for path in ("/api/admin/overview", "/api/admin/events", "/api/admin/users", "/api/admin/raw-posts"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)


if __name__ == "__main__":
    unittest.main()
