"""快手评论路由测试：SPEC 注册 + sqlite 内存库端到端取数（无点赞列用字面量 0）。"""

import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.services.comment_loader import PLATFORM_COMMENT_SPEC, fetch_top_comments


class KsCommentSpecTests(unittest.TestCase):
    def test_spec_registered(self):
        spec = PLATFORM_COMMENT_SPEC["ks"]
        self.assertEqual(spec["table"], "kuaishou_video_comment")
        self.assertEqual(spec["join_col"], "video_id")
        self.assertIsNone(spec["like_col"])  # ks 评论表无点赞列，同贴吧字面量 0


class KsFetchTopCommentsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE kuaishou_video_comment ("
                    "id INTEGER PRIMARY KEY, video_id VARCHAR(255), "
                    "content TEXT, add_ts BIGINT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO kuaishou_video_comment (video_id, content, add_ts) VALUES "
                    "('3xabc', '早的评论', 1), ('3xabc', '晚的评论', 2), ('other', '别的视频', 3)"
                )
            )
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()

    def test_fetch_orders_by_add_ts_desc_with_zero_likes(self):
        result = fetch_top_comments(self.db, [("ks", "3xabc")], per_note=3)
        self.assertEqual(result[("ks", "3xabc")], ["晚的评论", "早的评论"])

    def test_unknown_ids_absent(self):
        result = fetch_top_comments(self.db, [("ks", "nope")])
        self.assertNotIn(("ks", "nope"), result)


if __name__ == "__main__":
    unittest.main()
