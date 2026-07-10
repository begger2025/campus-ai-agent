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


def create_xhs_comment_table(db, rows: list[tuple[str, str, str]]) -> None:
    """xhs：关联列 note_id、点赞列 like_count。rows=(note_id, content, like_count)。"""

    db.execute(
        text(
            "CREATE TABLE xhs_note_comment ("
            "id INTEGER PRIMARY KEY, note_id TEXT, content TEXT, "
            "like_count TEXT, add_ts BIGINT)"
        )
    )
    for i, (note_id, content, like_count) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO xhs_note_comment (id, note_id, content, like_count, add_ts) "
                "VALUES (:i, :n, :c, :l, :t)"
            ),
            {"i": i, "n": note_id, "c": content, "l": like_count, "t": 1700000000000 + i},
        )
    db.commit()


def create_weibo_comment_table(db, rows: list[tuple[str, str, str, str]]) -> None:
    """weibo：点赞列 comment_like_count（不是 like_count）。rows=(note_id, content, comment_like_count, like_count)。"""

    db.execute(
        text(
            "CREATE TABLE weibo_note_comment ("
            "id INTEGER PRIMARY KEY, note_id TEXT, content TEXT, "
            "comment_like_count TEXT, like_count TEXT, add_ts BIGINT)"
        )
    )
    for i, (note_id, content, clc, lc) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO weibo_note_comment "
                "(id, note_id, content, comment_like_count, like_count, add_ts) "
                "VALUES (:i, :n, :c, :clc, :lc, :t)"
            ),
            {"i": i, "n": note_id, "c": content, "clc": clc, "lc": lc, "t": 1700000000000 + i},
        )
    db.commit()


def create_tieba_comment_table(db, rows: list[tuple[str, str]]) -> None:
    """tieba：无点赞列，排序回落 add_ts。rows=(note_id, content) 顺序即 add_ts 升序。"""

    db.execute(
        text(
            "CREATE TABLE tieba_comment ("
            "id INTEGER PRIMARY KEY, note_id TEXT, content TEXT, add_ts BIGINT)"
        )
    )
    for i, (note_id, content) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO tieba_comment (id, note_id, content, add_ts) "
                "VALUES (:i, :n, :c, :t)"
            ),
            {"i": i, "n": note_id, "c": content, "t": 1700000000000 + i},
        )
    db.commit()


def create_zhihu_comment_table(db, rows: list[tuple[str, str, str]]) -> None:
    """zhihu：关联列 content_id（不是 note_id）、点赞列 like_count。rows=(content_id, content, like_count)。"""

    db.execute(
        text(
            "CREATE TABLE zhihu_comment ("
            "id INTEGER PRIMARY KEY, content_id TEXT, content TEXT, "
            "like_count TEXT, add_ts BIGINT)"
        )
    )
    for i, (content_id, content, like_count) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO zhihu_comment (id, content_id, content, like_count, add_ts) "
                "VALUES (:i, :cid, :c, :l, :t)"
            ),
            {"i": i, "cid": content_id, "c": content, "l": like_count, "t": 1700000000000 + i},
        )
    db.commit()


class FetchTopCommentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

    def test_returns_top_liked_comments_per_note(self) -> None:
        db = self.session_factory()
        create_xhs_comment_table(
            db,
            [
                ("n1", "低赞评论", "2"),
                ("n1", "高赞评论", "99"),
                ("n1", "中赞评论", "10"),
                ("n1", "第四条评论", "1"),
                ("n2", "另一帖的评论", "5"),
            ],
        )

        result = fetch_top_comments(db, [("xhs", "n1"), ("xhs", "n2")], per_note=3)
        db.close()

        self.assertEqual(result[("xhs", "n1")][0], "高赞评论")
        self.assertEqual(len(result[("xhs", "n1")]), 3)
        self.assertEqual(result[("xhs", "n2")], ["另一帖的评论"])

    def test_zhihu_matches_by_content_id(self) -> None:
        db = self.session_factory()
        create_zhihu_comment_table(
            db,
            [
                ("z1", "知乎低赞", "3"),
                ("z1", "知乎高赞", "88"),
            ],
        )

        result = fetch_top_comments(db, [("zhihu", "z1")], per_note=3)
        db.close()

        self.assertEqual(result[("zhihu", "z1")][0], "知乎高赞")
        self.assertEqual(len(result[("zhihu", "z1")]), 2)

    def test_weibo_orders_by_comment_like_count_not_like_count(self) -> None:
        db = self.session_factory()
        # comment_like_count 与 like_count 故意相反：正确排序应看 comment_like_count
        create_weibo_comment_table(
            db,
            [
                ("w1", "低赞但like_count虚高", "1", "999"),
                ("w1", "真正高赞", "100", "1"),
            ],
        )

        result = fetch_top_comments(db, [("weibo", "w1")], per_note=3)
        db.close()

        self.assertEqual(result[("weibo", "w1")][0], "真正高赞")

    def test_tieba_no_like_column_falls_back_to_add_ts(self) -> None:
        db = self.session_factory()
        create_tieba_comment_table(
            db,
            [
                ("t1", "贴吧早评论"),
                ("t1", "贴吧晚评论"),
            ],
        )

        result = fetch_top_comments(db, [("tieba", "t1")], per_note=3)
        db.close()

        # 无点赞列 likes 恒为 0，回落按 add_ts DESC——晚插入的排前
        self.assertEqual(result[("tieba", "t1")], ["贴吧晚评论", "贴吧早评论"])

    def test_cross_platform_same_bare_id_does_not_collide(self) -> None:
        db = self.session_factory()
        create_xhs_comment_table(db, [("shared", "小红书内容", "1")])
        create_zhihu_comment_table(db, [("shared", "知乎内容", "1")])

        result = fetch_top_comments(
            db, [("xhs", "shared"), ("zhihu", "shared")], per_note=3
        )
        db.close()

        self.assertEqual(result[("xhs", "shared")], ["小红书内容"])
        self.assertEqual(result[("zhihu", "shared")], ["知乎内容"])

    def test_missing_table_returns_empty(self) -> None:
        # SQLite 演示快照没有 MediaCrawler 原生表——必须优雅降级而不是抛错
        db = self.session_factory()
        result = fetch_top_comments(db, [("weibo", "w1")])
        db.close()

        self.assertEqual(result, {})

    def test_unknown_platform_is_skipped(self) -> None:
        db = self.session_factory()
        create_xhs_comment_table(db, [("n1", "小红书评论", "5")])

        result = fetch_top_comments(db, [("douyin", "n1"), ("xhs", "n1")])
        db.close()

        self.assertNotIn(("douyin", "n1"), result)
        self.assertEqual(result[("xhs", "n1")], ["小红书评论"])

    def test_per_note_truncates(self) -> None:
        db = self.session_factory()
        create_xhs_comment_table(
            db,
            [
                ("n1", "评论一", "9"),
                ("n1", "评论二", "8"),
                ("n1", "评论三", "7"),
                ("n1", "评论四", "6"),
            ],
        )

        result = fetch_top_comments(db, [("xhs", "n1")], per_note=2)
        db.close()

        self.assertEqual(len(result[("xhs", "n1")]), 2)

    def test_empty_refs_short_circuits(self) -> None:
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
        create_xhs_comment_table(db, [("n1", "评论区都在吐槽", "50")])

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
        create_xhs_comment_table(db, [("68d53ba8", "裸ID评论", "9")])

        rows = query_agent_rows(db, keyword="带前缀", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], ["裸ID评论"])

    def test_zhihu_row_routes_to_zhihu_comment_by_content_id(self) -> None:
        db = self.session_factory()
        db.add(
            ProcessedPost(
                raw_post_id=3,
                platform="zhihu",
                note_id="zhihu:2056070606362302108",
                title="知乎问答",
                content="正文。",
                heat_score=7.0,
            )
        )
        db.commit()
        create_zhihu_comment_table(
            db, [("2056070606362302108", "知乎评论区风向", "12")]
        )

        rows = query_agent_rows(db, keyword="知乎问答", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], ["知乎评论区风向"])

    def test_rows_default_to_empty_comments_without_table(self) -> None:
        db = self.session_factory()
        rows = query_agent_rows(db, keyword="", limit=10)
        db.close()

        self.assertEqual(rows[0]["top_comments"], [])


if __name__ == "__main__":
    unittest.main()
