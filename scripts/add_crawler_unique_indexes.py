"""原生表 note_id/comment_id 唯一索引迁移脚本（幂等 + 有重复则拒绝）。

用法：
  .venv/Scripts/python.exe scripts/add_crawler_unique_indexes.py [--dry-run]

行为：
  - 表不存在 -> 跳过（不建库、不建表，MediaCrawler 自己的 create_all 负责）。
  - 该列已有唯一索引 -> 跳过（幂等，可重复运行）。
  - 该列存在重复值 -> 拒绝加索引，打印重复样本，不 ALTER，脚本以退出码 1 结束。
  - 否则 -> ALTER TABLE ... ADD UNIQUE INDEX ...（--dry-run 时只打印不执行）。

设计见 docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 1。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

# (表名, 列名, 索引名)
TARGETS: List[Tuple[str, str, str]] = [
    ("xhs_note", "note_id", "uk_xhs_note_note_id"),
    ("xhs_note_comment", "comment_id", "uk_xhs_note_comment_comment_id"),
    ("weibo_note", "note_id", "uk_weibo_note_note_id"),
    ("weibo_note_comment", "comment_id", "uk_weibo_note_comment_comment_id"),
    ("tieba_note", "note_id", "uk_tieba_note_note_id"),
    ("tieba_comment", "comment_id", "uk_tieba_comment_comment_id"),
    ("zhihu_content", "content_id", "uk_zhihu_content_content_id"),
    ("zhihu_comment", "comment_id", "uk_zhihu_comment_comment_id"),
]


@dataclass
class IndexPlan:
    table: str
    column: str
    index_name: str
    action: str  # "create" | "skip_missing_table" | "skip_exists" | "refuse_duplicates"
    duplicate_samples: list = field(default_factory=list)


def plan_unique_indexes(
    existing_tables: Set[str],
    index_map: Dict[str, List[dict]],
    duplicate_counter: Callable[[str, str], Sequence[Tuple[object, int]]],
    targets: Iterable[Tuple[str, str, str]] = TARGETS,
) -> List[IndexPlan]:
    """纯逻辑：给定表/索引快照与查重回调，决定每个目标的动作。不触碰真实 DB。

    Args:
        existing_tables: 数据库中实际存在的表名集合。
        index_map: {table: [inspect(engine).get_indexes(table) 的元素, ...]}；
            每个元素形如 {"name": ..., "column_names": [...], "unique": bool, ...}。
        duplicate_counter: (table, column) -> [(重复值, 出现次数), ...]。
            只有在表存在且该列尚无唯一索引时才会被调用。
        targets: 待规划的 (table, column, index_name) 列表，默认 TARGETS。
    """
    plans: List[IndexPlan] = []
    for table, column, index_name in targets:
        if table not in existing_tables:
            plans.append(IndexPlan(table, column, index_name, "skip_missing_table"))
            continue

        indexes = index_map.get(table, [])
        has_unique_index = any(
            idx.get("unique") and list(idx.get("column_names") or []) == [column]
            for idx in indexes
        )
        if has_unique_index:
            plans.append(IndexPlan(table, column, index_name, "skip_exists"))
            continue

        samples = list(duplicate_counter(table, column))
        if samples:
            plans.append(
                IndexPlan(
                    table, column, index_name, "refuse_duplicates", duplicate_samples=samples
                )
            )
            continue

        plans.append(IndexPlan(table, column, index_name, "create"))
    return plans


def _duplicate_samples_from_db(table: str, column: str) -> List[Tuple[object, int]]:
    sql = text(
        f"SELECT {column}, COUNT(*) c FROM {table} GROUP BY {column} HAVING c > 1 LIMIT 5"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [(row[0], row[1]) for row in rows]


@dataclass
class ApplyOutcome:
    plan: IndexPlan
    status: str  # "created" | "would_create" | "skipped" | "refused" | "failed"
    error: str = ""


def apply_plans(
    plans: List[IndexPlan],
    apply_fn: Callable[[IndexPlan], None],
    dry_run: bool = False,
) -> List[ApplyOutcome]:
    """按 plan 逐目标执行并归类结果。create 动作调用注入的 apply_fn 落地 ALTER。

    健壮性关键：单张表的 ALTER 失败（SQLAlchemyError，如 1071 索引过长、1062
    竞态插入产生的重复）不会中断整体——记为 failed 后继续处理其余目标，绝不让
    异常逃出去打断后面的表、吞掉汇总。apply_fn 便于测试注入假实现，主流程注入
    真正连库执行的 _alter_index。
    """
    outcomes: List[ApplyOutcome] = []
    for plan in plans:
        if plan.action in ("skip_missing_table", "skip_exists"):
            outcomes.append(ApplyOutcome(plan, "skipped"))
        elif plan.action == "refuse_duplicates":
            outcomes.append(ApplyOutcome(plan, "refused"))
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


def summarize_outcomes(outcomes: List[ApplyOutcome]) -> dict:
    counts = {"created": 0, "would_create": 0, "skipped": 0, "refused": 0, "failed": 0}
    for outcome in outcomes:
        counts[outcome.status] += 1
    return counts


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    """有任何目标失败或被拒绝 → 退出码 1，否则 0。"""
    return 1 if any(o.status in ("failed", "refused") for o in outcomes) else 0


def _alter_index(plan: IndexPlan) -> None:
    """真正连库执行单条 ALTER（DDL 自动提交）。失败抛 SQLAlchemyError，交由 apply_plans 兜住。"""
    sql = f"ALTER TABLE {plan.table} ADD UNIQUE INDEX {plan.index_name} ({plan.column})"
    print(f"执行: {sql}")
    with engine.begin() as conn:
        conn.execute(text(sql))


def _describe_plan(plan: IndexPlan, dry_run: bool) -> None:
    """打印计划阶段的说明（跳过/拒绝/试运行预览）；create 的实际执行不在这里。"""
    if plan.action == "skip_missing_table":
        print(f"[跳过] {plan.table}: 表不存在，跳过")
    elif plan.action == "skip_exists":
        print(f"[跳过] {plan.table}.{plan.column}: 已有唯一索引，跳过")
    elif plan.action == "refuse_duplicates":
        print(f"[拒绝] {plan.table}.{plan.column}: 发现重复值，拒绝加唯一索引。重复样本：")
        for value, count in plan.duplicate_samples:
            print(f"    {plan.column} = {value!r} 重复 {count} 次")
    elif plan.action == "create" and dry_run:
        sql = f"ALTER TABLE {plan.table} ADD UNIQUE INDEX {plan.index_name} ({plan.column})"
        print(f"[dry-run] 将执行: {sql}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="原生表 note_id/comment_id 唯一索引迁移脚本（幂等 + 有重复则拒绝）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将执行的操作，不实际 ALTER TABLE"
    )
    args = parser.parse_args(argv)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    target_table_names = {table for table, _, _ in TARGETS}
    index_map = {
        table: inspector.get_indexes(table)
        for table in existing_tables
        if table in target_table_names
    }

    plans = plan_unique_indexes(existing_tables, index_map, _duplicate_samples_from_db)

    for plan in plans:
        _describe_plan(plan, args.dry_run)

    outcomes = apply_plans(plans, _alter_index, dry_run=args.dry_run)

    for outcome in outcomes:
        if outcome.status == "failed":
            print(
                f"[失败] {outcome.plan.table}.{outcome.plan.column}: "
                f"ALTER 失败，已跳过并继续处理其余表：{outcome.error}"
            )

    counts = summarize_outcomes(outcomes)
    created_label = "would_create" if args.dry_run else "created"
    created = counts["would_create"] if args.dry_run else counts["created"]
    print(
        f"完成：{created_label}={created} skipped={counts['skipped']} "
        f"refused={counts['refused']} failed={counts['failed']}"
    )
    if counts["refused"]:
        print("存在被拒绝的表（有重复值），请先人工核实/清理重复数据后再重新运行本脚本。")
    if counts["failed"]:
        print("存在 ALTER 失败的表（见上方 [失败] 明细），其余目标已照常处理；请排查后重跑。")

    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
