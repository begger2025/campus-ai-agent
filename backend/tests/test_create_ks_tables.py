"""create_ks_tables 纯逻辑测试：建表/补列两态计划 + apply 层 + DDL 断言（不连库）。

DDL 必须与 MediaCrawler/database/models.py 的 KuaishouVideo/KuaishouVideoComment
逐列一致（含 video_id/comment_id 唯一索引与 comment_count 新列）。
风格同 test_create_zhihu_tables.py：plan/apply 分离、假 apply_fn、退出码断言。
"""

from __future__ import annotations

import unittest

from sqlalchemy.exc import OperationalError

from scripts.create_ks_tables import (
    ADD_COLUMN_DDL_BY_TABLE,
    CREATE_DDL_BY_TABLE,
    TABLES,
    TablePlan,
    apply_plans,
    exit_code_for,
    plan_ks_actions,
)

# 与 MediaCrawler/database/models.py::KuaishouVideo 逐列对齐的期望列定义片段
EXPECTED_VIDEO_COLUMNS = [
    "id INT NOT NULL AUTO_INCREMENT",
    "user_id VARCHAR(64)",
    "nickname TEXT",
    "avatar TEXT",
    "add_ts BIGINT",
    "last_modify_ts BIGINT",
    "video_id VARCHAR(255)",
    "video_type TEXT",
    "title TEXT",
    "`desc` TEXT",  # desc 是 MySQL 保留字，必须反引号
    "create_time BIGINT",
    "liked_count TEXT",
    "viewd_count TEXT",
    "comment_count TEXT",
    "video_url TEXT",
    "video_cover_url TEXT",
    "video_play_url TEXT",
    "source_keyword TEXT",
]

# 与 MediaCrawler/database/models.py::KuaishouVideoComment 逐列对齐
EXPECTED_COMMENT_COLUMNS = [
    "id INT NOT NULL AUTO_INCREMENT",
    "user_id TEXT",
    "nickname TEXT",
    "avatar TEXT",
    "add_ts BIGINT",
    "last_modify_ts BIGINT",
    "comment_id BIGINT",
    "video_id VARCHAR(255)",
    "content TEXT",
    "create_time BIGINT",
    "sub_comment_count TEXT",
]


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


class DdlTest(unittest.TestCase):
    """DDL 字符串断言：列清单 / 唯一索引 / 补列 ALTER / 引擎与字符集。"""

    def test_tables_cover_two_ks_tables_in_order(self) -> None:
        self.assertEqual(list(TABLES), ["kuaishou_video", "kuaishou_video_comment"])
        self.assertEqual(set(CREATE_DDL_BY_TABLE), set(TABLES))

    def test_kuaishou_video_columns_in_order(self) -> None:
        ddl = CREATE_DDL_BY_TABLE["kuaishou_video"]
        last_pos = -1
        for column in EXPECTED_VIDEO_COLUMNS:
            pos = ddl.find(column)
            self.assertGreater(pos, last_pos, f"列 {column!r} 缺失或顺序不对")
            last_pos = pos

    def test_kuaishou_video_comment_columns_in_order(self) -> None:
        ddl = CREATE_DDL_BY_TABLE["kuaishou_video_comment"]
        last_pos = -1
        for column in EXPECTED_COMMENT_COLUMNS:
            pos = ddl.find(column)
            self.assertGreater(pos, last_pos, f"列 {column!r} 缺失或顺序不对")
            last_pos = pos

    def test_unique_indexes_follow_model(self) -> None:
        # models.py 里 video_id/comment_id 已 unique=True；索引名沿用 SQLAlchemy
        # 默认命名 ix_表名_列名。
        self.assertIn(
            "UNIQUE INDEX ix_kuaishou_video_video_id (video_id)",
            CREATE_DDL_BY_TABLE["kuaishou_video"],
        )
        self.assertIn(
            "UNIQUE INDEX ix_kuaishou_video_comment_comment_id (comment_id)",
            CREATE_DDL_BY_TABLE["kuaishou_video_comment"],
        )

    def test_plain_indexes_follow_model(self) -> None:
        # models.py 里 index=True 的非唯一列
        self.assertIn(
            "INDEX ix_kuaishou_video_create_time (create_time)",
            CREATE_DDL_BY_TABLE["kuaishou_video"],
        )
        self.assertIn(
            "INDEX ix_kuaishou_video_comment_video_id (video_id)",
            CREATE_DDL_BY_TABLE["kuaishou_video_comment"],
        )

    def test_engine_and_charset(self) -> None:
        for table in TABLES:
            ddl = CREATE_DDL_BY_TABLE[table]
            self.assertIn("ENGINE=InnoDB", ddl)
            self.assertIn("DEFAULT CHARSET=utf8mb4", ddl)
            self.assertIn("PRIMARY KEY (id)", ddl)
            self.assertTrue(ddl.startswith(f"CREATE TABLE {table} ("))

    def test_add_column_ddl_matches_model(self) -> None:
        column, ddl = ADD_COLUMN_DDL_BY_TABLE["kuaishou_video"]
        self.assertEqual(column, "comment_count")
        self.assertTrue(ddl.startswith("ALTER TABLE kuaishou_video "))
        self.assertIn("ADD COLUMN comment_count TEXT", ddl)


class ApplyPlansTest(unittest.TestCase):
    """apply：dry-run 锁死不执行、create/add_column 双动作、失败不中断、退出码约定。"""

    def test_dry_run_never_applies_and_marks_would_statuses(self) -> None:
        plans = [
            TablePlan("kuaishou_video", "add_column"),
            TablePlan("kuaishou_video_comment", "create"),
        ]

        def apply_fn(plan: TablePlan) -> None:  # pragma: no cover - 必须不被调用
            raise AssertionError("dry-run 不应执行任何 DDL")

        outcomes = apply_plans(plans, apply_fn, dry_run=True)
        self.assertEqual(
            [o.status for o in outcomes], ["would_add_column", "would_create"]
        )
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_success_path_maps_create_and_add_column_statuses(self) -> None:
        plans = [
            TablePlan("kuaishou_video", "add_column"),
            TablePlan("kuaishou_video_comment", "create"),
        ]
        applied = []
        outcomes = apply_plans(plans, lambda plan: applied.append(plan.table))
        self.assertEqual(applied, ["kuaishou_video", "kuaishou_video_comment"])
        self.assertEqual([o.status for o in outcomes], ["column_added", "created"])
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_single_failure_does_not_stop_remaining_tables(self) -> None:
        plans = [
            TablePlan("kuaishou_video", "add_column"),
            TablePlan("kuaishou_video_comment", "create"),
        ]
        applied = []

        def apply_fn(plan: TablePlan) -> None:
            applied.append(plan.table)
            if plan.table == "kuaishou_video":
                raise OperationalError("ALTER ...", {}, Exception("1044 access denied"))

        outcomes = apply_plans(plans, apply_fn)

        self.assertEqual(applied, ["kuaishou_video", "kuaishou_video_comment"])
        statuses = {o.plan.table: o.status for o in outcomes}
        self.assertEqual(
            statuses,
            {"kuaishou_video": "failed", "kuaishou_video_comment": "created"},
        )
        failed = next(o for o in outcomes if o.status == "failed")
        self.assertIn("1044", failed.error)
        self.assertEqual(exit_code_for(outcomes), 1)

    def test_skip_exists_never_applies_and_exit_zero(self) -> None:
        plans = [
            TablePlan("kuaishou_video", "skip_exists"),
            TablePlan("kuaishou_video_comment", "skip_exists"),
        ]

        def apply_fn(plan: TablePlan) -> None:  # pragma: no cover
            raise AssertionError("skip_exists 不应触发 apply_fn")

        outcomes = apply_plans(plans, apply_fn)
        self.assertEqual([o.status for o in outcomes], ["skipped", "skipped"])
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_unknown_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            apply_plans([TablePlan("kuaishou_video", "bogus")], lambda plan: None)


if __name__ == "__main__":
    unittest.main()
