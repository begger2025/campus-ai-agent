"""后台概览的「今日工作台」扩展：待办计数 + 数据管线健康，全部实时查询。

审核发现（2026-07-17 用户截图）：原页面没有假数据，但 80% 内容与其它页重复、
六卡不可点、新功能待办入口全缺。重定位 = 回答「今天要处理什么、系统还好吗」。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.admin_models import AgentRunLog
from backend.database import Base
from backend.models import EventComment, ProcessedPost, PublicEvent, UserSubmission
from backend.services.admin_service import overview_data


class WorkbenchOverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        event = PublicEvent(event_key="sem:e", title="事件", status="published", risk_level="low", curated=True)
        self.db.add(event)
        self.db.commit()
        self.db.add_all([
            UserSubmission(user_id=1, username="u", title="待审投稿", content="c"),
            UserSubmission(user_id=1, username="u", title="已审", content="c", status="approved"),
            EventComment(event_id=event.id, user_id=1, username="u", content="被举报", report_count=2),
            EventComment(event_id=event.id, user_id=1, username="u", content="清白", report_count=0),
            ProcessedPost(note_id="a", raw_post_id=1, platform="xhs", title="新帖", content="c",
                          publish_time=datetime.utcnow() - timedelta(days=3)),
            ProcessedPost(note_id="b", raw_post_id=2, platform="xhs", title="老帖", content="c",
                          publish_time=datetime.utcnow() - timedelta(days=300)),
            ProcessedPost(note_id="c", raw_post_id=3, platform="xhs", title="剔除帖", content="c",
                          excluded=True, publish_time=datetime.utcnow() - timedelta(days=3)),
            AgentRunLog(agent_type="public_opinion", input_count=800, output_count=119,
                        status="success", duration_ms=120000,
                        output_summary=json.dumps({"warnings": ["a", "b"]})),
        ])
        self.db.commit()

    def test_workbench_counts_are_live_queries(self) -> None:
        data = overview_data(self.db)

        self.assertEqual(data["pending_submissions_count"], 1, "只数 pending")
        self.assertEqual(data["reported_comments_count"], 1, "有举报计数的才算待复核")
        self.assertEqual(data["curated_events_count"], 1)

    def test_corpus_health_excludes_the_excluded(self) -> None:
        corpus = overview_data(self.db)["corpus"]

        self.assertEqual(corpus["total"], 2, "剔除帖不算语料")
        self.assertEqual(corpus["recent_30d"], 1)
        self.assertEqual(corpus["excluded"], 1)
        self.assertAlmostEqual(corpus["recent_ratio"], 0.5)

    def test_last_agent_run_summarizes_the_pipeline(self) -> None:
        run = overview_data(self.db)["last_agent_run"]

        self.assertEqual(run["event_count"], 119)
        self.assertEqual(run["input_count"], 800)
        self.assertEqual(run["warnings_count"], 2, "警告数从 output_summary 的 JSON 里解析")
        self.assertEqual(run["status"], "success")

    def test_empty_pipeline_yields_none_not_crash(self) -> None:
        self.db.query(AgentRunLog).delete()
        self.db.commit()

        self.assertIsNone(overview_data(self.db)["last_agent_run"])


if __name__ == "__main__":
    unittest.main()
