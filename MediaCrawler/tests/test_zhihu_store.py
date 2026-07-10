# -*- coding: utf-8 -*-
"""知乎 store 防重复对齐测试：batch_get_existing_note_ids 的优雅降级与冲突自愈语义。

非 db 系存储（csv/json/...）不支持已存查询，模块级包装必须返回空集而非抛错；
空入参同样直接返回空集，不触碰任何存储后端。
IntegrityError 自愈（insert 竞态失败转 update）不得覆盖胜出方的首次入库时间 add_ts。
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.exc import IntegrityError

import config
import store.zhihu._store_impl as zhihu_store_impl
from store import zhihu as zhihu_store
from store.zhihu._store_impl import ZhihuDbStoreImplement


@pytest.mark.asyncio
async def test_batch_get_existing_note_ids_degrades_to_empty_for_non_db(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "csv")
    result = await zhihu_store.batch_get_existing_note_ids(["a", "b"])
    assert result == set()


@pytest.mark.asyncio
async def test_batch_get_existing_note_ids_empty_input(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "db")
    result = await zhihu_store.batch_get_existing_note_ids([])
    assert result == set()


@pytest.mark.asyncio
async def test_batch_get_existing_note_ids_blank_ids_treated_as_empty(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "db")
    result = await zhihu_store.batch_get_existing_note_ids(["", "   "])
    assert result == set()


# ---------------------------------------------------------------------------
# IntegrityError 自愈路径：并发竞态下失败方转 update 时不得覆盖胜出方的 add_ts
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeConflictSession:
    """首次查询判"不存在"、flush 抛 IntegrityError、rollback 后重查返回既有行。"""

    def __init__(self, existing_after_conflict):
        self.existing_after_conflict = existing_after_conflict
        self.execute_calls = 0
        self.added = []
        self.rolled_back = False
        self.committed = False

    async def execute(self, stmt):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _FakeResult(None)
        return _FakeResult(self.existing_after_conflict)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    async def rollback(self):
        self.rolled_back = True

    async def commit(self):
        self.committed = True


class _ExistingContentRow:
    """胜出方已入库的行：add_ts 是首次入库时间，自愈更新必须保留。"""

    def __init__(self):
        self.content_id = "c1"
        self.title = "旧标题"
        self.add_ts = 111
        self.last_modify_ts = 111


class _ExistingCommentRow:
    def __init__(self):
        self.comment_id = "m1"
        self.content = "旧评论"
        self.add_ts = 222
        self.last_modify_ts = 222


def _patch_session(monkeypatch, fake_session):
    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    monkeypatch.setattr(zhihu_store_impl, "get_session", fake_get_session)


@pytest.mark.asyncio
async def test_store_content_integrity_heal_preserves_add_ts(monkeypatch):
    existing = _ExistingContentRow()
    session = _FakeConflictSession(existing)
    _patch_session(monkeypatch, session)

    await ZhihuDbStoreImplement().store_content(
        {"content_id": "c1", "title": "新标题", "last_modify_ts": 999}
    )

    assert session.rolled_back  # 确实走了 IntegrityError 自愈路径
    assert existing.title == "新标题"  # 其他字段正常转 update
    assert existing.add_ts == 111  # 首次入库时间不被竞态失败方覆盖


@pytest.mark.asyncio
async def test_store_comment_integrity_heal_preserves_add_ts(monkeypatch):
    existing = _ExistingCommentRow()
    session = _FakeConflictSession(existing)
    _patch_session(monkeypatch, session)

    await ZhihuDbStoreImplement().store_comment(
        {"comment_id": "m1", "content": "新评论", "last_modify_ts": 999}
    )

    assert session.rolled_back
    assert existing.content == "新评论"
    assert existing.add_ts == 222
