"""审计第 1 批：生产崩溃修复（MySQL 上 500、SQLite 测不出的一类）。

- delete_event 漏删 EventReviewLog → MySQL 外键违约（rejected/archived 必带审核日志）
- review_submission 并发审批 → RawPost 唯一约束 IntegrityError 未捕获 → 500 而非 409
- report_comment 举报计数 read-modify-write 竞态 → 改原子自增，行为不变
- register 并发同名 → username 唯一约束 IntegrityError 未捕获 → 500 而非 409
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import EventReviewLog
from backend.database import Base
from backend.models import EventComment, PublicEvent, RawPost, UserSubmission
from backend.services.comment_service import AUTO_HIDE_REPORTS, report_comment
from backend.services.event_curation import delete_event
from backend.services.submission_service import SubmissionError, review_submission


def _make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


class DeleteEventReviewLogTests(unittest.TestCase):
    def test_delete_event_also_removes_its_review_logs(self) -> None:
        db = _make_db()
        self.addCleanup(db.close)
        event = PublicEvent(event_key="k", title="被驳回的事件", status="rejected")
        db.add(event)
        db.flush()
        db.add(EventReviewLog(event_id=event.id, reviewer_id="admin",
                              old_status="draft", new_status="rejected"))
        db.flush()

        delete_event(db, event)
        db.flush()

        # 漏删审核日志 → MySQL commit 时外键违约 500；此断言在 SQLite 上也能抓到残留行
        remaining = db.query(EventReviewLog).filter(EventReviewLog.event_id == event.id).count()
        self.assertEqual(remaining, 0, "事件删除后其审核日志必须一并清除，否则 MySQL 外键违约")


class ReviewSubmissionRaceTests(unittest.TestCase):
    def test_concurrent_approve_conflict_raises_clean_409_not_integrityerror(self) -> None:
        db = _make_db()
        self.addCleanup(db.close)
        sub = UserSubmission(user_id=1, username="u", title="投稿", content="c", status="pending")
        db.add(sub)
        db.flush()
        # 模拟"另一并发请求已先落库"：同 external_id 的 RawPost 已存在
        db.add(RawPost(platform="campus", external_id=f"sub:{sub.id}", title="x", content="c"))
        db.flush()

        with self.assertRaises(SubmissionError) as ctx:
            review_submission(db, sub, approve=True, comment="", actor="admin")
        self.assertEqual(ctx.exception.status_code, 409, "并发审批冲突要翻成 409，不能裸抛 IntegrityError→500")


class ReportCommentAtomicTests(unittest.TestCase):
    def test_report_increments_and_auto_hides_at_threshold(self) -> None:
        db = _make_db()
        self.addCleanup(db.close)
        event = PublicEvent(event_key="k", title="t", status="published")
        db.add(event)
        db.flush()
        c = EventComment(event_id=event.id, user_id=1, username="u", content="x", status="visible")
        db.add(c)
        db.flush()

        for i in range(AUTO_HIDE_REPORTS):
            report_comment(db, c.id)
            db.flush()

        db.refresh(c)
        self.assertEqual(c.report_count, AUTO_HIDE_REPORTS, "原子自增后计数必须精确")
        self.assertEqual(c.status, "hidden", "举报满阈值自动隐藏")


class RegisterRaceTests(unittest.TestCase):
    """check-then-insert：check 通过后 flush 撞 username 唯一约束（并发抢注）→ 必须 409。"""

    def test_integrityerror_on_flush_becomes_409(self) -> None:
        from sqlalchemy.orm import Session
        from fastapi.testclient import TestClient

        from backend.database import get_db
        from backend.main import app

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)

        # register 唯一的显式 flush 就是插入新用户那次；令它抛 IntegrityError 模拟并发抢注。
        # 测试库 autoflush=False，故补丁只命中该 flush，不误伤 .first() 查询。
        real_flush = Session.flush

        def flaky_flush(self, *args, **kwargs):
            raise IntegrityError("dup username", None, Exception("UNIQUE"))

        with mock.patch.object(Session, "flush", flaky_flush):
            resp = client.post(
                "/api/auth/register", json={"username": "racer", "password": "password123"}
            )
        self.assertEqual(resp.status_code, 409, "并发抢注唯一约束冲突要 409，不是 500")
        self.assertIs(Session.flush, real_flush)  # 补丁已还原


if __name__ == "__main__":
    unittest.main()
