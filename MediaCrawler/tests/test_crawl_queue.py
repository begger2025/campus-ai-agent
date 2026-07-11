# -*- coding: utf-8 -*-
"""队列认领模块 mock 测试：乐观条件更新竞态、租约回收、重试耗尽、结果回填、降级。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from store import crawl_queue


def _fake_get_session_factory(session):
    @asynccontextmanager
    async def _fake_get_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
    return _fake_get_session


def _result(*, first=None, scalar=None, all_rows=None, rowcount=0):
    r = MagicMock(name="result")
    r.first.return_value = first
    r.scalar.return_value = scalar
    r.all.return_value = all_rows or []
    r.rowcount = rowcount
    return r


@pytest.fixture(autouse=True)
def _db_mode(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "db")
    monkeypatch.setattr(config, "CRAWL_QUEUE_LEASE_SEC", 1800, raising=False)
    monkeypatch.setattr(config, "CRAWL_QUEUE_CLAIM_RETRY", 5, raising=False)


@pytest.mark.asyncio
async def test_claim_success_first_candidate(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    # execute 序列：回收租约(update) → 选候选(select) → 条件认领(update rowcount=1)
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=(7, "宿舍")),                # candidate
        _result(rowcount=1),                       # claim success
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    task = await crawl_queue.claim_task("ks", "worker-A")

    assert task == {"id": 7, "keyword": "宿舍"}


@pytest.mark.asyncio
async def test_claim_retries_when_first_candidate_taken(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=(7, "宿舍")),                # candidate 1
        _result(rowcount=0),                       # claim 1 lost (someone else)
        _result(first=(8, "食堂")),                # candidate 2
        _result(rowcount=1),                       # claim 2 success
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    task = await crawl_queue.claim_task("ks", "worker-A")

    assert task == {"id": 8, "keyword": "食堂"}


@pytest.mark.asyncio
async def test_claim_returns_none_when_queue_empty(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[
        _result(rowcount=0),                       # reclaim
        _result(first=None),                       # no candidate
    ])
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    assert await crawl_queue.claim_task("ks", "worker-A") is None


@pytest.mark.asyncio
async def test_claim_degrades_for_non_db_backend(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "json")
    # 不应触碰 get_session
    monkeypatch.setattr("store.crawl_queue.get_session",
                        _fake_get_session_factory(MagicMock(execute=AsyncMock(side_effect=AssertionError))))
    assert await crawl_queue.claim_task("ks", "worker-A") is None


@pytest.mark.asyncio
async def test_complete_task_updates_row(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=_result(rowcount=1))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    await crawl_queue.complete_task(7, "worker-A", "done", 12, "quota_reached")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_task_rejected_when_reclaimed(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=_result(rowcount=0))  # 已被别的 worker 认领
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))
    warn = MagicMock()
    monkeypatch.setattr("store.crawl_queue.utils.logger.warning", warn)

    await crawl_queue.complete_task(7, "worker-A", "done", 12, "quota_reached")  # 不应抛异常

    warn.assert_called_once()


@pytest.mark.asyncio
async def test_run_history_delta_sums_new_rows(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_result(all_rows=[(5, "completed"), (7, "quota_reached")]))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    total, reason = await crawl_queue.run_history_delta("ks", 10, "中山大学 宿舍")

    assert total == 12
    assert reason == "quota_reached"  # 取新增行里最后一行的 stop_reason


@pytest.mark.asyncio
async def test_run_history_delta_no_new_rows_returns_skipped(monkeypatch):
    session = MagicMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=_result(all_rows=[]))
    monkeypatch.setattr("store.crawl_queue.get_session", _fake_get_session_factory(session))

    total, reason = await crawl_queue.run_history_delta("ks", 10, "中山大学 宿舍")

    assert total == 0
    assert reason == "skipped"
