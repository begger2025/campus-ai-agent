# -*- coding: utf-8 -*-
"""分布式协同爬取：任务队列的认领/完成/租约回收/结果回填（异步、raw SQL）。

并发正确性核心：认领用"乐观条件更新"——SELECT 一个 pending 候选，再
`UPDATE ... WHERE id=? AND status='pending'`，受影响行数==1 才算抢到；否则换候选重试。
行级条件 UPDATE 的 status 守卫保证两台机器绝不认领同一行，无需 8.0 专属的 SKIP LOCKED。
非 db 系存储优雅降级（claim 返回 None、complete no-op），保证队列模式在本地文件配置下不崩。
"""

from typing import Optional, Tuple

from sqlalchemy import text

import config
from database.db_session import get_session
from tools import utils

_DB_BACKENDS = {"db", "sqlite", "postgres"}


def _is_db_backend() -> bool:
    return config.SAVE_DATA_OPTION in _DB_BACKENDS


async def claim_task(platform: str, worker_id: str) -> Optional[dict]:
    """认领一个该平台的 pending 任务；成功返回 {"id","keyword"}，队列空返回 None。"""
    if not _is_db_backend():
        return None
    now = int(utils.get_current_timestamp())
    lease_ms = int(getattr(config, "CRAWL_QUEUE_LEASE_SEC", 1800)) * 1000
    retries = max(int(getattr(config, "CRAWL_QUEUE_CLAIM_RETRY", 5)), 1)

    async with get_session() as session:
        # 1) 回收过期租约（幂等）
        await session.execute(
            text(
                "UPDATE crawl_task_queue SET status='pending', claimed_by=NULL "
                "WHERE platform=:p AND status='claimed' AND lease_expires_at < :now"
            ),
            {"p": platform, "now": now},
        )
        await session.commit()

        for _ in range(retries):
            # 2) 读候选
            row = (
                await session.execute(
                    text(
                        "SELECT id, keyword FROM crawl_task_queue "
                        "WHERE platform=:p AND status='pending' "
                        "ORDER BY priority DESC, id ASC LIMIT 1"
                    ),
                    {"p": platform},
                )
            ).first()
            if row is None:
                return None
            task_id, keyword = int(row[0]), str(row[1])
            # 3) 条件认领（行级原子）
            result = await session.execute(
                text(
                    "UPDATE crawl_task_queue "
                    "SET status='claimed', claimed_by=:w, claimed_at=:now, lease_expires_at=:exp "
                    "WHERE id=:id AND status='pending'"
                ),
                {"w": worker_id, "now": now, "exp": now + lease_ms, "id": task_id},
            )
            await session.commit()
            if result.rowcount == 1:
                utils.logger.info(
                    f"[store.crawl_queue.claim_task] claimed id={task_id} keyword={keyword} by={worker_id}"
                )
                return {"id": task_id, "keyword": keyword}
            # 被别人抢先，换下一个候选
        return None


async def complete_task(task_id: int, status: str, items_stored: int, stop_reason: str) -> None:
    """把任务标记为 done/failed 并回填结果统计。"""
    if not _is_db_backend():
        return
    now = int(utils.get_current_timestamp())
    async with get_session() as session:
        await session.execute(
            text(
                "UPDATE crawl_task_queue SET status=:st, finished_at=:now, "
                "items_stored=:n, stop_reason=:r WHERE id=:id"
            ),
            {"st": status, "now": now, "n": int(items_stored), "r": str(stop_reason)[:32], "id": int(task_id)},
        )
        await session.commit()


async def max_run_history_id(platform: str) -> int:
    """结果回填基准：该平台 crawler_run_history 当前最大 id（无则 0）。"""
    if not _is_db_backend():
        return 0
    async with get_session() as session:
        val = (
            await session.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM crawler_run_history WHERE platform=:p"),
                {"p": platform},
            )
        ).scalar()
    return int(val or 0)


async def run_history_delta(platform: str, before_id: int) -> Tuple[int, str]:
    """取 id>before_id 的新增 run_history 行：返回（items_stored 之和, 最后一行 stop_reason）。

    宽泛词被拦截时 search 不写行 → 无新增行 → 返回 (0, "skipped")。
    """
    if not _is_db_backend():
        return 0, ""
    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT items_stored, stop_reason FROM crawler_run_history "
                    "WHERE platform=:p AND id > :bid ORDER BY id ASC"
                ),
                {"p": platform, "bid": int(before_id)},
            )
        ).all()
    if not rows:
        return 0, "skipped"
    total = sum(int(r[0] or 0) for r in rows)
    reason = str(rows[-1][1] or "completed")
    return total, reason
