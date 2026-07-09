from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ChatQueryLog
from backend.services.auth_service import get_current_user


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ChatQueryLogModelTest(unittest.TestCase):
    def test_table_creates_and_row_inserts_with_defaults(self) -> None:
        # 表必须在 Base.metadata 里（SQLite 演示快照 create_all 依赖这一点）
        db = make_session_factory()()
        db.add(ChatQueryLog(user_id="7", message="宿舍空调怎么样", intent="search", keyword="宿舍", hit_count=2))
        db.commit()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.keyword, "宿舍")
        self.assertEqual(row.hit_count, 2)
        self.assertIsNotNone(row.created_at)
        db.close()


CANNED_CHAT = {
    "intent": "hotspots",
    "keyword": "宿舍",
    "answer": "回答内容",
    "route_source": "rules",
    "events": [{"title": "a"}, {"title": "b"}],
}


class ChatEndpointLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: User(id=7, username="tester", role="user")
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_chat_success_writes_query_log(self, service_cls) -> None:
        service_cls.return_value.chat.return_value = dict(CANNED_CHAT)

        response = self.client.post("/api/agent/public/chat", json={"message": "宿舍最近有什么热点"})

        self.assertEqual(response.status_code, 200)
        db = self.session_factory()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.user_id, "7")
        self.assertEqual(row.message, "宿舍最近有什么热点")
        self.assertEqual(row.intent, "hotspots")
        self.assertEqual(row.keyword, "宿舍")
        self.assertEqual(row.hit_count, 2)  # len(events)
        db.close()

    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_search_intent_counts_notes(self, service_cls) -> None:
        service_cls.return_value.chat.return_value = {
            "intent": "search",
            "keyword": "",
            "answer": "已找到 1 条",
            "route_source": "rules",
            "events": [],
            "notes": [{"title": "n1"}],
        }

        self.client.post("/api/agent/public/chat", json={"message": "随便看看"})

        db = self.session_factory()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.hit_count, 1)
        self.assertEqual(row.keyword, "")
        db.close()

    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_search_fallback_echoed_message_is_not_logged_as_keyword(self, service_cls) -> None:
        # search 兜底把整句回显为 keyword 时，不得把整句当话题词入库（会污染需求信号）
        service_cls.return_value.chat.return_value = {
            "intent": "search",
            "keyword": "校医院预约难吗",
            "answer": "已找到 0 条相关校园公开内容。",
            "route_source": "rules",
            "events": [],
            "notes": [],
        }

        self.client.post("/api/agent/public/chat", json={"message": "校医院预约难吗"})

        db = self.session_factory()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.keyword, "")
        self.assertEqual(row.intent, "search")
        db.close()

    @mock.patch("backend.routers.agent_public.record_chat_query", side_effect=RuntimeError("log db down"))
    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_log_failure_does_not_break_chat(self, service_cls, _record) -> None:
        service_cls.return_value.chat.return_value = dict(CANNED_CHAT)

        response = self.client.post("/api/agent/public/chat", json={"message": "宿舍最近有什么热点"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
        self.assertEqual(response.json()["data"]["answer"], "回答内容")


if __name__ == "__main__":
    unittest.main()
