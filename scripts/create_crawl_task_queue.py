"""共享 MySQL 建 crawl_task_queue 分布式爬取任务队列表（幂等，plan/apply）。

用法：.venv/Scripts/python.exe scripts/create_crawl_task_queue.py [--dry-run]

DDL 与 MediaCrawler/database/models.py::CrawlTaskQueue 逐列一致（utf8mb4、InnoDB）。
结构照抄 scripts/create_ks_tables.py。设计见
docs/superpowers/specs/2026-07-11-distributed-crawl-design.md §2。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

TABLE = "crawl_task_queue"

CREATE_DDL = """\
CREATE TABLE crawl_task_queue (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    platform VARCHAR(16) COMMENT '平台码 xhs/wb/tieba/zhihu/ks',
    keyword VARCHAR(255) COMMENT '裸关键词',
    status VARCHAR(16) DEFAULT 'pending' COMMENT 'pending/claimed/done/failed',
    priority INT DEFAULT 0 COMMENT '优先级，大者优先',
    claimed_by VARCHAR(64) COMMENT '认领 worker id',
    claimed_at BIGINT COMMENT '认领时间戳(ms)',
    lease_expires_at BIGINT COMMENT '租约到期(ms)',
    finished_at BIGINT COMMENT '完成时间戳(ms)',
    items_stored INT DEFAULT 0 COMMENT '新增入库条数',
    stop_reason VARCHAR(32) COMMENT '停止原因',
    created_at BIGINT COMMENT '播种时间戳(ms)',
    PRIMARY KEY (id),
    INDEX ix_crawl_task_queue_platform_status (platform, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分布式协同爬取任务队列'"""


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "skip_exists"


def plan_actions(existing_tables: Set[str], tables: Iterable[str] = (TABLE,)) -> List[TablePlan]:
    """纯逻辑：给定现有表名快照决定动作。不触碰真实 DB。"""
    plans: List[TablePlan] = []
    for table in tables:
        plans.append(TablePlan(table, "skip_exists" if table in existing_tables else "create"))
    return plans


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "skipped" | "failed"
    error: str = ""


def apply_plans(plans: List[TablePlan], apply_fn: Callable[[TablePlan], None], dry_run: bool = False) -> List[ApplyOutcome]:
    outcomes: List[ApplyOutcome] = []
    for plan in plans:
        if plan.action == "skip_exists":
            outcomes.append(ApplyOutcome(plan, "skipped"))
        elif plan.action == "create":
            if dry_run:
                outcomes.append(ApplyOutcome(plan, "would_create"))
                continue
            try:
                apply_fn(plan)
            except SQLAlchemyError as exc:
                outcomes.append(ApplyOutcome(plan, "failed", error=str(exc)))
            else:
                outcomes.append(ApplyOutcome(plan, "created"))
        else:
            raise ValueError(f"未知 action: {plan.action}")
    return outcomes


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    return 1 if any(o.status == "failed" for o in outcomes) else 0


def _apply_ddl(plan: TablePlan) -> None:
    print(f"执行: CREATE TABLE {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(CREATE_DDL))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="共享 MySQL 建 crawl_task_queue（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印 DDL，不建表")
    args = parser.parse_args(argv)

    existing_tables = set(inspect(engine).get_table_names())
    plans = plan_actions(existing_tables)

    for plan in plans:
        if plan.action == "skip_exists":
            print(f"[跳过] {plan.table}: 表已存在，跳过（幂等）")
        elif args.dry_run:
            print(f"[dry-run] 将执行:\n{CREATE_DDL}")

    outcomes = apply_plans(plans, _apply_ddl, dry_run=args.dry_run)
    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"[失败] {outcome.plan.table}: {outcome.error}")

    counts = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"完成：{counts}")
    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
