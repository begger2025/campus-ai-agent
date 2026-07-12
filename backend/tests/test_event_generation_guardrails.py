"""事件生成的两条底线：

1. 输入不许被静默截断——`--limit` 砍掉的帖子必须被数出来、喊出来（Defect A）。
2. 单帖不许成事件——一条帖子自成一簇时不产生 public_event（Defect B）。

两条都直接决定答辩时事件列表的可信度：截断会让"全量分析"其实只看了最新一段，
单帖事件会让列表里塞满「<某条帖子的标题>相关讨论」这种点进去只有一条内容的条目。
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent.public_opinion_core.clustering import cluster_notes
from backend.agent.public_opinion_core.schemas import AnalyzeRequest, OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import cluster_notes_semantic
from backend.agent.public_opinion_core.service import PublicOpinionAgentService
from backend.database import Base
from backend.models import ProcessedPost
from backend.services.public_opinion_adapter import query_agent_rows, run_public_opinion_analysis


ROOT = Path(__file__).resolve().parents[2]


def load_generate_script():
    spec = importlib.util.spec_from_file_location(
        "generate_public_events_under_test", ROOT / "scripts" / "generate_public_events.py"
    )
    module = importlib.util.module_from_spec(spec)
    # 脚本在模块级 load_dotenv(override=True)：真跑一遍会把 .env（含 DATABASE_URL、
    # HEAT_PLATFORM_WEIGHTS）灌进本进程的 os.environ，污染同一进程里的其它测试。
    with patch("dotenv.load_dotenv", return_value=True):
        spec.loader.exec_module(module)
    return module


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def note(note_id: str, title: str, content: str = "", **kwargs) -> OpinionNote:
    return OpinionNote(note_id=note_id, title=title, content=content or title, **kwargs)


class MinClusterSizeCoreTest(unittest.TestCase):
    """核心聚类：小于 min_cluster_size 的簇不产出事件。"""

    def test_semantic_singleton_cluster_produces_no_event(self) -> None:
        notes = [
            note("a", "食堂排队太长了"),
            note("b", "食堂窗口排队久"),
            note("c", "宿舍热水停了"),
        ]
        # a/b 向量相同必然同簇；c 正交必然单独成簇。
        vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]

        result = cluster_notes_semantic(
            notes, vectors, cluster_threshold=0.9, min_cluster_size=2
        )

        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].source_count, 2)
        self.assertEqual(result.suppressed_clusters, 1)
        # 被压制的簇不能留下簇中心，否则下次运行会把它对齐成"老事件"复活。
        self.assertEqual(len(result.centroids), 1)

    def test_semantic_min_cluster_size_one_keeps_current_behaviour(self) -> None:
        notes = [note("a", "食堂排队太长了"), note("c", "宿舍热水停了")]
        vectors = [[1.0, 0.0], [0.0, 1.0]]

        result = cluster_notes_semantic(notes, vectors, cluster_threshold=0.9, min_cluster_size=1)

        self.assertEqual(len(result.events), 2)
        self.assertEqual(result.suppressed_clusters, 0)

    def test_rule_clustering_singleton_group_produces_no_event(self) -> None:
        notes = [
            note("a", "食堂排队太长了"),
            note("b", "食堂窗口价格上涨"),
            note("c", "宿舍热水停了"),
        ]

        events = cluster_notes(notes, min_cluster_size=2)

        self.assertEqual([event.category for event in events], ["canteen_life"])
        self.assertEqual(events[0].source_count, 2)


class MinClusterSizeServiceTest(unittest.TestCase):
    """服务层：min_cluster_size 一路传到聚类，并把压制条数说出来。"""

    def test_service_suppresses_singletons_and_warns(self) -> None:
        rows = [
            {"id": 1, "processed_post_id": 1, "note_id": "a", "title": "食堂排队太长了", "content": "食堂排队太长了", "platform": "xhs"},
            {"id": 2, "processed_post_id": 2, "note_id": "b", "title": "食堂排队久", "content": "食堂排队久", "platform": "xhs"},
            {"id": 3, "processed_post_id": 3, "note_id": "c", "title": "宿舍热水停了", "content": "宿舍热水停了", "platform": "xhs"},
        ]
        vectors = {"食堂排队太长了": [1.0, 0.0], "食堂排队久": [1.0, 0.0], "宿舍热水停了": [0.0, 1.0]}

        def embedder(texts: list[str]) -> list[list[float]]:
            return [vectors[text] for text in texts]

        result = PublicOpinionAgentService().analyze_from_rows(
            rows,
            AnalyzeRequest(limit=10),
            embedder=embedder,
            cluster_threshold=0.9,
            min_cluster_size=2,
        )

        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].source_count, 2)
        self.assertEqual(result.run_log.extra.get("suppressed_clusters"), 1)
        self.assertTrue(
            any("min_cluster_size" in warning for warning in result.warnings),
            f"压制了单帖簇却没有任何提示：{result.warnings}",
        )


class AdapterGuardrailTest(unittest.TestCase):
    """适配层：默认配置下单帖不入库；limit 截断必须报警。"""

    def setUp(self) -> None:
        self.session_factory = make_session_factory()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            patch("backend.services.public_opinion_adapter.get_embedder", return_value=None),
            patch("backend.services.public_opinion_adapter.get_sentiment_classifier", return_value=None),
            patch(
                "backend.services.public_opinion_adapter.MEMORY_SNAPSHOT_PATH",
                Path(self.tmp.name) / "memory.json",
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, posts: list[ProcessedPost]) -> None:
        db = self.session_factory()
        db.add_all(posts)
        db.commit()
        db.close()

    def seed_two_canteen_one_dorm(self) -> None:
        self.seed(
            [
                ProcessedPost(raw_post_id=1, platform="xhs", note_id="c1", title="食堂排队太长", content="食堂窗口排队太长了", heat_score=10.0),
                ProcessedPost(raw_post_id=2, platform="xhs", note_id="c2", title="食堂价格上涨", content="食堂套餐价格涨了", heat_score=9.0),
                ProcessedPost(raw_post_id=3, platform="xhs", note_id="d1", title="宿舍热水停了", content="宿舍热水又停了", heat_score=8.0),
            ]
        )

    def analyze(self, **kwargs):
        db = self.session_factory()
        try:
            return run_public_opinion_analysis(db, persist=False, **kwargs)
        finally:
            db.rollback()
            db.close()

    def test_single_post_group_does_not_become_event(self) -> None:
        self.seed_two_canteen_one_dorm()

        result = self.analyze(keyword="", limit=0)

        titles = [event["title"] for event in result["events"]]
        self.assertEqual(result["event_count"], 1, f"单帖不该成事件，实际事件：{titles}")
        self.assertEqual(result["events"][0]["source_count"], 2)
        self.assertEqual(len(result["payload_preview"]["public_events"]), 1)

    def test_limit_zero_loads_every_row(self) -> None:
        self.seed_two_canteen_one_dorm()

        db = self.session_factory()
        rows = query_agent_rows(db, limit=0)
        db.close()

        self.assertEqual(len(rows), 3)

    def test_truncated_input_is_reported_loudly(self) -> None:
        self.seed_two_canteen_one_dorm()

        result = self.analyze(keyword="", limit=2)

        truncation = result.get("input_truncated")
        self.assertIsNotNone(truncation, "被 limit 截断却没有在返回值里说明")
        self.assertEqual(truncation["matched"], 3)
        self.assertEqual(truncation["analyzed"], 2)
        self.assertEqual(truncation["dropped"], 1)
        self.assertTrue(
            any("截断" in warning for warning in result["warnings"]),
            f"截断没有进 warnings：{result['warnings']}",
        )

    def test_full_run_reports_no_truncation(self) -> None:
        self.seed_two_canteen_one_dorm()

        result = self.analyze(keyword="", limit=0)

        self.assertIsNone(result.get("input_truncated"))
        self.assertFalse([w for w in result["warnings"] if "截断" in w])


class GenerateScriptDefaultTest(unittest.TestCase):
    """脚本默认值：默认跑全量，不再默认砍到最新 200 条。"""

    def test_default_limit_means_all_rows(self) -> None:
        module = load_generate_script()

        self.assertEqual(module.DEFAULT_LIMIT, 0)


if __name__ == "__main__":
    unittest.main()
