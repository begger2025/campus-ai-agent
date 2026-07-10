# -*- coding: utf-8 -*-
"""知乎 store 防重复对齐测试：batch_get_existing_note_ids 的优雅降级。

非 db 系存储（csv/json/...）不支持已存查询，模块级包装必须返回空集而非抛错；
空入参同样直接返回空集，不触碰任何存储后端。
"""

import pytest

import config
from store import zhihu as zhihu_store


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
