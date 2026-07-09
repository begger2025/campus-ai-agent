from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ChatQueryLog, ProcessedPost

NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class _StubRoute:
    """确定性路由桩：绕开 LLM/规则差异，测试只关心种子脚本自身的行为。"""

    def __init__(self, keyword: str, intent: str = "search") -> None:
        self.keyword = keyword
        self.intent = intent
        self.source = "rules"


def stub_route(message: str) -> _StubRoute:
    return _StubRoute(keyword="宿舍" if "宿舍" in message else "")


class SeedQueryLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_seeds_questions_with_routed_keyword_and_hits(self) -> None:
        from scripts.seed_query_log import seed_questions

        self.db.add(
            ProcessedPost(raw_post_id=1, platform="xhs", title="宿舍空调坏了", source_keyword="宿舍", created_at=NOW, publish_time=NOW)
        )
        self.db.commit()

        inserted = seed_questions(
            self.db,
            ["宿舍空调怎么样", "# 注释行跳过", "", "食堂饭菜如何"],
            route=stub_route,
            now=NOW,
        )
        self.db.commit()

        self.assertEqual(inserted, 2)
        rows = self.db.query(ChatQueryLog).order_by(ChatQueryLog.id).all()
        self.assertEqual(rows[0].keyword, "宿舍")
        self.assertGreaterEqual(rows[0].hit_count, 1)  # 站内有"宿舍"相关帖
        self.assertEqual(rows[0].user_id, "seed")
        self.assertEqual(rows[1].keyword, "")
        self.assertEqual(rows[1].hit_count, 0)


if __name__ == "__main__":
    unittest.main()
