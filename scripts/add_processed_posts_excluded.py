"""processed_posts.excluded / excluded_reason 加列（幂等，支持 --dry-run）。

用法：
  .venv/Scripts/python.exe scripts/add_processed_posts_excluded.py --dry-run   # 只报告，不写
  .venv/Scripts/python.exe scripts/add_processed_posts_excluded.py             # 真正执行

## 这两列干什么

**数据质量管控**：管理员剔除无关帖（同名的台湾国立中山大学、蹭校名的地产/床垫集采广告、
早期乱填关键词爬回的 Python 教程帖…）。剔除后它不进任何下游——舆情分析页看不到、
事件聚类不收、舆情助手检索不到。

**剔除 ≠ 审核**：帖子是从公开平台爬来的**客观事实**，审核别人已经公开发布的话语义上
说不通；需要人工定夺的是 **AI 的主张**（事件的聚类和研判），那道闸门在
`public_events.status` 上。这里要的不是闸门，是质量管控。

**软删除而不是 DELETE**：上一次清噪声帖是直接删库（375 行 / 6 张表 / 撞了外键回滚）。
剔除可恢复，也留得下理由。

## 为什么需要这个脚本

`Base.metadata.create_all()` **不会** ALTER 已存在的表，所以 `ProcessedPost` 上新增的
两列不会自己出现在共享库里，必须显式迁移。

只加列，不回填（存量全部默认 excluded=0，即"未剔除"——这正是当前的真实状态）。
绝不 drop、绝不改别的列、绝不建表（表不存在就跳过）。
结构照抄 scripts/add_processed_posts_heat_rank.py。
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
from backend.models import ProcessedPost  # noqa: E402

TABLE = "processed_posts"

# 两列一起加。excluded 上建索引：每一个下游查询（舆情分析页 / 事件聚类 / agent 检索）
# 都要按它过滤，是最高频的过滤条件。
COLUMNS: list[tuple[str, str, str]] = [
    (
        "excluded",
        "ALTER TABLE processed_posts ADD COLUMN excluded TINYINT(1) NOT NULL DEFAULT 0 "
        "COMMENT '管理员剔除的无关帖：不进舆情分析页/事件聚类/agent检索' AFTER concerns_json",
        "ALTER TABLE processed_posts ADD COLUMN excluded BOOLEAN NOT NULL DEFAULT 0",
    ),
    (
        "excluded_reason",
        "ALTER TABLE processed_posts ADD COLUMN excluded_reason VARCHAR(200) NOT NULL DEFAULT '' "
        "COMMENT '剔除理由（恢复时清空）' AFTER excluded",
        "ALTER TABLE processed_posts ADD COLUMN excluded_reason VARCHAR(200) NOT NULL DEFAULT ''",
    ),
]

INDEX_NAME = "ix_processed_posts_excluded"
MYSQL_INDEX_DDL = f"CREATE INDEX {INDEX_NAME} ON {TABLE} (excluded)"
SQLITE_INDEX_DDL = f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} (excluded)"


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
    """迁移后的状态：多少条帖子、多少条已剔除（只读）。"""

    db = SessionLocal()
    try:
        total = db.query(ProcessedPost).count()
        excluded = db.query(ProcessedPost).filter(ProcessedPost.excluded.is_(True)).count()
        print(f"\n当前：processed_posts 共 {total} 条，其中已剔除 {excluded} 条（未剔除 {total - excluded} 条）")
    finally:
        db.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="processed_posts.excluded / excluded_reason 加列（幂等）"
    )
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
