"""共享 MySQL 建 crawler_run_history 通用爬取历史表（幂等）。

用法：
  .venv/Scripts/python.exe scripts/create_crawler_run_history.py [--dry-run]

行为：
  - 表已存在 -> 跳过（幂等，可重复运行）。
  - 表不存在 -> CREATE TABLE ...（--dry-run 时只打印将执行的 DDL，不实际建表）。
  - 建表失败（权限/连接等）-> 打印错误，脚本以退出码 1 结束。

DDL 与 MediaCrawler/database/models.py 的 CrawlerRunHistory 逐列一致（含 platform、
source_keyword 两个普通索引，utf8mb4，InnoDB）。写侧是 MediaCrawler 三平台 search()，
读侧是 backend/services/keyword_suggestion_adapter.py 的贫瘠词判定。
设计见 docs/superpowers/specs/2026-07-10-keyword-quality-pipeline-design.md P1-2/P1-3。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

TABLE_NAME = "crawler_run_history"

# 与 MediaCrawler/database/models.py::CrawlerRunHistory 逐列一致；
# 索引名沿用 SQLAlchemy create_all 的默认命名（ix_表名_列名），两侧建表结果等价。
CREATE_TABLE_DDL = f"""\
CREATE TABLE {TABLE_NAME} (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    platform VARCHAR(16) COMMENT '平台（xhs | wb | tieba）',
    source_keyword VARCHAR(255) COMMENT '搜索关键词（主题限定组合后）',
    started_at BIGINT COMMENT '开始时间戳（毫秒）',
    finished_at BIGINT COMMENT '结束时间戳（毫秒）',
    pages_fetched INT DEFAULT 0 COMMENT '实际抓取页数',
    items_seen INT DEFAULT 0 COMMENT '平台返回原始条数（过滤前）',
    items_stored INT DEFAULT 0 COMMENT '真正入库条数（过滤/跳过后）',
    stop_reason VARCHAR(64) DEFAULT '' COMMENT '停止原因（quota_reached | empty_page | window_exhausted | exception | completed）',
    PRIMARY KEY (id),
    INDEX ix_crawler_run_history_platform (platform),
    INDEX ix_crawler_run_history_source_keyword (source_keyword)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通用爬取历史：三平台每关键词一轮 search 一行（纯追加日志表）'"""


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "skip_exists"


def plan_create_table(existing_tables: Set[str], table: str = TABLE_NAME) -> TablePlan:
    """纯逻辑：给定库中现有表名快照，决定建表动作。不触碰真实 DB。"""
    if table in existing_tables:
        return TablePlan(table, "skip_exists")
    return TablePlan(table, "create")


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "skipped" | "failed"
    error: str = ""


def apply_plan(
    plan: TablePlan,
    apply_fn: Callable[[TablePlan], None],
    dry_run: bool = False,
) -> ApplyOutcome:
    """按 plan 执行并归类结果。create 动作调用注入的 apply_fn 落地 CREATE TABLE。

    建表失败（SQLAlchemyError）不抛出——记为 failed 交给退出码，保证汇总总能打印。
    apply_fn 便于测试注入假实现，主流程注入真正连库执行的 _create_table。
    """
    if plan.action == "skip_exists":
        return ApplyOutcome(plan, "skipped")
    if plan.action == "create":
        if dry_run:
            return ApplyOutcome(plan, "would_create")
        try:
            apply_fn(plan)
        except SQLAlchemyError as exc:
            return ApplyOutcome(plan, "failed", error=str(exc))
        return ApplyOutcome(plan, "created")
    raise ValueError(f"未知 action: {plan.action}")


def exit_code_for(outcome: ApplyOutcome) -> int:
    """建表失败 → 退出码 1，否则 0。"""
    return 1 if outcome.status == "failed" else 0


def _create_table(plan: TablePlan) -> None:
    """真正连库执行 CREATE TABLE（DDL 自动提交）。失败抛 SQLAlchemyError，交由 apply_plan 兜住。"""
    print(f"执行: CREATE TABLE {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_DDL))


def _describe_plan(plan: TablePlan, dry_run: bool) -> None:
    """打印计划阶段的说明（跳过/试运行预览）；create 的实际执行不在这里。"""
    if plan.action == "skip_exists":
        print(f"[跳过] {plan.table}: 表已存在，跳过（幂等）")
    elif plan.action == "create" and dry_run:
        print(f"[dry-run] 将执行:\n{CREATE_TABLE_DDL}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="共享 MySQL 建 crawler_run_history 通用爬取历史表（幂等）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将执行的 DDL，不实际 CREATE TABLE"
    )
    args = parser.parse_args(argv)

    existing_tables = set(inspect(engine).get_table_names())
    plan = plan_create_table(existing_tables)
    _describe_plan(plan, args.dry_run)

    outcome = apply_plan(plan, _create_table, dry_run=args.dry_run)

    if outcome.status == "failed":
        print(f"[失败] {plan.table}: 建表失败：{outcome.error}")

    print(
        f"完成：table={plan.table} status={outcome.status}"
    )
    if outcome.status == "failed":
        print("请检查数据库连接与账号 DDL 权限后重跑本脚本。")

    return exit_code_for(outcome)


if __name__ == "__main__":
    sys.exit(main())
