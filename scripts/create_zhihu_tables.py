"""共享 MySQL 建知乎三张原生表（幂等，逐表 plan/apply）。

用法：
  .venv/Scripts/python.exe scripts/create_zhihu_tables.py [--dry-run]

行为：
  - 表已存在 -> 跳过（幂等，可重复运行，逐表 skip_exists）。
  - 表不存在 -> CREATE TABLE ...（--dry-run 时只打印将执行的 DDL，不实际建表）。
  - 单表建表失败（权限/连接等）-> 记为 failed 继续处理其余表，脚本以退出码 1 结束。

DDL 与 MediaCrawler/database/models.py 的 ZhihuContent/ZhihuComment/ZhihuCreator 逐列
一致（utf8mb4，InnoDB）；content_id/comment_id 两列在 Z2 已改 unique=True、user_id 本就
unique，故三处直接随建表建 UNIQUE INDEX（索引名沿用 SQLAlchemy create_all 的默认命名
ix_表名_列名，两侧建表结果等价）——线上后跑 add_crawler_unique_indexes.py 时自动 skip。
结构照抄 scripts/create_crawler_run_history.py（plan/apply 分离、--dry-run、退出码约定）。
设计见 docs/superpowers/specs/2026-07-10-zhihu-crawler-retrofit-design.md §3。
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

TABLES: Tuple[str, ...] = ("zhihu_content", "zhihu_comment", "zhihu_creator")

# 与 MediaCrawler/database/models.py::ZhihuContent 逐列一致；desc 是 MySQL 保留字需反引号。
_ZHIHU_CONTENT_DDL = """\
CREATE TABLE zhihu_content (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    content_id VARCHAR(64) COMMENT '内容ID',
    content_type TEXT COMMENT '内容类型',
    content_text TEXT COMMENT '内容文本',
    content_url TEXT COMMENT '内容URL',
    question_id VARCHAR(255) COMMENT '问题ID',
    title TEXT COMMENT '标题',
    `desc` TEXT COMMENT '描述',
    created_time VARCHAR(32) COMMENT '创建时间',
    updated_time TEXT COMMENT '更新时间',
    voteup_count INT DEFAULT 0 COMMENT '赞同数',
    comment_count INT DEFAULT 0 COMMENT '评论数',
    source_keyword TEXT COMMENT '来源关键词',
    user_id VARCHAR(255) COMMENT '用户ID',
    user_link TEXT COMMENT '用户链接',
    user_nickname TEXT COMMENT '用户昵称',
    user_avatar TEXT COMMENT '用户头像',
    user_url_token TEXT COMMENT '用户URL Token',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_zhihu_content_content_id (content_id),
    INDEX ix_zhihu_content_created_time (created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知乎内容（回答/文章/视频）'"""

# 与 MediaCrawler/database/models.py::ZhihuComment 逐列一致。
_ZHIHU_COMMENT_DDL = """\
CREATE TABLE zhihu_comment (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    comment_id VARCHAR(64) COMMENT '评论ID',
    parent_comment_id VARCHAR(64) COMMENT '父评论ID',
    content TEXT COMMENT '评论内容',
    publish_time VARCHAR(32) COMMENT '发布时间',
    ip_location TEXT COMMENT 'IP地址位置',
    sub_comment_count INT DEFAULT 0 COMMENT '子评论数',
    like_count INT DEFAULT 0 COMMENT '点赞数',
    dislike_count INT DEFAULT 0 COMMENT '点踩数',
    content_id VARCHAR(64) COMMENT '内容ID',
    content_type TEXT COMMENT '内容类型',
    user_id VARCHAR(64) COMMENT '用户ID',
    user_link TEXT COMMENT '用户链接',
    user_nickname TEXT COMMENT '用户昵称',
    user_avatar TEXT COMMENT '用户头像',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_zhihu_comment_comment_id (comment_id),
    INDEX ix_zhihu_comment_publish_time (publish_time),
    INDEX ix_zhihu_comment_content_id (content_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知乎评论'"""

# 与 MediaCrawler/database/models.py::ZhihuCreator 逐列一致（anwser_count 拼写照抄上游）。
_ZHIHU_CREATOR_DDL = """\
CREATE TABLE zhihu_creator (
    id INT NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    user_id VARCHAR(64) COMMENT '用户ID',
    user_link TEXT COMMENT '用户链接',
    user_nickname TEXT COMMENT '用户昵称',
    user_avatar TEXT COMMENT '用户头像',
    url_token TEXT COMMENT 'URL Token',
    gender TEXT COMMENT '性别',
    ip_location TEXT COMMENT 'IP地址位置',
    follows INT DEFAULT 0 COMMENT '关注数',
    fans INT DEFAULT 0 COMMENT '粉丝数',
    anwser_count INT DEFAULT 0 COMMENT '回答数',
    video_count INT DEFAULT 0 COMMENT '视频数',
    question_count INT DEFAULT 0 COMMENT '问题数',
    article_count INT DEFAULT 0 COMMENT '文章数',
    column_count INT DEFAULT 0 COMMENT '专栏数',
    get_voteup_count INT DEFAULT 0 COMMENT '获赞数',
    add_ts BIGINT COMMENT '添加时间戳',
    last_modify_ts BIGINT COMMENT '最后修改时间戳',
    PRIMARY KEY (id),
    UNIQUE INDEX ix_zhihu_creator_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知乎创作者'"""

DDL_BY_TABLE: Dict[str, str] = {
    "zhihu_content": _ZHIHU_CONTENT_DDL,
    "zhihu_comment": _ZHIHU_COMMENT_DDL,
    "zhihu_creator": _ZHIHU_CREATOR_DDL,
}


@dataclass
class TablePlan:
    table: str
    action: str  # "create" | "skip_exists"


def plan_create_tables(
    existing_tables: Set[str], tables: Iterable[str] = TABLES
) -> List[TablePlan]:
    """纯逻辑：给定库中现有表名快照，逐表决定建表动作。不触碰真实 DB。"""
    plans: List[TablePlan] = []
    for table in tables:
        if table in existing_tables:
            plans.append(TablePlan(table, "skip_exists"))
        else:
            plans.append(TablePlan(table, "create"))
    return plans


@dataclass
class ApplyOutcome:
    plan: TablePlan
    status: str  # "created" | "would_create" | "skipped" | "failed"
    error: str = ""


def apply_plans(
    plans: List[TablePlan],
    apply_fn: Callable[[TablePlan], None],
    dry_run: bool = False,
) -> List[ApplyOutcome]:
    """按 plan 逐表执行并归类结果。create 动作调用注入的 apply_fn 落地 CREATE TABLE。

    单表建表失败（SQLAlchemyError）不中断整体——记为 failed 后继续处理其余表，
    保证汇总总能打印。apply_fn 便于测试注入假实现，主流程注入真正连库执行的 _create_table。
    """
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


def summarize_outcomes(outcomes: List[ApplyOutcome]) -> dict:
    counts = {"created": 0, "would_create": 0, "skipped": 0, "failed": 0}
    for outcome in outcomes:
        counts[outcome.status] += 1
    return counts


def exit_code_for(outcomes: List[ApplyOutcome]) -> int:
    """有任何表建表失败 → 退出码 1，否则 0。"""
    return 1 if any(o.status == "failed" for o in outcomes) else 0


def _create_table(plan: TablePlan) -> None:
    """真正连库执行 CREATE TABLE（DDL 自动提交）。失败抛 SQLAlchemyError，交由 apply_plans 兜住。"""
    print(f"执行: CREATE TABLE {plan.table} ...")
    with engine.begin() as conn:
        conn.execute(text(DDL_BY_TABLE[plan.table]))


def _describe_plan(plan: TablePlan, dry_run: bool) -> None:
    """打印计划阶段的说明（跳过/试运行预览）；create 的实际执行不在这里。"""
    if plan.action == "skip_exists":
        print(f"[跳过] {plan.table}: 表已存在，跳过（幂等）")
    elif plan.action == "create" and dry_run:
        print(f"[dry-run] 将执行:\n{DDL_BY_TABLE[plan.table]}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="共享 MySQL 建知乎三张原生表（幂等，逐表 plan/apply）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将执行的 DDL，不实际 CREATE TABLE"
    )
    args = parser.parse_args(argv)

    existing_tables = set(inspect(engine).get_table_names())
    plans = plan_create_tables(existing_tables)

    for plan in plans:
        _describe_plan(plan, args.dry_run)

    outcomes = apply_plans(plans, _create_table, dry_run=args.dry_run)

    for outcome in outcomes:
        if outcome.status == "failed":
            print(f"[失败] {outcome.plan.table}: 建表失败：{outcome.error}")

    counts = summarize_outcomes(outcomes)
    created_label = "would_create" if args.dry_run else "created"
    created = counts["would_create"] if args.dry_run else counts["created"]
    print(
        f"完成：{created_label}={created} skipped={counts['skipped']} "
        f"failed={counts['failed']}"
    )
    if counts["failed"]:
        print("存在建表失败的表（见上方 [失败] 明细），请检查数据库连接与账号 DDL 权限后重跑本脚本。")

    return exit_code_for(outcomes)


if __name__ == "__main__":
    sys.exit(main())
