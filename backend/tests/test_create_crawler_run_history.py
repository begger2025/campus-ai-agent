from __future__ import annotations

import unittest

from sqlalchemy.exc import OperationalError

from scripts.create_crawler_run_history import (
    CREATE_TABLE_DDL,
    TABLE_NAME,
    TablePlan,
    apply_plan,
    exit_code_for,
    plan_create_table,
)


def _unexpected_apply(plan: TablePlan) -> None:  # pragma: no cover - 必须不被调用
    raise AssertionError(f"此场景不应执行建表: {plan.table}")


class PlanCreateTableTest(unittest.TestCase):
    """纯逻辑测试：不连接任何数据库，只用表名快照做存在性判定。"""

    def test_table_name_is_crawler_run_history(self) -> None:
        self.assertEqual(TABLE_NAME, "crawler_run_history")

    def test_missing_table_plans_create(self) -> None:
        plan = plan_create_table(existing_tables=set())
        self.assertEqual(plan.table, TABLE_NAME)
        self.assertEqual(plan.action, "create")

    def test_existing_table_plans_skip(self) -> None:
        plan = plan_create_table(existing_tables={TABLE_NAME, "xhs_note"})
        self.assertEqual(plan.action, "skip_exists")

    def test_other_tables_do_not_affect_plan(self) -> None:
        plan = plan_create_table(existing_tables={"xhs_note", "weibo_note"})
        self.assertEqual(plan.action, "create")


class CreateTableDdlTest(unittest.TestCase):
    """DDL 与 MediaCrawler/database/models.py 的 CrawlerRunHistory 逐列一致。"""

    def test_ddl_contains_all_columns(self) -> None:
        for column in (
            "id",
            "platform",
            "source_keyword",
            "started_at",
            "finished_at",
            "pages_fetched",
            "items_seen",
            "items_stored",
            "stop_reason",
        ):
            self.assertIn(column, CREATE_TABLE_DDL)

    def test_ddl_column_types_match_model(self) -> None:
        self.assertIn("VARCHAR(16)", CREATE_TABLE_DDL)   # platform
        self.assertIn("VARCHAR(255)", CREATE_TABLE_DDL)  # source_keyword
        self.assertIn("VARCHAR(64)", CREATE_TABLE_DDL)   # stop_reason
        self.assertEqual(CREATE_TABLE_DDL.count("BIGINT"), 2)  # started_at / finished_at

    def test_ddl_has_two_plain_indexes_engine_and_charset(self) -> None:
        self.assertIn("INDEX ix_crawler_run_history_platform (platform)", CREATE_TABLE_DDL)
        self.assertIn(
            "INDEX ix_crawler_run_history_source_keyword (source_keyword)", CREATE_TABLE_DDL
        )
        self.assertNotIn("UNIQUE", CREATE_TABLE_DDL.upper())
        self.assertIn("ENGINE=InnoDB", CREATE_TABLE_DDL)
        self.assertIn("utf8mb4", CREATE_TABLE_DDL)


class ApplyPlanTest(unittest.TestCase):
    """执行阶段：dry-run 只预览、跳过不执行、失败兜住并给退出码 1。全程注入假 apply_fn。"""

    def test_create_invokes_apply_fn(self) -> None:
        applied = []
        plan = TablePlan(TABLE_NAME, "create")
        outcome = apply_plan(plan, applied.append)
        self.assertEqual(applied, [plan])
        self.assertEqual(outcome.status, "created")
        self.assertEqual(exit_code_for(outcome), 0)

    def test_dry_run_never_applies(self) -> None:
        plan = TablePlan(TABLE_NAME, "create")
        outcome = apply_plan(plan, _unexpected_apply, dry_run=True)
        self.assertEqual(outcome.status, "would_create")
        self.assertEqual(exit_code_for(outcome), 0)

    def test_skip_exists_never_applies(self) -> None:
        plan = TablePlan(TABLE_NAME, "skip_exists")
        outcome = apply_plan(plan, _unexpected_apply)
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual(exit_code_for(outcome), 0)

    def test_create_failure_is_captured_with_exit_code_one(self) -> None:
        plan = TablePlan(TABLE_NAME, "create")

        def apply_fn(p: TablePlan) -> None:
            raise OperationalError("CREATE TABLE ...", {}, Exception("1044 access denied"))

        outcome = apply_plan(plan, apply_fn)
        self.assertEqual(outcome.status, "failed")
        self.assertIn("1044", outcome.error)
        self.assertEqual(exit_code_for(outcome), 1)


if __name__ == "__main__":
    unittest.main()
