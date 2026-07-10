from __future__ import annotations

import unittest

from sqlalchemy.exc import OperationalError

from scripts.add_crawler_unique_indexes import (
    IndexPlan,
    TARGETS,
    apply_plans,
    exit_code_for,
    plan_unique_indexes,
    summarize_outcomes,
)


def _unexpected_call(table: str, column: str):
    raise AssertionError(
        f"duplicate_counter 不应在此场景下被调用: table={table} column={column}"
    )


class PlanUniqueIndexesTest(unittest.TestCase):
    """纯逻辑测试：不连接任何数据库，全部用 fake 的表/索引/查重快照。"""

    def test_targets_match_specification(self) -> None:
        self.assertEqual(
            list(TARGETS),
            [
                ("xhs_note", "note_id", "uk_xhs_note_note_id"),
                ("xhs_note_comment", "comment_id", "uk_xhs_note_comment_comment_id"),
                ("weibo_note", "note_id", "uk_weibo_note_note_id"),
                ("weibo_note_comment", "comment_id", "uk_weibo_note_comment_comment_id"),
                ("tieba_note", "note_id", "uk_tieba_note_note_id"),
                ("tieba_comment", "comment_id", "uk_tieba_comment_comment_id"),
            ],
        )

    def test_missing_table_is_skipped(self) -> None:
        plans = plan_unique_indexes(
            existing_tables=set(),
            index_map={},
            duplicate_counter=_unexpected_call,
        )
        self.assertEqual(len(plans), len(TARGETS))
        for plan in plans:
            self.assertIsInstance(plan, IndexPlan)
            self.assertEqual(plan.action, "skip_missing_table")
            self.assertEqual(plan.duplicate_samples, [])

    def test_existing_unique_index_is_skipped(self) -> None:
        table, column, index_name = TARGETS[0]
        index_map = {
            table: [
                {"name": index_name, "unique": True, "column_names": [column]},
            ]
        }
        plans = plan_unique_indexes(
            existing_tables={table},
            index_map=index_map,
            duplicate_counter=_unexpected_call,
        )
        plan = next(p for p in plans if p.table == table)
        self.assertEqual(plan.action, "skip_exists")
        self.assertEqual(plan.duplicate_samples, [])

    def test_non_unique_index_and_no_duplicates_creates(self) -> None:
        table, column, index_name = TARGETS[0]
        index_map = {
            table: [
                {"name": f"idx_{column}", "unique": False, "column_names": [column]},
            ]
        }
        plans = plan_unique_indexes(
            existing_tables={table},
            index_map=index_map,
            duplicate_counter=lambda t, c: [],
        )
        plan = next(p for p in plans if p.table == table)
        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.duplicate_samples, [])

    def test_duplicates_present_refuses_and_carries_samples(self) -> None:
        table, column, index_name = TARGETS[0]
        samples = [("abc123", 3), ("def456", 2)]
        plans = plan_unique_indexes(
            existing_tables={table},
            index_map={table: []},
            duplicate_counter=lambda t, c: samples,
        )
        plan = next(p for p in plans if p.table == table)
        self.assertEqual(plan.action, "refuse_duplicates")
        self.assertEqual(plan.duplicate_samples, samples)

    def test_unique_index_on_different_column_does_not_count(self) -> None:
        """索引存在但列不匹配（比如复合索引或别的列）不能算作已加固。"""
        table, column, index_name = TARGETS[0]
        index_map = {
            table: [
                {"name": "some_other_index", "unique": True, "column_names": ["other_col"]},
            ]
        }
        plans = plan_unique_indexes(
            existing_tables={table},
            index_map=index_map,
            duplicate_counter=lambda t, c: [],
        )
        plan = next(p for p in plans if p.table == table)
        self.assertEqual(plan.action, "create")

    def test_all_six_targets_planned_in_order(self) -> None:
        plans = plan_unique_indexes(
            existing_tables={t for t, _, _ in TARGETS},
            index_map={},
            duplicate_counter=lambda t, c: [],
        )
        self.assertEqual(len(plans), 6)
        self.assertEqual(
            [(p.table, p.column, p.index_name) for p in plans],
            list(TARGETS),
        )
        for plan in plans:
            self.assertEqual(plan.action, "create")


class ApplyPlansTest(unittest.TestCase):
    """Issue 2 回归：单表 ALTER 失败不中断整体；汇总/退出码正确。全程不连库（注入假 apply_fn）。"""

    @staticmethod
    def _create_plan(table: str) -> IndexPlan:
        return IndexPlan(table, "note_id", f"uk_{table}_note_id", "create")

    def test_single_alter_failure_does_not_stop_remaining_targets(self):
        plans = [self._create_plan("t1"), self._create_plan("t2"), self._create_plan("t3")]
        applied = []

        def apply_fn(plan: IndexPlan) -> None:
            applied.append(plan.table)
            if plan.table == "t2":
                # 模拟 MySQL 1071 索引过长 / 1062 竞态重复等 DDL 错误
                raise OperationalError("ALTER ...", {}, Exception("1071 index too long"))

        outcomes = apply_plans(plans, apply_fn)

        # 关键：t2 失败后 t3 仍被尝试（没有中断）
        self.assertEqual(applied, ["t1", "t2", "t3"])
        statuses = {o.plan.table: o.status for o in outcomes}
        self.assertEqual(statuses, {"t1": "created", "t2": "failed", "t3": "created"})
        # 失败明细带上了异常信息
        failed = next(o for o in outcomes if o.status == "failed")
        self.assertIn("1071", failed.error)

        counts = summarize_outcomes(outcomes)
        self.assertEqual(counts["created"], 2)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(exit_code_for(outcomes), 1)

    def test_all_created_yields_exit_code_zero(self):
        plans = [self._create_plan("t1"), self._create_plan("t2")]
        outcomes = apply_plans(plans, lambda plan: None)
        self.assertEqual(summarize_outcomes(outcomes)["created"], 2)
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_refused_yields_exit_code_one_without_applying(self):
        plans = [IndexPlan("t1", "note_id", "uk", "refuse_duplicates", duplicate_samples=[("x", 2)])]

        def apply_fn(plan: IndexPlan) -> None:  # pragma: no cover - 必须不被调用
            raise AssertionError("refuse_duplicates 不应触发 apply_fn")

        outcomes = apply_plans(plans, apply_fn)
        self.assertEqual(outcomes[0].status, "refused")
        self.assertEqual(summarize_outcomes(outcomes)["refused"], 1)
        self.assertEqual(exit_code_for(outcomes), 1)

    def test_skip_outcomes_do_not_apply_and_exit_zero(self):
        plans = [
            IndexPlan("t1", "note_id", "uk1", "skip_missing_table"),
            IndexPlan("t2", "note_id", "uk2", "skip_exists"),
        ]

        def apply_fn(plan: IndexPlan) -> None:  # pragma: no cover
            raise AssertionError("skip_* 不应触发 apply_fn")

        outcomes = apply_plans(plans, apply_fn)
        self.assertEqual([o.status for o in outcomes], ["skipped", "skipped"])
        self.assertEqual(summarize_outcomes(outcomes)["skipped"], 2)
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_dry_run_never_applies_and_marks_would_create(self):
        plans = [self._create_plan("t1")]

        def apply_fn(plan: IndexPlan) -> None:  # pragma: no cover
            raise AssertionError("dry-run 不应执行 ALTER")

        outcomes = apply_plans(plans, apply_fn, dry_run=True)
        self.assertEqual(outcomes[0].status, "would_create")
        self.assertEqual(summarize_outcomes(outcomes)["would_create"], 1)
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_mixed_failure_and_refusal_exit_one(self):
        plans = [
            self._create_plan("t1"),
            IndexPlan("t2", "note_id", "uk", "refuse_duplicates", duplicate_samples=[("y", 3)]),
            self._create_plan("t3"),
        ]

        def apply_fn(plan: IndexPlan) -> None:
            if plan.table == "t3":
                raise OperationalError("ALTER ...", {}, Exception("boom"))

        outcomes = apply_plans(plans, apply_fn)
        counts = summarize_outcomes(outcomes)
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["refused"], 1)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(exit_code_for(outcomes), 1)


if __name__ == "__main__":
    unittest.main()
