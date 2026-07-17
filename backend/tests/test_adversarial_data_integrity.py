"""对抗战役 · 攻击面5：数据一致性。

刁钻用户假设：删掉事件后评论/审核日志成孤儿？剔除的帖子会不会还被检索到
（静默泄漏——用户以为剔了，AI 却仍在用它下结论）？移出事件最后一条成员会不会
留下空壳事件？这些是"看起来正常、实则数据不一致"的隐藏隐患。

admin/user 均为 transient（不入库）：dependency_overrides 直接返回，接口只读其内存属性，
避免 Session close 后 DetachedInstanceError（攻击面3 的教训）。
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import EventReviewLog, User
from backend.database import Base, get_db
from backend.models import EventComment, EventPostLink, ProcessedPost, PublicEvent
from backend.main import app
from backend.services.auth_service import get_current_user, require_admin


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

        self.admin = User(id=1, username="admin", role="admin", status="active", is_active=True)
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.admin
        app.dependency_overrides[require_admin] = lambda: self.admin
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _count(self, model, **flt):
        db = self.session_factory()
        try:
            q = db.query(model)
            for k, v in flt.items():
                q = q.filter(getattr(model, k) == v)
            return q.count()
        finally:
            db.close()


class CascadeDeleteTests(_Fixture):
    def test_delete_event_leaves_no_orphans(self):
        db = self.session_factory()
        db.add(ProcessedPost(id=1, note_id="n1", raw_post_id=1, platform="xhs",
                             title="t", content="c", publish_time=datetime(2026, 7, 1)))
        db.add(PublicEvent(id=1, event_key="k1", title="待删事件", status="draft"))
        db.add(EventPostLink(id=1, event_id=1, processed_post_id=1, raw_post_id=1, rank=1))
        db.add(EventComment(id=1, event_id=1, user_id=9, username="u", content="评论",
                           status="visible", sentiment="neutral", created_at=datetime(2026, 7, 1)))
        db.add(EventReviewLog(id=1, event_id=1, reviewer_id="admin",
                             old_status="draft", new_status="draft"))
        db.commit()
        db.close()

        resp = self.client.delete("/api/admin/events/1")
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self._count(EventPostLink, event_id=1), 0, "残留孤儿 link")
        self.assertEqual(self._count(EventComment, event_id=1), 0, "残留孤儿评论")
        self.assertEqual(self._count(EventReviewLog, event_id=1), 0, "残留孤儿审核日志")
        self.assertEqual(self._count(ProcessedPost, id=1), 1, "帖子被误删（它是客观采集数据）")


class ExclusionLeakTests(_Fixture):
    """剔除的帖子绝不能再出现在面向用户的检索里（静默泄漏防护）。"""

    def setUp(self):
        super().setUp()
        db = self.session_factory()
        for i, (title, excluded) in enumerate([("正常宿舍帖", False), ("广告应剔除", True)], start=1):
            db.add(ProcessedPost(id=i, note_id=f"n{i}", raw_post_id=i, platform="xhs",
                                title=title, content=title, sentiment="neutral", risk_level="low",
                                excluded=excluded, publish_time=datetime(2026, 7, 1)))
        db.commit()
        db.close()
        self.user = User(id=2, username="u", role="user", status="active", is_active=True)
        app.dependency_overrides[get_current_user] = lambda: self.user

    def test_excluded_post_absent_from_search(self):
        r1 = self.client.get("/api/sentiment/posts", params={"keyword": "宿舍"})
        self.assertIn("正常宿舍帖", [it["title"] for it in r1.json()["data"]["items"]])
        r2 = self.client.get("/api/sentiment/posts", params={"keyword": "广告"})
        self.assertNotIn("广告应剔除", [it["title"] for it in r2.json()["data"]["items"]],
                         "被剔除的帖子仍出现在检索结果——静默泄漏")


class EmptyShellTests(_Fixture):
    def test_removing_last_member_rejected(self):
        db = self.session_factory()
        db.add(ProcessedPost(id=1, note_id="n1", raw_post_id=1, platform="xhs",
                             title="唯一成员", content="c", publish_time=datetime(2026, 7, 1)))
        db.add(PublicEvent(id=1, event_key="k1", title="单成员事件", status="draft", source_count=1))
        db.add(EventPostLink(id=1, event_id=1, processed_post_id=1, raw_post_id=1, rank=1))
        db.commit()
        db.close()

        resp = self.client.delete("/api/admin/events/1/posts/1")
        self.assertGreaterEqual(resp.status_code, 400, "移出最后一条成员应被拒（不允许空壳）")
        self.assertEqual(self._count(EventPostLink, event_id=1), 1, "拒绝后成员仍在")


if __name__ == "__main__":
    unittest.main()
