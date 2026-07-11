"""add_processed_posts_heat_rank 迁移脚本：加列 + 回填，幂等、可 --dry-run。

create_all 不会 ALTER 已存在的表，所以共享库里那 331 行需要一个显式迁移。
纯逻辑（plan/apply）不连库；回填 pass 用 sqlite 内存库验证。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ProcessedPost, RawPost
from scripts.add_processed_posts_heat_rank import (
    COLUMN,
    TABLE,
    apply_plan,
    backfill_heat_ranks,
    plan_column,
    preview_backfill,
)


class PlanColumnTests(unittest.TestCase):
    def test_target_constants(self) -> None:
        self.assertEqual(TABLE, "processed_posts")
        self.assertEqual(COLUMN, "heat_rank")

    def test_missing_table_is_skipped_not_created(self) -> None:
        # 本脚本只加列，绝不建表、绝不 drop、绝不改别的东西。
        plan = plan_column(existing_tables=set(), existing_columns=set())
        self.assertEqual(plan.action, "skip_missing_table")

    def test_column_absent_is_planned_add(self) -> None:
        plan = plan_column(existing_tables={TABLE}, existing_columns={"id", "heat_score"})
        self.assertEqual(plan.action, "add_column")

    def test_column_present_is_skipped_so_a_rerun_is_safe(self) -> None:
        plan = plan_column(existing_tables={TABLE}, existing_columns={"id", "heat_score", "heat_rank"})
        self.assertEqual(plan.action, "skip_exists")


class ApplyPlanTests(unittest.TestCase):
    def test_dry_run_reports_would_add_and_never_calls_the_ddl(self) -> None:
        calls: list[str] = []
        plan = plan_column({TABLE}, {"id"})
        outcome = apply_plan(plan, lambda _plan: calls.append("ddl"), dry_run=True)
        self.assertEqual(outcome.status, "would_add")
        self.assertEqual(calls, [])

    def test_second_run_reports_skipped(self) -> None:
        calls: list[str] = []
        plan = plan_column({TABLE}, {"id", "heat_rank"})
        outcome = apply_plan(plan, lambda _plan: calls.append("ddl"), dry_run=False)
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual(calls, [])

    def test_add_column_calls_the_ddl_once(self) -> None:
        calls: list[str] = []
        plan = plan_column({TABLE}, {"id"})
        outcome = apply_plan(plan, lambda _plan: calls.append("ddl"), dry_run=False)
        self.assertEqual(outcome.status, "added")
        self.assertEqual(calls, ["ddl"])


class BackfillTests(unittest.TestCase):
    """回填：存量行拿到 heat_rank，web 行先拿到来源权威度热度。"""

    def setUp(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
        self.addCleanup(self.db.close)

    def _add(self, platform: str, heat: float, url: str = "") -> ProcessedPost:
        raw = RawPost(platform=platform, external_id=f"{platform}-{heat}-{url}", title="t", url=url)
        self.db.add(raw)
        self.db.flush()
        post = ProcessedPost(
            raw_post_id=raw.id, platform=platform, note_id=f"{platform}:{raw.id}", title="t", heat_score=heat
        )
        self.db.add(post)
        self.db.flush()
        return post

    def test_backfill_ranks_every_row_within_its_platform(self) -> None:
        xhs_top = self._add("xhs", 12000.0)
        xhs_low = self._add("xhs", 10.0)
        weibo_top = self._add("weibo", 9.0)

        report = backfill_heat_ranks(self.db)
        self.db.flush()

        self.assertEqual(report["ranked"], 3)
        self.assertEqual(weibo_top.heat_rank, 50.0)  # 该平台只有一条 -> 中性 50
        self.assertGreater(xhs_top.heat_rank, xhs_low.heat_rank)

    def test_backfill_gives_web_rows_an_authority_heat_score_first(self) -> None:
        official = self._add("web", 0.0, url="https://news.sysu.edu.cn/n/1")
        unknown = self._add("web", 0.0, url="https://random.example.com/x")

        report = backfill_heat_ranks(self.db)
        self.db.flush()

        self.assertEqual(report["web_rescored"], 1)
        self.assertGreater(official.heat_score, 0.0)
        self.assertGreater(official.heat_rank, unknown.heat_rank)

    def test_backfill_is_idempotent(self) -> None:
        self._add("xhs", 12000.0)
        self._add("xhs", 10.0)
        backfill_heat_ranks(self.db)
        self.db.flush()

        report = backfill_heat_ranks(self.db)

        self.assertEqual(report["ranked"], 0)
        self.assertEqual(report["web_rescored"], 0)

    def test_backfill_never_changes_heat_score_of_crawler_platforms(self) -> None:
        post = self._add("xhs", 3924.0)
        backfill_heat_ranks(self.db)
        self.db.flush()
        self.assertEqual(post.heat_score, 3924.0)


class PreviewBackfillTests(unittest.TestCase):
    """dry-run 要能真的预演回填——而且必须在 heat_rank 列还不存在时也能跑。

    所以预演只能用显式列查询（SELECT platform, heat_score ...），绝不能 SELECT 整个
    ORM 实体（那会带上尚不存在的 heat_rank 列，直接报错）。
    """

    def setUp(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
        self.addCleanup(self.db.close)

    def _add(self, platform: str, heat: float, url: str = "") -> None:
        raw = RawPost(platform=platform, external_id=f"{platform}-{heat}-{url}", title="t", url=url)
        self.db.add(raw)
        self.db.flush()
        self.db.add(
            ProcessedPost(
                raw_post_id=raw.id, platform=platform, note_id=f"{platform}:{raw.id}", title="t", heat_score=heat
            )
        )
        self.db.flush()

    def test_preview_reports_every_platform_and_writes_nothing(self) -> None:
        self._add("xhs", 3924.0)
        self._add("xhs", 10.0)
        self._add("weibo", 3.0)

        report = preview_backfill(self.db)

        self.assertEqual(report["total"], 3)
        self.assertEqual(report["ranked"], 3)
        platforms = {row["platform"]: row for row in report["platforms"]}
        self.assertEqual(platforms["xhs"]["rows"], 2)
        self.assertEqual(platforms["weibo"]["rows"], 1)
        self.assertEqual(platforms["weibo"]["median_heat_score"], 3.0)
        # 微博唯一那条拿到中性 50，而不是被判 0 分沉底。
        self.assertEqual(platforms["weibo"]["max_heat_rank"], 50.0)
        self.assertEqual(platforms["xhs"]["max_heat_rank"], 75.0)

    def test_preview_reports_web_rows_that_would_be_rescored(self) -> None:
        self._add("web", 0.0, url="https://news.sysu.edu.cn/n/1")
        self._add("web", 0.0, url="https://random.example.com/x")

        report = preview_backfill(self.db)

        self.assertEqual(report["web_rescored"], 1)
        web = next(row for row in report["platforms"] if row["platform"] == "web")
        self.assertEqual(web["rows"], 2)


if __name__ == "__main__":
    unittest.main()
