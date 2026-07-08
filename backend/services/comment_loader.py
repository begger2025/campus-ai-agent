"""从 MediaCrawler 原生评论表读取高赞评论摘录（xhs_note_comment）。

评论是舆情情绪的重要语料：帖子四平八稳、评论区炸锅的情况并不少见。
本模块按 note_id 批量取每帖点赞最高的前 N 条评论，供 Agent 分析文本
（analysis_text）与简报语料使用。

表不存在时（如 SQLite 演示快照未含 MediaCrawler 原生表）优雅返回空——
评论是增强信号，不是硬依赖。
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

COMMENT_TABLE = "xhs_note_comment"
COMMENT_MAX_CHARS = 200


def fetch_top_comments(
    db: Session,
    note_ids: list[str],
    *,
    per_note: int = 3,
) -> dict[str, list[str]]:
    """Return {note_id: [评论文本…]}，每帖最多 per_note 条，按点赞数降序。"""

    clean_ids = [str(note_id) for note_id in note_ids if str(note_id or "").strip()]
    if not clean_ids:
        return {}

    bind = db.get_bind()
    if COMMENT_TABLE not in inspect(bind).get_table_names():
        return {}

    placeholders = ", ".join(f":id{i}" for i in range(len(clean_ids)))
    params = {f"id{i}": note_id for i, note_id in enumerate(clean_ids)}
    # like_count 在原生表里是文本列；CAST 失败按 0 处理（MySQL/SQLite 行为一致）
    rows = db.execute(
        text(
            f"SELECT note_id, content, CAST(like_count AS UNSIGNED) AS likes "  # noqa: S608 —— 占位符拼接，无注入面
            f"FROM {COMMENT_TABLE} WHERE note_id IN ({placeholders}) "
            f"ORDER BY likes DESC, create_time DESC"
        )
        if bind.dialect.name == "mysql"
        else text(
            f"SELECT note_id, content, CAST(like_count AS INTEGER) AS likes "
            f"FROM {COMMENT_TABLE} WHERE note_id IN ({placeholders}) "
            f"ORDER BY likes DESC, create_time DESC"
        ),
        params,
    ).all()

    result: dict[str, list[str]] = {}
    for note_id, content, _likes in rows:
        comment = str(content or "").strip()[:COMMENT_MAX_CHARS]
        if not comment:
            continue
        bucket = result.setdefault(str(note_id), [])
        if len(bucket) < per_note:
            bucket.append(comment)
    return result
