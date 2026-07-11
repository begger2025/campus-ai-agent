"""共享 MySQL 建快手两张原生表（幂等，逐表 plan/apply；表已存在时兼作 comment_count 补列迁移）。

用法：
  .venv/Scripts/python.exe scripts/create_ks_tables.py [--dry-run]

行为（单脚本覆盖建表/补列两态）：
  - 表不存在 -> CREATE TABLE ...（含 comment_count 列与唯一索引）。
  - 表已存在且缺 comment_count 列 -> ALTER TABLE ADD COLUMN（仅 kuaishou_video 有此新列需求）。
  - 表已存在且列齐 -> 跳过（幂等，可重复运行）。
  - 单表失败（权限/连接等）-> 记为 failed 继续处理其余表，脚本以退出码 1 结束。

DDL 与 MediaCrawler/database/models.py 的 KuaishouVideo/KuaishouVideoComment 逐列一致
（utf8mb4，InnoDB）；video_id/comment_id 唯一索引随建表自带（索引名沿用 SQLAlchemy 默认
命名 ix_表名_列名）——线上后跑 add_crawler_unique_indexes.py 时自动 skip。
结构照抄 scripts/create_zhihu_tables.py。
设计见 docs/superpowers/specs/2026-07-11-ks-crawler-retrofit-design.md §3。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.database import engine  # noqa: E402

TABLES: Tuple[str, ...] = ("kuaishou_video", "kuaishou_video_comment")

# 与 MediaCrawler/database/models.py::KuaishouVideo 逐列一致；desc 是 MySQL 保留字需反引号。
_KS_VIDEO_DDL = """\
CREATE TABLE kuaishou_video (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    user_id VARCHAR(64) COMMENT '用户ID',
    nickname TEXT COMMENT '用户昵称',
    avatar TEXT COMMENT '用户头像',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    video_id VARCHAR(255) COMMENT '视频ID',
    video_type TEXT COMMENT '视频类型',
    title TEXT COMMENT '视频标题',
    `desc` TEXT COMMENT '视频描述',
    create_time BIGINT COMMENT '创建时间戳',
    liked_count TEXT COMMENT '点赞数',
    viewd_count TEXT COMMENT '观看数',
    comment_count TEXT COMMENT '评论数',
    video_url TEXT COMMENT '视频URL',
    video_cover_url TEXT COMMENT '视频封面URL',
    video_play_url TEXT COMMENT '视频播放URL',
    source_keyword TEXT COMMENT '来源关键词',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_kuaishou_video_video_id (video_id),
    INDEX ix_kuaishou_video_create_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='快手视频'"""

# 与 MediaCrawler/database/models.py::KuaishouVideoComment 逐列一致。
_KS_COMMENT_DDL = """\
CREATE TABLE kuaishou_video_comment (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    user_id TEXT COMMENT '用户ID',
    nickname TEXT COMMENT '用户昵称',
    avatar TEXT COMMENT '用户头像',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    comment_id BIGINT COMMENT '评论ID',
    video_id VARCHAR(255) COMMENT '视频ID',
    content TEXT COMMENT '评论内容',
    create_time BIGINT COMMENT '创建时间戳',
    sub_comment_count TEXT COMMENT '子评论数',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_kuaishou_video_comment_comment_id (comment_id),
    INDEX ix_kuaishou_video_comment_video_id (video_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='快手视频评论'"""

CREATE_DDL_BY_TABLE: Dict[str, str] = {
    "kuaishou_video": _KS_VIDEO_DDL,
    "kuaishou_video_comment": _KS_COMMENT_DDL,
}

# 表已存在时需要探测/补齐的新列（目前只有 kuaishou_video.comment_count）
ADD_COLUMN_DDL_BY_TABLE: Dict[str, Tuple[str, str]] = {
    "kuaishou_video": (
        "comment_count",
        "ALTER TABLE kuaishou_video ADD COLUMN comment_count TEXT COMMENT '评论数'",
    ),
}


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "add_column" | "skip_exists"


def plan_ks_actions(
    existing_tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
    tables: Iterable[str] = TABLES,
) -> List[TablePlan]:
    """纯逻辑：给定库中现有表名与各表列名快照，逐表决定动作。不触碰真实 DB。"""
    plans: List[TablePlan] = []
    for table in tables:
        if table not in existing_tables:
            plans.append(TablePlan(table, "create"))
            continue
        column_spec = ADD_COLUMN_DDL_BY_TABLE.get(table)
        if column_spec and column_spec[0] not in columns_by_table.get(table, set()):
            plans.append(TablePlan(table, "add_column"))
        else:
            plans.append(TablePlan(table, "skip_exists"))
    return plans


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "column_added" | "would_add_column" | "skipped" | "failed"
    error: str = ""


def apply_plans(
    plans: List[TablePlan],
    apply_fn: Callable[[TablePlan], None],
    dry_run: bool = False,
) -> List[ApplyOutcome]:
    """按 plan 逐表执行并归类结果。create/add_column 调用注入的 apply_fn 落地 DDL。

    单表失败（SQLAlchemyError）不中断整体——记为 failed 后继续处理其余表。
    """
    would_by_action = {"create": "would_create", "add_column": "would_add_column"}
    done_by_action = {"create": "created", "add_column": "column_added"}
    outcomes: List[ApplyOutcome] = []
    for plan in plans:
        if plan.action == "skip_exists":
            outcomes.append(ApplyOutcome(plan, "skipped"))
        elif plan.action in ("create", "add_column"):
            if dry_run:
                outcomes.append(ApplyOutcome(plan, would_by_action[plan.action]))
                continue
            try:
                apply_fn(plan)
            except SQLAlchemyError as exc:
                outcomes.append(ApplyOutcome(plan, "failed", error=str(exc)))
            else:
                outcomes.append(ApplyOutcome(plan, done_by_action[plan.action]))
        else:
            raise ValueError(f"未知 action: {plan.action}")
    return outcomes


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    """有任何表执行失败 → 退出码 1，否则 0。"""
    return 1 if any(o.status == "failed" for o in outcomes) else 0


def _ddl_for(plan: TablePlan) -> str:
    if plan.action == "create":
        return CREATE_DDL_BY_TABLE[plan.table]
    return ADD_COLUMN_DDL_BY_TABLE[plan.table][1]


def _apply_ddl(plan: TablePlan) -> None:
    """真正连库执行 DDL。失败抛 SQLAlchemyError，交由 apply_plans 兜住。"""
    print(f"执行: {plan.action} {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(_ddl_for(plan)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="共享 MySQL 建快手两张原生表（幂等；表已存在时兼作 comment_count 补列迁移）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将执行的 DDL，不实际执行"
    )
    args = parser.parse_args(argv)

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    columns_by_table: Dict[str, Set[str]] = {}
    for table in TABLES:
        if table in existing_tables:
            columns_by_table[table] = {col["name"] for col in insp.get_columns(table)}

    plans = plan_ks_actions(existing_tables, columns_by_table)

    for plan in plans:
        if plan.action == "skip_exists":
            print(f"[跳过] {plan.table}: 表已存在且列齐，跳过（幂等）")
        elif args.dry_run:
            print(f"[dry-run] 将执行:\n{_ddl_for(plan)}")

    outcomes = apply_plans(plans, _apply_ddl, dry_run=args.dry_run)

    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"[失败] {outcome.plan.table}: 执行失败：{outcome.error}")

    counts: Dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(f"完成：{counts}")
    if counts.get("failed"):
        print("存在执行失败的表（见上方 [失败] 明细），请检查数据库连接与账号 DDL 权限后重跑本脚本。")

    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
