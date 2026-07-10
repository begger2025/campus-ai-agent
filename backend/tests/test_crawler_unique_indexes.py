from __future__ import annotations

import unittest

from scripts.add_crawler_unique_indexes import IndexPlan, TARGETS, plan_unique_indexes


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


if __name__ == "__main__":
    unittest.main()
