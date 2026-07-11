# -*- coding: utf-8 -*-
"""队列驱动运行：登录后循环认领一个关键词、调既有 search()、回填结果、标记完成。"""

import socket

import config
from store import crawl_queue
from tools import utils
from tools.topic_scope import compose_topic_keyword


async def run_keyword_queue(crawler) -> None:
    """循环：认领 → 设单关键词 → crawler.search() → 回填 → done/failed，直到队列排空。

    单任务 search 抛异常 → 标 failed 并继续下一个（不让一个坏关键词终止整台机器）。
    """
    worker = str(getattr(config, "CRAWL_WORKER_ID", "") or socket.gethostname())
    platform = config.PLATFORM
    utils.logger.info(f"[run_keyword_queue] start worker={worker} platform={platform}")

    while True:
        task = await crawl_queue.claim_task(platform, worker)
        if task is None:
            utils.logger.info("[run_keyword_queue] queue drained, exit")
            break
        before_id = await crawl_queue.max_run_history_id(platform)
        config.KEYWORDS = task["keyword"]
        # 与 search() 内部一致的主题限定组合（纯函数、同 config 结果一致）——
        # 结果回填按 source_keyword 精确定位本任务的 run_history 行
        composed_keyword = compose_topic_keyword(
            task["keyword"],
            getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
            getattr(config, "TOPIC_RELEVANCE_TERMS", []),
        )
        try:
            await crawler.search()
            stored, reason = await crawl_queue.run_history_delta(platform, before_id, composed_keyword)
            await crawl_queue.complete_task(task["id"], worker, "done", stored, reason)
            utils.logger.info(
                f"[run_keyword_queue] done id={task['id']} keyword={task['keyword']} stored={stored}"
            )
        except Exception as ex:  # noqa: BLE001 —— 单任务失败隔离，不中断整台机器采集
            await crawl_queue.complete_task(task["id"], worker, "failed", 0, "exception")
            utils.logger.error(
                f"[run_keyword_queue] failed id={task['id']} keyword={task['keyword']} error={ex}"
            )
