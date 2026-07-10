# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/run_history.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""crawler_run_history 通用爬取历史的共享异步写入器（三平台共用）。

仿 store.xhs.create_xhs_crawl_history 的机制：db 系存储写一行，
非 db 存储模式优雅 no-op（getattr/callable 降级）；写失败只打日志，绝不让爬取崩溃。
"""

from typing import Any, Dict, Optional

import config
from database.db_session import get_session
from database.models import CrawlerRunHistory
from tools import utils


class RunHistoryDbStoreImplement:
    """db / sqlite / postgres 共用的通用爬取历史写入实现。"""

    async def create_run_history(self, row: Dict[str, Any]) -> None:
        async with get_session() as session:
            history = CrawlerRunHistory(
                platform=str(row.get("platform") or ""),
                source_keyword=str(row.get("source_keyword") or ""),
                started_at=int(row.get("started_at") or 0),
                finished_at=int(row.get("finished_at") or 0),
                pages_fetched=int(row.get("pages_fetched") or 0),
                items_seen=int(row.get("items_seen") or 0),
                items_stored=int(row.get("items_stored") or 0),
                stop_reason=str(row.get("stop_reason") or ""),
            )
            session.add(history)


# 仅 db 系存储支持通用爬取历史；csv/json/jsonl/mongodb/excel 优雅降级为 no-op
_RUN_HISTORY_STORES = {
    "db": RunHistoryDbStoreImplement,
    "sqlite": RunHistoryDbStoreImplement,
    "postgres": RunHistoryDbStoreImplement,
}


def _create_store() -> Optional[RunHistoryDbStoreImplement]:
    store_class = _RUN_HISTORY_STORES.get(config.SAVE_DATA_OPTION)
    return store_class() if store_class else None


async def save_crawler_run_history(row: Dict[str, Any]) -> None:
    """写一行通用爬取历史；任何失败只打日志，不向调用方抛出。"""
    store = _create_store()
    creator = getattr(store, "create_run_history", None)
    if not callable(creator):
        utils.logger.info(
            f"[store.run_history.save_crawler_run_history] Current store backend does not support run history, "
            f"save option: {config.SAVE_DATA_OPTION}"
        )
        return

    try:
        await creator(row)
        utils.logger.info(
            f"[store.run_history.save_crawler_run_history] Run history saved, "
            f"platform={row.get('platform')}, keyword={row.get('source_keyword')}, "
            f"pages_fetched={row.get('pages_fetched')}, items_seen={row.get('items_seen')}, "
            f"items_stored={row.get('items_stored')}, stop_reason={row.get('stop_reason')}"
        )
    except Exception as ex:
        utils.logger.error(
            f"[store.run_history.save_crawler_run_history] Failed to save run history, "
            f"platform={row.get('platform')}, keyword={row.get('source_keyword')}, error: {ex}"
        )
