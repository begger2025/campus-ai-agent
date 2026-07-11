"""create_crawl_task_queue 纯逻辑测试：建表/跳过计划（不连库）。"""

import unittest

from scripts.create_crawl_task_queue import CREATE_DDL, TABLE, plan_actions


class PlanActionsTests(unittest.TestCase):
    def test_table_constant(self):
        self.assertEqual(TABLE, "crawl_task_queue")

    def test_missing_table_planned_create(self):
        plans = plan_actions(existing_tables=set())
        self.assertEqual([(p.table, p.action) for p in plans], [("crawl_task_queue", "create")])

    def test_existing_table_skipped(self):
        plans = plan_actions(existing_tables={"crawl_task_queue"})
        self.assertEqual([(p.table, p.action) for p in plans], [("crawl_task_queue", "skip_exists")])


class DdlTests(unittest.TestCase):
    def test_ddl_columns_in_order(self):
        cols = [
            "id", "platform", "keyword", "status", "priority", "claimed_by",
            "claimed_at", "lease_expires_at", "finished_at", "items_stored",
            "stop_reason", "created_at",
        ]
        last = -1
        for col in cols:
            pos = CREATE_DDL.find(col)
            self.assertGreater(pos, last, f"列 {col} 缺失或顺序错")
            last = pos

    def test_ddl_index_and_engine(self):
        self.assertIn("INDEX ix_crawl_task_queue_platform_status (platform, status)", CREATE_DDL)
        self.assertIn("ENGINE=InnoDB DEFAULT CHARSET=utf8mb4", CREATE_DDL)
        self.assertIn("PRIMARY KEY (id)", CREATE_DDL)


if __name__ == "__main__":
    unittest.main()
