from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost, PublicEvent
from backend.services.public_opinion_adapter import run_public_opinion_analysis


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def seed_posts(db) -> None:
    db.add_all(
        [
            ProcessedPost(
                raw_post_id=1,
                platform="xhs",
                note_id="n-neg",
                title="宿舍诈骗电话频发",
                content="最近宿舍多人接到诈骗电话，要求提供银行卡，大家很担心。",
                source_keyword="宿舍",
                heat_score=50.0,
            ),
            ProcessedPost(
                raw_post_id=2,
                platform="xhs",
                note_id="n-pos",
                title="食堂新窗口不错",
                content="新开的轻食窗口味道不错，环境也好。",
                source_keyword="食堂",
                heat_score=30.0,
            ),
        ]
    )
    db.commit()


class AnalysisWriteBackTest(unittest.TestCase):
    """analyze 持久化时必须把逐帖情绪/风险回写 processed_posts——
    否则表里的 sentiment/risk 列永远是建行时的占位值（全库 neutral/low）。"""

    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        db = self.session_factory()
        seed_posts(db)
        db.close()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            # 不加载嵌入模型（避免网络/耗时），走规则聚类
            patch("backend.services.public_opinion_adapter.get_embedder", return_value=None),
            # 不触发 LLM 情绪
            patch("backend.services.public_opinion_adapter.get_sentiment_classifier", return_value=None),
            # 记忆快照写进临时目录，不污染真实 data/public_opinion_memory.json
            patch(
                "backend.services.public_opinion_adapter.MEMORY_SNAPSHOT_PATH",
                Path(self.tmp.name) / "memory.json",
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_analysis(self, persist: bool = True):
        db = self.session_factory()
        try:
            result = run_public_opinion_analysis(db, keyword="", limit=50, persist=persist)
            db.commit()
            return result
        finally:
            db.close()

    def test_persist_writes_back_note_sentiment_and_risk(self) -> None:
        self.run_analysis(persist=True)

        db = self.session_factory()
        neg = db.query(ProcessedPost).filter(ProcessedPost.note_id == "n-neg").one()
        pos = db.query(ProcessedPost).filter(ProcessedPost.note_id == "n-pos").one()
        db.close()

        self.assertEqual(neg.sentiment, "negative")
        self.assertNotEqual(neg.risk_level, "low")
        self.assertGreater(neg.risk_score, 0)
        self.assertIn("诈骗", neg.risk_reasons_json)
        self.assertEqual(pos.sentiment, "positive")

    def test_preview_run_does_not_write_back(self) -> None:
        self.run_analysis(persist=False)

        db = self.session_factory()
        rows = db.query(ProcessedPost).all()
        db.close()

        self.assertTrue(all(row.sentiment == "neutral" for row in rows))


class StaleDraftArchiveTest(AnalysisWriteBackTest):
    """全量分析后，上一代聚类留下的、本次不再出现的草稿事件应自动归档；
    已发布/已驳回事件绝不自动碰（前台内容与管理员决定优先）。"""

    def seed_events(self) -> None:
        db = self.session_factory()
        db.add_all(
            [
                PublicEvent(event_key="keyword:旧话题", title="旧代草稿事件", status="draft"),
                PublicEvent(event_key="canteen_life", title="旧代已发布事件", status="published"),
            ]
        )
        db.commit()
        db.close()

    def get_event(self, key: str) -> PublicEvent:
        db = self.session_factory()
        row = db.query(PublicEvent).filter(PublicEvent.event_key == key).one()
        db.close()
        return row

    def test_full_run_archives_stale_drafts_but_not_published(self) -> None:
        self.seed_events()

        self.run_analysis(persist=True)

        self.assertEqual(self.get_event("keyword:旧话题").status, "archived")
        self.assertEqual(self.get_event("canteen_life").status, "published")

    def test_keyword_run_does_not_archive(self) -> None:
        self.seed_events()

        db = self.session_factory()
        run_public_opinion_analysis(db, keyword="食堂", limit=50, persist=True)
        db.commit()
        db.close()

        self.assertEqual(self.get_event("keyword:旧话题").status, "draft")

    def test_truncated_run_does_not_archive(self) -> None:
        # limit 截断（没看全帖子）时不能判定草稿失活
        self.seed_events()

        db = self.session_factory()
        run_public_opinion_analysis(db, keyword="", limit=1, persist=True)
        db.commit()
        db.close()

        self.assertEqual(self.get_event("keyword:旧话题").status, "draft")

    def test_preview_run_does_not_archive(self) -> None:
        self.seed_events()

        self.run_analysis(persist=False)

        self.assertEqual(self.get_event("keyword:旧话题").status, "draft")


if __name__ == "__main__":
    unittest.main()
