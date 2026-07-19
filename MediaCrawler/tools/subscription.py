# -*- coding: utf-8 -*-
"""订阅式爬取的纯逻辑：增量刹车判定。

订阅（盯官方账号 / 盯贴吧吧）与关键词搜索的本质区别是**增量语义**：
源是固定的、存量是巨大的（中山大学吧 345 万帖），每轮只要"上次之后的新帖"。
刹车两道：
  1. 追平停止（caught_up）——整页都已入库说明已经追上上次的进度，立即停；
  2. 页保护上限（page_cap）——首轮冷启动没有"上次"，靠页数上限兜底，
     防止一头扎进百万级存量。

纯函数、无 IO，便于单测锁定语义。
"""

from __future__ import annotations

STOP_CAUGHT_UP = "caught_up"
STOP_PAGE_CAP = "page_cap"


def split_new_ids(page_ids: list[str], existing_ids: set[str]) -> list[str]:
    """返回本页里真正的新 id：去空、页内去重、剔除已入库，保持原序。"""

    seen: set[str] = set()
    fresh: list[str] = []
    for raw in page_ids:
        note_id = str(raw or "").strip()
        if not note_id or note_id in seen or note_id in existing_ids:
            continue
        seen.add(note_id)
        fresh.append(note_id)
    return fresh


def subscription_should_stop(
    new_count_on_page: int,
    pages_fetched: int,
    max_pages: int,
) -> tuple[bool, str]:
    """一页处理完后判定是否停止。

    追平优先于页上限：整页 0 新帖时无论翻了几页都该停（订阅已同步完成）。
    max_pages <= 0 视为 1（配置写坏也不允许无限翻页——刹车不能因为配置失效）。
    """

    if new_count_on_page <= 0:
        return True, STOP_CAUGHT_UP
    if pages_fetched >= max(int(max_pages), 1):
        return True, STOP_PAGE_CAP
    return False, ""
