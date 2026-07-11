"""create_ks_tables 纯逻辑测试：建表/补列两态计划（不连库）。"""

import unittest

from scripts.create_ks_tables import ADD_COLUMN_DDL_BY_TABLE, TABLES, plan_ks_actions


class PlanKsActionsTests(unittest.TestCase):
    def test_tables_constant(self):
        self.assertEqual(TABLES, ("kuaishou_video", "kuaishou_video_comment"))
        self.assertIn("kuaishou_video", ADD_COLUMN_DDL_BY_TABLE)

    def test_missing_tables_planned_create(self):
        plans = plan_ks_actions(existing_tables=set(), columns_by_table={})
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "create"), ("kuaishou_video_comment", "create")],
        )

    def test_existing_table_missing_column_planned_add_column(self):
        plans = plan_ks_actions(
            existing_tables={"kuaishou_video", "kuaishou_video_comment"},
            columns_by_table={
                "kuaishou_video": {"id", "video_id", "liked_count"},
                "kuaishou_video_comment": {"id", "comment_id"},
            },
        )
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "add_column"), ("kuaishou_video_comment", "skip_exists")],
        )

    def test_existing_with_column_all_skip(self):
        plans = plan_ks_actions(
            existing_tables={"kuaishou_video", "kuaishou_video_comment"},
            columns_by_table={
                "kuaishou_video": {"id", "video_id", "comment_count"},
                "kuaishou_video_comment": {"id", "comment_id"},
            },
        )
        self.assertEqual(
            [(p.table, p.action) for p in plans],
            [("kuaishou_video", "skip_exists"), ("kuaishou_video_comment", "skip_exists")],
        )


if __name__ == "__main__":
    unittest.main()
