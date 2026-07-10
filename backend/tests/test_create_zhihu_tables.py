"""Z6：知乎三表建表脚本（纯逻辑测试，不连接任何数据库）。

DDL 必须与 MediaCrawler/database/models.py 的 ZhihuContent/ZhihuComment/ZhihuCreator
逐列一致（含 Z2 后的 content_id/comment_id 唯一索引与 user_id 唯一索引）。
风格同 test_crawler_unique_indexes.py：plan/apply 分离、假 apply_fn、退出码断言。
"""

from __future__ import annotations

import unittest

from sqlalchemy.exc import OperationalError

from scripts.create_zhihu_tables import (
    DDL_BY_TABLE,
    TABLES,
    TablePlan,
    apply_plans,
    exit_code_for,
    plan_create_tables,
    summarize_outcomes,
)

# 与 MediaCrawler/database/models.py 逐列对齐的期望列定义片段
EXPECTED_CONTENT_COLUMNS = [
    "id INT NOT NULL AUTO_INCREMENT",
    "content_id VARCHAR(64)",
    "content_type TEXT",
    "content_text TEXT",
    "content_url TEXT",
    "question_id VARCHAR(255)",
    "title TEXT",
    "`desc` TEXT",  # desc 是 MySQL 保留字，必须反引号
    "created_time VARCHAR(32)",
    "updated_time TEXT",
    "voteup_count INT DEFAULT 0",
    "comment_count INT DEFAULT 0",
    "source_keyword TEXT",
    "user_id VARCHAR(255)",
    "user_link TEXT",
    "user_nickname TEXT",
    "user_avatar TEXT",
    "user_url_token TEXT",
    "add_ts BIGINT",
    "last_modify_ts BIGINT",
]

EXPECTED_COMMENT_COLUMNS = [
    "id INT NOT NULL AUTO_INCREMENT",
    "comment_id VARCHAR(64)",
    "parent_comment_id VARCHAR(64)",
    "content TEXT",
    "publish_time VARCHAR(32)",
    "ip_location TEXT",
    "sub_comment_count INT DEFAULT 0",
    "like_count INT DEFAULT 0",
    "dislike_count INT DEFAULT 0",
    "content_id VARCHAR(64)",
    "content_type TEXT",
    "user_id VARCHAR(64)",
    "user_link TEXT",
    "user_nickname TEXT",
    "user_avatar TEXT",
    "add_ts BIGINT",
    "last_modify_ts BIGINT",
]

EXPECTED_CREATOR_COLUMNS = [
    "id INT NOT NULL AUTO_INCREMENT",
    "user_id VARCHAR(64)",
    "user_link TEXT",
    "user_nickname TEXT",
    "user_avatar TEXT",
    "url_token TEXT",
    "gender TEXT",
    "ip_location TEXT",
    "follows INT DEFAULT 0",
    "fans INT DEFAULT 0",
    "anwser_count INT DEFAULT 0",
    "video_count INT DEFAULT 0",
    "question_count INT DEFAULT 0",
    "article_count INT DEFAULT 0",
    "column_count INT DEFAULT 0",
    "get_voteup_count INT DEFAULT 0",
    "add_ts BIGINT",
    "last_modify_ts BIGINT",
]


class DdlTest(unittest.TestCase):
    """DDL 字符串断言：列清单 / 唯一索引 / 引擎与字符集。"""

    def test_tables_cover_three_zhihu_tables_in_order(self) -> None:
        self.assertEqual(
            list(TABLES), ["zhihu_content", "zhihu_comment", "zhihu_creator"]
        )
        self.assertEqual(set(DDL_BY_TABLE), set(TABLES))

    def test_zhihu_content_columns(self) -> None:
        ddl = DDL_BY_TABLE["zhihu_content"]
        for column in EXPECTED_CONTENT_COLUMNS:
            self.assertIn(column, ddl)

    def test_zhihu_comment_columns(self) -> None:
        ddl = DDL_BY_TABLE["zhihu_comment"]
        for column in EXPECTED_COMMENT_COLUMNS:
            self.assertIn(column, ddl)

    def test_zhihu_creator_columns(self) -> None:
        ddl = DDL_BY_TABLE["zhihu_creator"]
        for column in EXPECTED_CREATOR_COLUMNS:
            self.assertIn(column, ddl)

    def test_unique_indexes_follow_z2_model(self) -> None:
        # Z2 已把 content_id/comment_id 改 unique=True；user_id 本就 unique。
        # 索引名沿用 SQLAlchemy 默认 ix_表名_列名。
        self.assertIn(
            "UNIQUE INDEX ix_zhihu_content_content_id (content_id)",
            DDL_BY_TABLE["zhihu_content"],
        )
        self.assertIn(
            "UNIQUE INDEX ix_zhihu_comment_comment_id (comment_id)",
            DDL_BY_TABLE["zhihu_comment"],
        )
        self.assertIn(
            "UNIQUE INDEX ix_zhihu_creator_user_id (user_id)",
            DDL_BY_TABLE["zhihu_creator"],
        )

    def test_plain_indexes_follow_model(self) -> None:
        # models.py 里 index=True 的非唯一列
        self.assertIn(
            "INDEX ix_zhihu_content_created_time (created_time)",
            DDL_BY_TABLE["zhihu_content"],
        )
        self.assertIn(
            "INDEX ix_zhihu_comment_publish_time (publish_time)",
            DDL_BY_TABLE["zhihu_comment"],
        )
        self.assertIn(
            "INDEX ix_zhihu_comment_content_id (content_id)",
            DDL_BY_TABLE["zhihu_comment"],
        )

    def test_engine_and_charset(self) -> None:
        for table in TABLES:
            ddl = DDL_BY_TABLE[table]
            self.assertIn("ENGINE=InnoDB", ddl)
            self.assertIn("DEFAULT CHARSET=utf8mb4", ddl)
            self.assertIn("PRIMARY KEY (id)", ddl)
            self.assertTrue(ddl.startswith(f"CREATE TABLE {table} ("))


class PlanCreateTablesTest(unittest.TestCase):
    """plan 三态：全缺 -> 全建；部分存在 -> 混合；全存在 -> 全跳过（幂等逐表 skip_exists）。"""

    def test_all_missing_plans_create_for_each_table(self) -> None:
        plans = plan_create_tables(existing_tables=set())
        self.assertEqual(len(plans), 3)
        self.assertEqual([p.table for p in plans], list(TABLES))
        for plan in plans:
            self.assertEqual(plan.action, "create")

    def test_partial_existing_mixes_create_and_skip(self) -> None:
        plans = plan_create_tables(existing_tables={"zhihu_content"})
        actions = {p.table: p.action for p in plans}
        self.assertEqual(
            actions,
            {
                "zhihu_content": "skip_exists",
                "zhihu_comment": "create",
                "zhihu_creator": "create",
            },
        )

    def test_all_existing_skips_everything(self) -> None:
        plans = plan_create_tables(existing_tables=set(TABLES))
        for plan in plans:
            self.assertEqual(plan.action, "skip_exists")


class ApplyPlansTest(unittest.TestCase):
    """apply：dry-run 锁死不执行、失败不中断、退出码约定。"""

    @staticmethod
    def _create_plan(table: str) -> TablePlan:
        return TablePlan(table, "create")

    def test_dry_run_never_applies_and_marks_would_create(self) -> None:
        plans = [self._create_plan(t) for t in TABLES]

        def apply_fn(plan: TablePlan) -> None:  # pragma: no cover - 必须不被调用
            raise AssertionError("dry-run 不应执行 CREATE TABLE")

        outcomes = apply_plans(plans, apply_fn, dry_run=True)
        self.assertEqual([o.status for o in outcomes], ["would_create"] * 3)
        self.assertEqual(summarize_outcomes(outcomes)["would_create"], 3)
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_skip_exists_never_applies_and_exit_zero(self) -> None:
        plans = [TablePlan("zhihu_content", "skip_exists")]

        def apply_fn(plan: TablePlan) -> None:  # pragma: no cover
            raise AssertionError("skip_exists 不应触发 apply_fn")

        outcomes = apply_plans(plans, apply_fn)
        self.assertEqual(outcomes[0].status, "skipped")
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_single_failure_does_not_stop_remaining_tables(self) -> None:
        plans = [self._create_plan(t) for t in TABLES]
        applied = []

        def apply_fn(plan: TablePlan) -> None:
            applied.append(plan.table)
            if plan.table == "zhihu_comment":
                raise OperationalError("CREATE ...", {}, Exception("1044 access denied"))

        outcomes = apply_plans(plans, apply_fn)

        self.assertEqual(applied, list(TABLES))  # 失败后仍继续处理后续表
        statuses = {o.plan.table: o.status for o in outcomes}
        self.assertEqual(
            statuses,
            {
                "zhihu_content": "created",
                "zhihu_comment": "failed",
                "zhihu_creator": "created",
            },
        )
        failed = next(o for o in outcomes if o.status == "failed")
        self.assertIn("1044", failed.error)
        self.assertEqual(exit_code_for(outcomes), 1)

    def test_all_created_yields_exit_code_zero(self) -> None:
        plans = [self._create_plan(t) for t in TABLES]
        outcomes = apply_plans(plans, lambda plan: None)
        self.assertEqual(summarize_outcomes(outcomes)["created"], 3)
        self.assertEqual(exit_code_for(outcomes), 0)

    def test_unknown_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            apply_plans([TablePlan("zhihu_content", "bogus")], lambda plan: None)


if __name__ == "__main__":
    unittest.main()
