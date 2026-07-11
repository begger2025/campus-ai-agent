"""processed_posts.heat_rank 加列 + 回填（幂等，plan/apply，支持 --dry-run）。

用法：
  .venv/Scripts/python.exe scripts/add_processed_posts_heat_rank.py --dry-run   # 只报告，不写
  .venv/Scripts/python.exe scripts/add_processed_posts_heat_rank.py             # 真正执行

为什么需要它：`Base.metadata.create_all()` **不会** ALTER 已存在的表，所以
`ProcessedPost` 上新增的 `heat_rank` 列不会自己出现在共享库里，必须显式迁移。

做两件事，都幂等：
  1. ALTER TABLE processed_posts ADD COLUMN heat_rank ...（列已存在 -> 跳过）
  2. 回填：
     a. web 行（证据交付进来的网页，没有互动量、heat_score 恒为 0）先按
        「来源权威度 + 核验强度」重算 heat_score；
     b. 按平台把所有行的 heat_score 重算成平台内百分位 heat_rank。
     回填是全量重算，重跑一次只会报告 0 行变化。

绝不 drop、绝不改别的列、绝不建表（表不存在就跳过）。
结构照抄 scripts/add_crawler_unique_indexes.py / scripts/create_crawl_task_queue.py。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.database import SessionLocal, engine, uses_mysql  # noqa: E402
from backend.models import ProcessedPost, RawPost  # noqa: E402
from backend.services.heat_ranking import (  # noqa: E402
    WEB_PLATFORM,
    _web_verification_status,
    calculate_web_heat_score,
    percentile_ranks,
    recompute_heat_ranks,
    refresh_web_heat_scores,
)

TABLE = "processed_posts"
COLUMN = "heat_rank"

# MySQL 建 NOT NULL DEFAULT 0：存量 331 行立刻拿到一个合法值（0 = "尚未归一化"），
# 随后由回填 pass 覆盖成真实百分位。AFTER heat_score 让它紧挨着展示用的那一列。
MYSQL_DDL = (
    f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} FLOAT NOT NULL DEFAULT 0 "
    "COMMENT '平台内归一化排序分（heat_score 在本平台内的百分位 0-100）' AFTER heat_score"
)
SQLITE_DDL = f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} FLOAT DEFAULT 0"


@dataclass
class ColumnPlan:
    table: str
    column: str
    action: str  # "add_column" | "skip_exists" | "skip_missing_table"


def plan_column(existing_tables: Set[str], existing_columns: Set[str]) -> ColumnPlan:
    """纯逻辑：给定表/列快照决定动作。不触碰真实 DB。"""

    if TABLE not in existing_tables:
        return ColumnPlan(TABLE, COLUMN, "skip_missing_table")
    if COLUMN in existing_columns:
        return ColumnPlan(TABLE, COLUMN, "skip_exists")
    return ColumnPlan(TABLE, COLUMN, "add_column")


@dataclass
class ApplyOutcome:
    plan: ColumnPlan
    status: str  # "added" | "would_add" | "skipped" | "failed"
    error: str = ""


def apply_plan(
    plan: ColumnPlan,
    apply_fn: Callable[[ColumnPlan], None],
    dry_run: bool = False,
) -> ApplyOutcome:
    if plan.action in ("skip_exists", "skip_missing_table"):
        return ApplyOutcome(plan, "skipped")
    if plan.action != "add_column":
        raise ValueError(f"未知 action: {plan.action}")
    if dry_run:
        return ApplyOutcome(plan, "would_add")
    try:
        apply_fn(plan)
    except SQLAlchemyError as exc:
        return ApplyOutcome(plan, "failed", error=str(exc))
    return ApplyOutcome(plan, "added")


def backfill_heat_ranks(db: Session) -> dict[str, int]:
    """回填：web 行先拿到来源权威度热度，然后所有行按平台算 heat_rank 百分位。

    全量重算，幂等：重跑一次两个计数都会是 0。返回 {"web_rescored": n, "ranked": n, "total": n}。
    """

    web_rescored = refresh_web_heat_scores(db)
    ranked = recompute_heat_ranks(db)
    return {
        "web_rescored": web_rescored,
        "ranked": ranked,
        "total": db.query(ProcessedPost).count(),
    }


def preview_backfill(db: Session) -> dict[str, Any]:
    """只读预演回填：报告每个平台会变成什么样，一个字都不写。

    关键约束：`--dry-run` 要在 heat_rank 列**还不存在**的时候也能跑，所以这里只能用
    显式列查询（SELECT id, platform, heat_score ...）。一旦 SELECT 整个 ORM 实体，
    SQLAlchemy 会把尚未创建的 heat_rank 列也带进 SQL，直接报 Unknown column。
    """

    rows = db.query(
        ProcessedPost.id, ProcessedPost.platform, ProcessedPost.heat_score, ProcessedPost.raw_post_id
    ).all()

    # web 行的 heat_score 会被"来源权威度 + 核验强度"重算，先把新值算出来。
    web_ids = [row.raw_post_id for row in rows if (row.platform or "") == WEB_PLATFORM]
    web_scores: dict[int, float] = {}
    if web_ids:
        raw_rows = db.query(RawPost).filter(RawPost.id.in_(web_ids)).all()
        status_by_raw_id = _web_verification_status(db, raw_rows)
        raw_by_id = {raw.id: raw for raw in raw_rows}
        for row in rows:
            if (row.platform or "") != WEB_PLATFORM:
                continue
            raw = raw_by_id.get(row.raw_post_id)
            web_scores[row.id] = calculate_web_heat_score(
                url=raw.url if raw is not None else "",
                verification_status=status_by_raw_id.get(row.raw_post_id),
            )

    web_rescored = sum(
        1
        for row in rows
        if row.id in web_scores and float(row.heat_score or 0.0) != web_scores[row.id]
    )

    by_platform: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        score = web_scores.get(row.id, float(row.heat_score or 0.0))
        by_platform.setdefault(row.platform or "", []).append((row.id, score))

    platforms: list[dict[str, Any]] = []
    ranked = 0
    for platform, entries in sorted(by_platform.items()):
        scores = [score for _id, score in entries]
        ranks = percentile_ranks(scores)
        ranked += len(ranks)
        ordered = sorted(scores)
        platforms.append(
            {
                "platform": platform,
                "rows": len(entries),
                "median_heat_score": ordered[len(ordered) // 2] if ordered else 0.0,
                "min_heat_rank": min(ranks) if ranks else 0.0,
                "max_heat_rank": max(ranks) if ranks else 0.0,
            }
        )

    return {
        "total": len(rows),
        "ranked": ranked,
        "web_rescored": web_rescored,
        "platforms": platforms,
    }


def _alter_add_column(plan: ColumnPlan) -> None:
    ddl = MYSQL_DDL if uses_mysql() else SQLITE_DDL
    print(f"执行: {ddl}")
    with engine.begin() as conn:
        conn.execute(text(ddl))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="processed_posts.heat_rank 加列 + 回填（幂等）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只报告将执行的操作与回填影响，不做任何写入"
    )
    args = parser.parse_args(argv)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    existing_columns = (
        {col["name"] for col in inspector.get_columns(TABLE)}
        if TABLE in existing_tables
        else set()
    )

    plan = plan_column(existing_tables, existing_columns)
    if plan.action == "skip_missing_table":
        print(f"[跳过] {TABLE}: 表不存在，跳过（本脚本不建表）")
    elif plan.action == "skip_exists":
        print(f"[跳过] {TABLE}.{COLUMN}: 列已存在，跳过（幂等）")
    elif args.dry_run:
        ddl = MYSQL_DDL if uses_mysql() else SQLITE_DDL
        print(f"[dry-run] 将执行: {ddl}")

    outcome = apply_plan(plan, _alter_add_column, dry_run=args.dry_run)
    if outcome.status == "failed":
        print(f"[失败] {TABLE}.{COLUMN}: ALTER 失败：{outcome.error}")
        return 1

    if plan.action == "skip_missing_table":
        print(f"完成：column={outcome.status} backfill=skipped")
        return 0

    db = SessionLocal()
    try:
        if args.dry_run:
            # 只读预演：显式列查询，heat_rank 列还不存在也能跑。
            report = preview_backfill(db)
            print("\n[dry-run] 回填预演（行数 / heat_score 中位数 -> heat_rank 值域）：")
            for row in report["platforms"]:
                print(
                    f"    {row['platform'] or '(空)':<8} rows={row['rows']:<5} "
                    f"median_heat_score={row['median_heat_score']:<10g} "
                    f"heat_rank {row['min_heat_rank']:g}~{row['max_heat_rank']:g}"
                )
            print(
                f"\n[dry-run] 将回填：web_rescored={report['web_rescored']} "
                f"ranked={report['ranked']} total_rows={report['total']}（未做任何写入）"
            )
            db.rollback()
            print(f"完成：column={outcome.status} backfill=would_backfill")
            return 0

        report = backfill_heat_ranks(db)
        db.commit()
        print(
            f"\n回填完成：web_rescored={report['web_rescored']} "
            f"ranked={report['ranked']} total_rows={report['total']}"
        )
        print(f"完成：column={outcome.status} backfill=done")
    except Exception as exc:  # noqa: BLE001 - 回填失败不能留下半吊子事务
        db.rollback()
        print(f"[失败] 回填失败，已回滚：{exc}")
        return 1
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
