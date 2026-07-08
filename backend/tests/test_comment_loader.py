from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost
from backend.services.comment_loader import fetch_top_comments
from backend.services.public_opinion_adapter import query_agent_rows


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_comment_table(db, rows: list[tuple[str, str, str]]) -> None:
    """建 MediaCrawler 原生评论表的最小版本并播种 (note_id, content, like_count)。"""

    db.execute(
        text(
            "CREATE TABLE xhs_note_comment ("
            "id INTEGER PRIMARY KEY, note_id TEXT, content TEXT, "
            "like_count TEXT, create_time BIGINT)"
        )
    )
    for i, (note_id, content, like_count) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO xhs_note_comment (id, note_id, content, like_count, create_time) "
                "VALUES (:i, :n, :c, :l, :t)"
            ),
            {"i": i, "n": note_id, "c": content, "l": like_count, "t": 1700000000000 + i},
        )
    db.commit()


class FetchTopCommentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

    def test_returns_top_liked_comments_per_note(self) -> None:
        db = self.session_factory()
        create_comment_table(
            db,
            [
                ("n1", "低赞评论", "2"),
                ("n1", "高赞评论", "99"),
                ("n1", "中赞评论", "10"),
                ("n1", "第四条评论", "1"),
                ("n2", "另一帖的评论", "5"),
            ],
        )

        result = fetch_top_comments(db, ["n1", "n2"], per_note=3)
        db.close()

        self.assertEqual(result["n1"][0], "高赞评论")
        self.assertEqual(len(result["n1"]), 3)
        self.assertEqual(result["n2"], ["另一帖的评论"])

    def test_missing_table_returns_empty(self) -> None:
        # SQLite 演示快照没有 MediaCrawler 原生表——必须优雅降级而不是抛错
        db = self.session_factory()
        result = fetch_top_comments(db, ["n1"])
        db.close()

        self.assertEqual(result, {})

    def test_empty_note_ids_short_circuits(self) -> None:
        db = self.session_factory()
        result = fetch_top_comments(db, [])
        db.close()

        self.assertEqual(result, {})


class QueryAgentRowsWithCommentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        db = self.session_factory()
        db.add(
            ProcessedPost(
                raw_post_id=1,
                platform="xhs",
                note_id="n1",
                title="食堂排队",
                content="中午排队很久。",
                heat_score=10.0,
            )
        )
        db.commit()
        db.close()

    def test_rows_carry_top_comments_when_table_present(self) -> None:
        db = self.session_factory()
        create_comment_table(db, [("n1", "评论区都在吐槽", "50")])

        rows = query_agent_rows(db, keyword="", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], ["评论区都在吐槽"])

    def test_prefixed_note_id_still_matches_bare_comment_note_id(self) -> None:
        # 真实库口径：processed_posts.note_id 是 "xhs:68d5..."，评论表是裸 "68d5..."
        db = self.session_factory()
        db.add(
            ProcessedPost(
                raw_post_id=2,
                platform="xhs",
                note_id="xhs:68d53ba8",
                title="带前缀的帖子",
                content="正文。",
                heat_score=5.0,
            )
        )
        db.commit()
        create_comment_table(db, [("68d53ba8", "裸ID评论", "9")])

        rows = query_agent_rows(db, keyword="带前缀", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], ["裸ID评论"])

    def test_rows_default_to_empty_comments_without_table(self) -> None:
        db = self.session_factory()
        rows = query_agent_rows(db, keyword="", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], [])


if __name__ == "__main__":
    unittest.main()
