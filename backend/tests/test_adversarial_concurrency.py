"""对抗战役 · 攻击面3：并发竞态。

刁钻用户假设：狂点提交、构造重复 id 批量操作、快速连发绕频控。
项目已有竞态防护（注册/投稿/举报的 IntegrityError→409、原子自增），本组补齐
批量去重、频控、举报累加到阈值的确定性语义验证。真并发（多线程）在 SQLite 单连接
下会串行，故这里用确定性的时序断言覆盖竞态语义。
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
from backend.main import app
from backend.models import EventComment, PublicEvent
from backend.services import comment_service
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
        self.addCleanup(comment_service.reset_comment_rate_limit)
        self.client = TestClient(app)

        # admin 保持 transient（不 add 入库）：dependency_overrides 直接返回它，
        # 接口只读它的内存属性 id/username/role，不触发 Session 刷新（避免 close 后 detached）。
        db = self.session_factory()
        for i in range(1, 4):
            db.add(PublicEvent(id=i, event_key=f"k{i}", title=f"事件{i}", status="draft"))
        db.commit()
        db.close()


class BatchDedupTests(_Fixture):
    def test_duplicate_ids_in_batch_processed_once(self):
        """同一 id 在批量里出现多次，只应处理一次、只留一条审计日志。"""
        resp = self.client.post(
            "/api/admin/events/batch-status",
            json={"event_ids": [1, 1, 1, 2], "status": "published"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["succeeded"], 2, "去重后应只处理 2 个不同事件")

        db = self.session_factory()
        try:
            logs = db.query(EventReviewLog).all()
        finally:
            db.close()
        self.assertEqual(len(logs), 2, "重复 id 不应产生重复审计日志")


class RateLimitTests(_Fixture):
    def setUp(self):
        super().setUp()
        db = self.session_factory()
        db.query(PublicEvent).filter(PublicEvent.id == 1).update({"status": "published"})
        db.commit()
        db.close()
        self.user = User(id=5, username="u", role="user", status="active", is_active=True)
        app.dependency_overrides[get_current_user] = lambda: self.user

    def test_rapid_double_comment_is_throttled(self):
        r1 = self.client.post("/api/events/1/comments", json={"content": "第一条评论"})
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post("/api/events/1/comments", json={"content": "秒发第二条"})
        self.assertEqual(r2.status_code, 429, "10 秒冷却内的连发应被频控拦截")


class ReportAtomicTests(_Fixture):
    def test_reports_accumulate_and_autohide_is_idempotent(self):
        """连续举报累加到阈值触发隐藏；超过阈值继续举报仍是 hidden（幂等）。"""
        db = self.session_factory()
        db.add(EventComment(
            id=1, event_id=1, user_id=9, username="发帖人", content="争议言论",
            status="visible", report_count=0, sentiment="neutral",
            created_at=datetime(2026, 7, 1),
        ))
        db.commit()
        db.close()

        last_status = None
        for _ in range(7):  # 阈值是 5
            comment_service.reset_comment_rate_limit()
            resp = self.client.post("/api/comments/1/report")
            self.assertEqual(resp.status_code, 200)
            last_status = resp.json()["data"]["status"]
        self.assertEqual(last_status, "hidden", "举报超阈值后应保持 hidden")

        db = self.session_factory()
        try:
            comment = db.query(EventComment).filter(EventComment.id == 1).one()
        finally:
            db.close()
        self.assertEqual(comment.report_count, 7, "每次举报都应累加，不丢增量")
        self.assertEqual(comment.status, "hidden")


if __name__ == "__main__":
    unittest.main()
