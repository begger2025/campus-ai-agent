# -*- coding: utf-8 -*-
"""
Unit tests for the crawl-stage skip-if-exists helper added to the weibo/tieba DB
store implementations (注意点 4：微博/贴吧爬取阶段跳过已入库帖子).

设计见 docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 4。
参考实现：store/xhs/_store_impl.py::batch_get_existing_note_ids。

全程不连接真实数据库：database.db_session.get_session 被替换成返回 fake session 的
async context manager（stubbing 风格镜像 test_store_integrity_fallback.py），只验证：
  - 空输入 -> 空集合，且不发起任何 DB 查询。
  - WeiboNote.note_id 是 BigInteger：非数字 id 必须被防御性跳过，不能让 int() 抛出异常
    往上传播；若跳过后一个能查的 id 都不剩，直接短路返回空集合、不查库。
  - TiebaNote.note_id 是 String(644)：按字符串比较，输入去空白、去重。
  - 两平台返回的集合统一是 str（哪怕底层列是 BigInteger）。
  - store/weibo/__init__.py、store/tieba/__init__.py 的模块级包装函数在底层 store
    不支持该方法时（csv/json/excel 等非 DB 模式）优雅降级为空集合，不抛异常。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import store.tieba as tieba_store
import store.weibo as weibo_store
from store.tieba import TieBaStoreFactory
from store.tieba._store_impl import TieBaDbStoreImplement
from store.weibo import WeibostoreFactory
from store.weibo._store_impl import WeiboDbStoreImplement


def _scalars_result(values):
    """模拟 `await session.execute(stmt)` 的返回值：.scalars().all() 是同步方法链。"""
    scalars_mock = MagicMock(name="fake_scalars")
    scalars_mock.all.return_value = values
    result = MagicMock(name="fake_result")
    result.scalars.return_value = scalars_mock
    return result


def _fake_get_session_factory(session):
    """还原 database.db_session.get_session() 的形状：一个零参数、返回 async context
    manager 的 callable。用 MagicMock(side_effect=...) 包一层，方便断言"是否发起了查询"。"""

    @asynccontextmanager
    async def _fake_get_session():
        yield session

    return MagicMock(side_effect=_fake_get_session)


class TestWeiboBatchGetExistingNoteIds:
    """WeiboNote.note_id 是 BigInteger，入参需要 int 化，非数字 id 防御性跳过。"""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_set_without_db_call(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock()
        get_session_mock = _fake_get_session_factory(fake_session)
        monkeypatch.setattr("store.weibo._store_impl.get_session", get_session_mock)

        store = WeiboDbStoreImplement()
        result = await store.batch_get_existing_note_ids([])

        assert result == set()
        get_session_mock.assert_not_called()
        fake_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_non_numeric_ids_skipped_defensively_without_db_call(self, monkeypatch):
        """全部是非数字 id（BigInteger 列无法比较）：不能抛异常，且不应该发起查询。"""
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock()
        get_session_mock = _fake_get_session_factory(fake_session)
        monkeypatch.setattr("store.weibo._store_impl.get_session", get_session_mock)

        store = WeiboDbStoreImplement()
        result = await store.batch_get_existing_note_ids(["not-a-number", "abc123abc", "  "])

        assert result == set()
        get_session_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_ids_query_only_numeric_ones_and_normalize_result_to_str(self, monkeypatch):
        """混合输入：非数字 id 被过滤掉，只查数字 id；返回集合统一转 str。"""
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_scalars_result([123456789012345]))
        get_session_mock = _fake_get_session_factory(fake_session)
        monkeypatch.setattr("store.weibo._store_impl.get_session", get_session_mock)

        store = WeiboDbStoreImplement()
        result = await store.batch_get_existing_note_ids(["123456789012345", "not-numeric", ""])

        assert result == {"123456789012345"}
        assert all(isinstance(item, str) for item in result)
        fake_session.execute.assert_awaited_once()


class TestTiebaBatchGetExistingNoteIds:
    """TiebaNote.note_id 是 String(644)，直接按字符串比较，输入去空白去重。"""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_set_without_db_call(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock()
        get_session_mock = _fake_get_session_factory(fake_session)
        monkeypatch.setattr("store.tieba._store_impl.get_session", get_session_mock)

        store = TieBaDbStoreImplement()
        result = await store.batch_get_existing_note_ids([])

        assert result == set()
        get_session_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_ids_are_stripped_deduplicated_and_result_normalized_to_str(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_scalars_result(["note-1", "note-2"]))
        get_session_mock = _fake_get_session_factory(fake_session)
        monkeypatch.setattr("store.tieba._store_impl.get_session", get_session_mock)

        store = TieBaDbStoreImplement()
        result = await store.batch_get_existing_note_ids([" note-1 ", "note-1", "note-2", "  "])

        assert result == {"note-1", "note-2"}
        assert all(isinstance(item, str) for item in result)
        fake_session.execute.assert_awaited_once()


class TestModuleWrapperGracefulDegradation:
    """store/weibo/__init__.py、store/tieba/__init__.py 的模块级包装函数：
    底层 store 不支持 batch_get_existing_note_ids（csv/json/excel 等非 DB 模式）时
    必须优雅降级为空集合，不能抛异常——镜像 store/xhs/__init__.py 的既有写法。"""

    class _NoOpStore:
        """没有 batch_get_existing_note_ids 方法，模拟非 DB 的 store 实现。"""

    @pytest.mark.asyncio
    async def test_weibo_wrapper_degrades_to_empty_set_for_non_db_store(self, monkeypatch):
        monkeypatch.setattr(WeibostoreFactory, "create_store", lambda: self._NoOpStore())

        result = await weibo_store.batch_get_existing_note_ids(["123"])

        assert result == set()

    @pytest.mark.asyncio
    async def test_tieba_wrapper_degrades_to_empty_set_for_non_db_store(self, monkeypatch):
        monkeypatch.setattr(TieBaStoreFactory, "create_store", lambda: self._NoOpStore())

        result = await tieba_store.batch_get_existing_note_ids(["note-1"])

        assert result == set()
