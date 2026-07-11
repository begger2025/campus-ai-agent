"""从 MediaCrawler 原生评论表读取高赞评论摘录，按平台路由到对应表/列。

评论是舆情情绪的重要语料：帖子四平八稳、评论区炸锅的情况并不少见。
本模块按 (platform, 裸 note_id) 批量取每帖点赞最高的前 N 条评论，供 Agent
分析文本（analysis_text）与简报语料使用。

五个平台的原生评论表列名不同（线上实测），故用 PLATFORM_COMMENT_SPEC 路由：

| 平台 | 表 | 关联列 | 点赞列 |
|---|---|---|---|
| xhs   | xhs_note_comment   | note_id    | like_count         |
| weibo | weibo_note_comment | note_id    | comment_like_count |
| tieba | tieba_comment      | note_id    | 无（字面量 0）      |
| zhihu | zhihu_comment      | content_id | like_count         |
| ks    | kuaishou_video_comment | video_id | 无（字面量 0）      |

五张表都有 add_ts（BigInteger 毫秒）与 content，排序统一 `ORDER BY likes DESC, add_ts DESC`。

表不存在时（如 SQLite 演示快照未含 MediaCrawler 原生表）优雅返回空——
评论是增强信号，不是硬依赖。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

COMMENT_MAX_CHARS = 200

# 每平台原生评论表的路由：表名、关联列、点赞列（None=无点赞列，用字面量 0）。
PLATFORM_COMMENT_SPEC: dict[str, dict] = {
    "xhs": {"table": "xhs_note_comment", "join_col": "note_id", "like_col": "like_count"},
    "weibo": {
        "table": "weibo_note_comment",
        "join_col": "note_id",
        "like_col": "comment_like_count",
    },
    "tieba": {"table": "tieba_comment", "join_col": "note_id", "like_col": None},
    "zhihu": {"table": "zhihu_comment", "join_col": "content_id", "like_col": "like_count"},
    "ks": {"table": "kuaishou_video_comment", "join_col": "video_id", "like_col": None},
}


def fetch_top_comments(
    db: Session,
    refs: list[tuple[str, str]],
    *,
    per_note: int = 3,
) -> dict[tuple[str, str], list[str]]:
    """Return {(platform, bare_id): [评论文本…]}，每帖最多 per_note 条，按点赞降序。

    refs 为 (platform, 裸 note_id) 列表。内部按 platform 分组，未在 SPEC 的平台跳过；
    每平台先判表存在（不存在跳过，保留演示快照优雅降级）。键含 platform，避免跨平台
    裸 id 撞车。
    """

    # 按平台分组裸 id，过滤空值与未知平台
    groups: dict[str, list[str]] = {}
    for platform, bare_id in refs:
        p = str(platform or "").strip()
        b = str(bare_id or "").strip()
        if not p or not b or p not in PLATFORM_COMMENT_SPEC:
            continue
        groups.setdefault(p, []).append(b)
    if not groups:
        return {}

    bind = db.get_bind()
    existing_tables = set(inspect(bind).get_table_names())
    # like_count 在原生表里是文本列；CAST 失败按 0 处理。整数方言：mysql=UNSIGNED、其它=INTEGER。
    int_type = "UNSIGNED" if bind.dialect.name == "mysql" else "INTEGER"

    result: dict[tuple[str, str], list[str]] = {}
    for platform, bare_ids in groups.items():
        spec = PLATFORM_COMMENT_SPEC[platform]
        table = spec["table"]
        if table not in existing_tables:
            continue  # 优雅降级：表不存在直接跳过该平台

        join_col = spec["join_col"]
        like_col = spec["like_col"]
        like_expr = f"CAST({like_col} AS {int_type})" if like_col else "0"

        unique_ids = list(dict.fromkeys(bare_ids))
        placeholders = ", ".join(f":id{i}" for i in range(len(unique_ids)))
        params = {f"id{i}": bid for i, bid in enumerate(unique_ids)}
        rows = db.execute(
            text(
                f"SELECT {join_col} AS ref, content, {like_expr} AS likes "  # noqa: S608 —— 表/列来自固定 SPEC，值走占位符，无注入面
                f"FROM {table} WHERE {join_col} IN ({placeholders}) "
                f"ORDER BY likes DESC, add_ts DESC"
            ),
            params,
        ).all()

        for ref, content, _likes in rows:
            comment = str(content or "").strip()[:COMMENT_MAX_CHARS]
            if not comment:
                continue
            bucket = result.setdefault((platform, str(ref)), [])
            if len(bucket) < per_note:
                bucket.append(comment)
    return result
