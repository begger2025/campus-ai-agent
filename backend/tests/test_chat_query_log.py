from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ChatQueryLog


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


if __name__ == "__main__":
    unittest.main()
