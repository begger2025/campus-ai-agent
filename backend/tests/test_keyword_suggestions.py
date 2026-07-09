from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ChatQueryLog, ProcessedPost
from backend.services.auth_service import get_current_user
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions

NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _post(raw_post_id: int, source_keyword: str, days_ago: int, likes: int, tags_json: str = "") -> ProcessedPost:
    moment = NOW - timedelta(days=days_ago)
    return ProcessedPost(
        raw_post_id=raw_post_id,
        platform="xhs",
        title=f"{source_keyword}相关帖子{raw_post_id}",
        source_keyword=source_keyword,
        like_count=likes,
        tags_json=tags_json,
        publish_time=moment,
        created_at=moment,
    )


class KeywordSuggestionAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_empty_database_returns_empty_suggestions(self) -> None:
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)
        self.assertEqual(data["meta"]["post_count"], 0)

    def test_end_to_end_four_signals(self) -> None:
        # A+B：宿舍空调被问 3 次、命中 0，从未爬过 → 应登顶
        for i in range(3):
            self.db.add(
                ChatQueryLog(
                    user_id="7",
                    message="宿舍空调怎么样",
                    intent="opinion_answer",
                    keyword="宿舍空调",
                    hit_count=0,
                    created_at=NOW - timedelta(days=1, hours=i),
                )
            )
        # C：食堂 3 天前爬过、内容热 → heat 信号且已降权
        # D：这些帖子带"期末周"标签，从未作为关键词爬过 → discovery
        self.db.add(_post(1, "食堂", 3, 500, tags_json='["期末周"]'))
        self.db.add(_post(2, "食堂", 3, 300, tags_json='["期末周"]'))
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertEqual(data["suggestions"][0]["signals"], ["demand", "gap"])
        self.assertIn("heat", by_kw["食堂"]["signals"])
        self.assertIn("已降权", by_kw["食堂"]["reason"])
        self.assertEqual(by_kw["期末周"]["signals"], ["discovery"])
        self.assertEqual(data["meta"]["query_count"], 3)
        self.assertEqual(data["meta"]["post_count"], 2)

    def test_broken_tags_json_is_tolerated(self) -> None:
        self.db.add(_post(1, "食堂", 3, 500, tags_json="not-json"))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual([s["keyword"] for s in data["suggestions"]], ["食堂"])

    def test_queries_without_keyword_are_skipped(self) -> None:
        self.db.add(ChatQueryLog(user_id="7", message="综合分析一下", intent="complex_analysis", keyword="", hit_count=0, created_at=NOW))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)


class KeywordSuggestionsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def login_as(self, role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: User(id=1, username=f"test_{role}", role=role)

    def test_requires_token(self) -> None:
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 401)

    def test_normal_user_is_forbidden(self) -> None:
        self.login_as("user")
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 403)

    def test_admin_gets_suggestions_payload(self) -> None:
        self.login_as("admin")
        db = self.session_factory()
        db.add(ChatQueryLog(user_id="1", message="宿舍空调怎么样", intent="search", keyword="宿舍空调", hit_count=0, created_at=datetime.utcnow()))
        db.commit()
        db.close()

        response = self.client.get("/api/admin/keyword-suggestions?days=30&top=5")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertIn("meta", data)

    def test_empty_data_returns_empty_list(self) -> None:
        self.login_as("admin")
        response = self.client.get("/api/admin/keyword-suggestions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
