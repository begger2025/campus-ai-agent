"""对抗战役 · 攻击面2：输入边界与畸形数据。

刁钻用户假设：往每个输入框塞系统没预料的东西——LIKE 通配符、超长、空白、
畸形分页。目标是把"搜索结果不符预期""畸形数据入库""接口崩 500"这类隐藏 bug 逼出来。
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ProcessedPost
from backend.services.auth_service import create_access_token, get_current_user, hash_password


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

        self.user = User(id=2, username="u", role="user", status="active",
                         is_active=True, password_hash=hash_password("x"))
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        db = self.session_factory()
        db.add(self.user)
        # 两条帖子：标题分别含 "50%优惠" 和 "abc"。搜 "%" 若被当通配符会两条全中。
        for i, title in enumerate(["宿舍50%涨价", "食堂abc日常"], start=1):
            db.add(ProcessedPost(
                id=i, note_id=f"n{i}", raw_post_id=i, platform="xhs",
                title=title, content=title, sentiment="neutral", risk_level="low",
                excluded=False, publish_time=datetime(2026, 7, 1),
            ))
        db.commit()
        db.close()

    def _search(self, keyword: str):
        return self.client.get("/api/sentiment/posts", params={"keyword": keyword})


class LikeWildcardTests(_Fixture):
    def test_percent_is_literal_not_wildcard(self):
        """搜 '%' 应按字面找含百分号的帖子（1 条），而不是通配匹配全部（2 条）。"""
        resp = self._search("%")
        self.assertEqual(resp.status_code, 200)
        total = resp.json()["data"]["total"]
        self.assertEqual(total, 1, f"'%' 被当成通配符匹配了全部（total={total}）")

    def test_underscore_is_literal_not_single_char_wildcard(self):
        """搜 '_' 应找含下划线的帖子（0 条），而不是匹配任意单字符（2 条全中）。"""
        resp = self._search("_")
        self.assertEqual(resp.status_code, 200)
        total = resp.json()["data"]["total"]
        self.assertEqual(total, 0, f"'_' 被当成单字符通配符（total={total}）")

    def test_literal_percent_query_finds_the_right_post(self):
        resp = self._search("50%涨")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertIn("50%", items[0]["title"])


class MalformedInputTests(_Fixture):
    def test_oversized_keyword_rejected_by_length_cap(self):
        """超长搜索词应被 max_length 挡下（422），而不是打进 LIKE 拖垮查询。"""
        resp = self._search("阿" * 5000)
        self.assertEqual(resp.status_code, 422)

    def test_emoji_and_special_chars_do_not_crash(self):
        for kw in ["🔥🚨", "'; DROP TABLE processed_posts;--", "<script>", "\\", "％"]:
            resp = self._search(kw)
            self.assertEqual(resp.status_code, 200, f"关键词 {kw!r} 让搜索崩了")

    def test_huge_page_number_returns_empty_not_crash(self):
        resp = self.client.get("/api/sentiment/posts", params={"page": 99999999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["items"], [])

    def test_zero_and_negative_page_rejected(self):
        for page in [0, -1]:
            resp = self.client.get("/api/sentiment/posts", params={"page": page})
            self.assertEqual(resp.status_code, 422, f"page={page} 未被拒")

    def test_oversized_page_size_rejected(self):
        resp = self.client.get("/api/sentiment/posts", params={"page_size": 100000})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
