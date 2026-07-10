# -*- coding: utf-8 -*-
"""
Unit tests for the IntegrityError self-healing fallback added to the DB store
implementations (xhs / weibo / tieba).

设计见 docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 1（store 加固）。

全程不连接真实数据库：database.db_session.get_session 被替换成返回 fake session 的
async context manager，只验证"唯一键冲突（IntegrityError）不能让爬取崩溃"：
  - xhs：有独立的 add_content/update_content helper，验证冲突后转成 update。
  - weibo/tieba：insert/update 共用一条内联路径、无独立 helper，验证冲突后
    记录告警并跳过该条，而不是让异常向上传播中断整场爬取。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from store.tieba._store_impl import TieBaDbStoreImplement
from store.weibo._store_impl import WeiboDbStoreImplement
from store.xhs._store_impl import XhsDbStoreImplement


def _bare_fake_session() -> MagicMock:
    """xhs 测试用：add_content/update_content 本身被直接打桩，session 只需要
    rollback 是可 await 的，不必模拟 get_session() 的 commit/rollback 语义。"""
    session = MagicMock(name="fake_session")
    session.rollback = AsyncMock()
    return session


def _select_result(scalar_value=None) -> MagicMock:
    """模拟 `await session.execute(stmt)` 的返回值：.scalar_one_or_none() 是同步方法。"""
    result = MagicMock(name="fake_result")
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _fake_get_session_factory(session):
    """还原 database.db_session.get_session() 的真实形状：
    正常退出不用管（weibo/tieba 自己会显式 commit），
    async with 块内抛异常时 rollback 后重新抛出——这样 weibo/tieba 显式的
    `await session.commit()` 抛出 IntegrityError 时行为与真实 get_session() 一致。
    """

    @asynccontextmanager
    async def _fake_get_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    return _fake_get_session


class TestXhsIntegrityFallback:
    """xhs：try add_content -> except IntegrityError -> rollback -> update_content。"""

    @pytest.mark.asyncio
    async def test_store_content_falls_back_to_update_on_integrity_error(self, monkeypatch):
        store = XhsDbStoreImplement()
        fake_session = _bare_fake_session()
        monkeypatch.setattr(
            "store.xhs._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        monkeypatch.setattr(store, "content_is_exist", AsyncMock(return_value=False))
        add_content_mock = AsyncMock(side_effect=IntegrityError("dup", None, None))
        monkeypatch.setattr(store, "add_content", add_content_mock)
        update_content_mock = AsyncMock()
        monkeypatch.setattr(store, "update_content", update_content_mock)

        # 关键断言：不应该有任何异常从 store_content 逃逸出来
        await store.store_content({"note_id": "note-1"})

        add_content_mock.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        update_content_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_comment_falls_back_to_update_on_integrity_error(self, monkeypatch):
        store = XhsDbStoreImplement()
        fake_session = _bare_fake_session()
        monkeypatch.setattr(
            "store.xhs._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        monkeypatch.setattr(store, "comment_is_exist", AsyncMock(return_value=False))
        add_comment_mock = AsyncMock(side_effect=IntegrityError("dup", None, None))
        monkeypatch.setattr(store, "add_comment", add_comment_mock)
        update_comment_mock = AsyncMock()
        monkeypatch.setattr(store, "update_comment", update_comment_mock)

        await store.store_comment({"comment_id": "comment-1", "note_id": "note-1"})

        add_comment_mock.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        update_comment_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_content_normal_insert_does_not_touch_update(self, monkeypatch):
        """反向对照：没有冲突时走正常 insert 分支，update_content 不应被调用。"""
        store = XhsDbStoreImplement()
        fake_session = _bare_fake_session()
        monkeypatch.setattr(
            "store.xhs._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        monkeypatch.setattr(store, "content_is_exist", AsyncMock(return_value=False))
        add_content_mock = AsyncMock()
        monkeypatch.setattr(store, "add_content", add_content_mock)
        update_content_mock = AsyncMock()
        monkeypatch.setattr(store, "update_content", update_content_mock)

        await store.store_content({"note_id": "note-1"})

        add_content_mock.assert_awaited_once()
        update_content_mock.assert_not_awaited()
        fake_session.rollback.assert_not_awaited()


class TestWeiboIntegrityFallback:
    """weibo：insert/update 共用一条内联路径，无独立 add_/update_ helper。
    验证并发冲突时不崩溃：记录告警并跳过该条（详见任务报告里的取舍说明）。"""

    @pytest.mark.asyncio
    async def test_store_content_integrity_error_is_swallowed_and_logged(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_select_result(None))
        fake_session.add = MagicMock()
        fake_session.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()

        monkeypatch.setattr(
            "store.weibo._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        warn_mock = MagicMock()
        monkeypatch.setattr("store.weibo._store_impl.utils.logger.warning", warn_mock)

        store = WeiboDbStoreImplement()
        # 关键断言：不应该有任何异常从 store_content 逃逸出来
        await store.store_content({"note_id": "123456"})

        fake_session.commit.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        warn_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_comment_integrity_error_is_swallowed_and_logged(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_select_result(None))
        fake_session.add = MagicMock()
        fake_session.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()

        monkeypatch.setattr(
            "store.weibo._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        warn_mock = MagicMock()
        monkeypatch.setattr("store.weibo._store_impl.utils.logger.warning", warn_mock)

        store = WeiboDbStoreImplement()
        await store.store_comment({"comment_id": "654321", "note_id": "123456"})

        fake_session.commit.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        warn_mock.assert_called_once()


class TestTiebaIntegrityFallback:
    """tieba：结构与 weibo 相同（无独立 helper），同样验证跳过并告警。"""

    @pytest.mark.asyncio
    async def test_store_content_integrity_error_is_swallowed_and_logged(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_select_result(None))
        fake_session.add = MagicMock()
        fake_session.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()

        monkeypatch.setattr(
            "store.tieba._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        warn_mock = MagicMock()
        monkeypatch.setattr("store.tieba._store_impl.utils.logger.warning", warn_mock)

        store = TieBaDbStoreImplement()
        await store.store_content({"note_id": "note-1"})

        fake_session.commit.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        warn_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_comment_integrity_error_is_swallowed_and_logged(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_select_result(None))
        fake_session.add = MagicMock()
        fake_session.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
        fake_session.rollback = AsyncMock()

        monkeypatch.setattr(
            "store.tieba._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        warn_mock = MagicMock()
        monkeypatch.setattr("store.tieba._store_impl.utils.logger.warning", warn_mock)

        store = TieBaDbStoreImplement()
        await store.store_comment({"comment_id": "comment-1", "note_id": "note-1"})

        fake_session.commit.assert_awaited_once()
        fake_session.rollback.assert_awaited_once()
        warn_mock.assert_called_once()
