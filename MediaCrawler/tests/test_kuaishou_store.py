# -*- coding: utf-8 -*-
"""快手 store 模块级行为测试：commentCount 持久化透传 + 批量已存查询。

不连真实数据库：store 工厂/get_session 均打桩。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import config
from store import kuaishou as kuaishou_store
from store.kuaishou._store_impl import KuaishouDbStoreImplement
from var import source_keyword_var


def make_feed(video_id: str, caption: str, ts_ms: int = 1_781_193_600_000) -> dict:
    return {
        "type": 1,
        "author": {"id": "u1", "name": "某同学", "headerUrl": ""},
        "photo": {
            "id": video_id,
            "caption": caption,
            "originCaption": caption,
            "timestamp": ts_ms,
            "realLikeCount": 10,
            "viewCount": 100,
            "commentCount": 3,
            "coverUrl": "",
            "photoUrl": "",
        },
    }


@pytest.mark.asyncio
async def test_update_kuaishou_video_persists_comment_count(monkeypatch):
    """GraphQL 返回的 commentCount 现状被丢弃；改造后应随 content_item 入库。"""
    captured: dict = {}

    class FakeStore:
        async def store_content(self, content_item):
            captured.update(content_item)

    monkeypatch.setattr(
        kuaishou_store.KuaishouStoreFactory, "create_store", staticmethod(lambda: FakeStore())
    )
    source_keyword_var.set("中山大学 宿舍")

    await kuaishou_store.update_kuaishou_video(make_feed("3xabc", "中山大学宿舍vlog"))

    assert captured["video_id"] == "3xabc"
    assert captured["comment_count"] == "3"


def _fake_get_session_factory(session):
    @asynccontextmanager
    async def _fake_get_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    return _fake_get_session


def _ids_result(ids):
    result = MagicMock(name="fake_result")
    result.scalars.return_value.all.return_value = ids
    return result


class TestKuaishouBatchGetExistingNoteIds:
    @pytest.mark.asyncio
    async def test_returns_existing_ids(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock(return_value=_ids_result(["3xa", "3xb"]))
        fake_session.rollback = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        store = KuaishouDbStoreImplement()

        existing = await store.batch_get_existing_note_ids(["3xa", "3xb", "3xc", " ", ""])

        assert existing == {"3xa", "3xb"}

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits(self, monkeypatch):
        fake_session = MagicMock(name="fake_session")
        fake_session.execute = AsyncMock()
        monkeypatch.setattr(
            "store.kuaishou._store_impl.get_session", _fake_get_session_factory(fake_session)
        )
        store = KuaishouDbStoreImplement()

        assert await store.batch_get_existing_note_ids([]) == set()
        assert await store.batch_get_existing_note_ids(["", "  "]) == set()
        fake_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_module_wrapper_degrades_when_backend_unsupported(self, monkeypatch):
        """非 db 系后端没有该方法：模块包装优雅降级返回空集，不抛异常。"""
        monkeypatch.setattr(
            kuaishou_store.KuaishouStoreFactory, "create_store", staticmethod(lambda: object())
        )

        assert await kuaishou_store.batch_get_existing_note_ids(["3xa"]) == set()
