"""public_events.curated 加列（幂等，支持 --dry-run）。

用法：
  .venv/Scripts/python.exe scripts/add_public_events_curated.py --dry-run   # 只报告，不写
  .venv/Scripts/python.exe scripts/add_public_events_curated.py             # 真正执行

## 这一列干什么

**人工修正锁**：管理员对事件做过任何人工修正（重命名 / 合并 / 增删成员 / 人工创建）
→ curated=TRUE。再生成管线对 curated 行只读（persist 跳过 upsert），其成员帖退出
聚类池——延续「机器绝不覆盖人的决定」的既有原则（同 actor 归档语义）。
设计与阶段计划见 docs/superpowers/plans/2026-07-16-manual-event-curation.md。

只加列不回填（存量全部默认 curated=0 = 未人工修正，正是当前真实状态）。
绝不 drop、绝不改别的列、绝不建表。结构照抄 scripts/add_processed_posts_excluded.py。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import SessionLocal, engine, uses_mysql  # noqa: E402
from backend.models import PublicEvent  # noqa: E402

TABLE = "public_events"

COLUMNS: list[tuple[str, str, str]] = [
    (
        "curated",
        "ALTER TABLE public_events ADD COLUMN curated TINYINT(1) NOT NULL DEFAULT 0 "
        "COMMENT '人工修正锁：再生成管线对该行只读，成员帖退出聚类池' AFTER status",
        "ALTER TABLE public_events ADD COLUMN curated BOOLEAN NOT NULL DEFAULT 0",
    ),
]

INDEX_NAME = "ix_public_events_curated"
MYSQL_INDEX_DDL = f"CREATE INDEX {INDEX_NAME} ON {TABLE} (curated)"
SQLITE_INDEX_DDL = f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} (curated)"


@dataclass
class Step:
    name: str
    kind: str  # "column" | "index"
    action: str  # "add" | "skip_exists" | "skip_missing_table"
    ddl: str = ""


def plan_steps(
    existing_tables: Set[str], existing_columns: Set[str], existing_indexes: Set[str], mysql: bool
) -> list[Step]:
    """纯逻辑：给定表/列/索引快照决定动作。不触碰真实 DB（可单测）。"""

    if TABLE not in existing_tables:
        return [Step(TABLE, "column", "skip_missing_table")]

    steps: list[Step] = []
    for column, mysql_ddl, sqlite_ddl in COLUMNS:
        if column in existing_columns:
            steps.append(Step(column, "column", "skip_exists"))
        else:
            steps.append(Step(column, "column", "add", mysql_ddl if mysql else sqlite_ddl))

    if INDEX_NAME in existing_indexes:
        steps.append(Step(INDEX_NAME, "index", "skip_exists"))
    else:
        steps.append(
            Step(INDEX_NAME, "index", "add", MYSQL_INDEX_DDL if mysql else SQLITE_INDEX_DDL)
        )
    return steps


def _execute(ddl: str) -> None:
    print(f"执行: {ddl}")
    with engine.begin() as conn:
        conn.execute(text(ddl))


def apply_steps(
    steps: list[Step], execute: Callable[[str], None], dry_run: bool = False
) -> dict[str, int]:
    counts = {"added": 0, "would_add": 0, "skipped": 0, "failed": 0}
    for step in steps:
        if step.action in ("skip_exists", "skip_missing_table"):
            reason = "列/索引已存在，跳过（幂等）" if step.action == "skip_exists" else "表不存在，跳过"
            print(f"[跳过] {step.name}: {reason}")
            counts["skipped"] += 1
            continue
        if dry_run:
            print(f"[dry-run] 将执行: {step.ddl}")
            counts["would_add"] += 1
            continue
        try:
            execute(step.ddl)
        except SQLAlchemyError as exc:
            print(f"[失败] {step.name}: {exc}")
            counts["failed"] += 1
            continue
        counts["added"] += 1
    return counts


def report_current_state() -> None:
    db = SessionLocal()
    try:
        total = db.query(PublicEvent).count()
        curated = db.query(PublicEvent).filter(PublicEvent.curated.is_(True)).count()
        print(f"\n当前：public_events 共 {total} 行，其中人工修正 {curated} 行")
    finally:
        db.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="public_events.curated 加列（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只报告将执行的操作，不做任何写入")
    args = parser.parse_args(argv)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    existing_columns = (
        {col["name"] for col in inspector.get_columns(TABLE)} if TABLE in existing_tables else set()
    )
    existing_indexes = (
        {idx["name"] for idx in inspector.get_indexes(TABLE)} if TABLE in existing_tables else set()
    )

    steps = plan_steps(existing_tables, existing_columns, existing_indexes, uses_mysql())
    counts = apply_steps(steps, _execute, dry_run=args.dry_run)

    if counts["failed"]:
        print(f"\n完成（有失败）：{counts}")
        return 1

    print(f"\n完成：{counts}")
    if not args.dry_run and TABLE in existing_tables:
        report_current_state()
    return 0


if __name__ == "__main__":
    sys.exit(main())
