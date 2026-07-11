# -*- coding: utf-8 -*-
"""队列驱动循环测试：认领顺序、单任务失败不中断、结果回填、排空退出。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import config
from store import crawl_queue
from tools import crawl_queue_runner


class FakeCrawler:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.searched = []

    async def search(self):
        kw = config.KEYWORDS
        self.searched.append(kw)
        if kw in self.fail_on:
            raise RuntimeError("boom")


@pytest.fixture
def queue_env(monkeypatch):
    monkeypatch.setattr(config, "PLATFORM", "ks")
    monkeypatch.setattr(config, "CRAWL_WORKER_ID", "worker-A", raising=False)
    completed = []

    async def fake_complete(task_id, worker_id, status, items_stored, stop_reason):
        completed.append((task_id, status, items_stored, stop_reason))

    async def fake_max_id(platform):
        return 100

    async def fake_delta(platform, before_id, source_keyword):
        return 5, "completed"

    monkeypatch.setattr(crawl_queue, "complete_task", fake_complete)
    monkeypatch.setattr(crawl_queue, "max_run_history_id", fake_max_id)
    monkeypatch.setattr(crawl_queue, "run_history_delta", fake_delta)
    return completed


@pytest.mark.asyncio
async def test_loops_claimed_keywords_until_drained(queue_env, monkeypatch):
    completed = queue_env
    tasks = [{"id": 1, "keyword": "宿舍"}, {"id": 2, "keyword": "食堂"}, None]
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(side_effect=tasks))

    crawler = FakeCrawler()
    await crawl_queue_runner.run_keyword_queue(crawler)

    assert crawler.searched == ["宿舍", "食堂"]
    assert completed == [(1, "done", 5, "completed"), (2, "done", 5, "completed")]


@pytest.mark.asyncio
async def test_failed_task_marked_and_loop_continues(queue_env, monkeypatch):
    completed = queue_env
    tasks = [{"id": 1, "keyword": "宿舍"}, {"id": 2, "keyword": "食堂"}, None]
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(side_effect=tasks))

    crawler = FakeCrawler(fail_on={"宿舍"})
    await crawl_queue_runner.run_keyword_queue(crawler)

    # 宿舍 search 抛异常 → 标 failed；循环继续到食堂
    assert crawler.searched == ["宿舍", "食堂"]
    assert completed[0] == (1, "failed", 0, "exception")
    assert completed[1] == (2, "done", 5, "completed")


@pytest.mark.asyncio
async def test_empty_queue_no_search(queue_env, monkeypatch):
    completed = queue_env
    monkeypatch.setattr(crawl_queue, "claim_task", AsyncMock(return_value=None))

    crawler = FakeCrawler()
    await crawl_queue_runner.run_keyword_queue(crawler)

    assert crawler.searched == []
    assert completed == []
