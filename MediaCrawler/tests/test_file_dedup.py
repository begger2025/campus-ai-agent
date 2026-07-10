# -*- coding: utf-8 -*-
"""
Unit tests for the in-process dedup guard used by file save modes
(csv/json/jsonl/excel). 设计见
docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 2。

跨 run / 跨文件去重不在范围内（需要全文件扫描，代价不划算）：这里只验证
"同一进程运行期间，同一 (platform, crawler_type, item_type, id) 的重复项只写一次"。

关键回归点：store 工厂 create_store() 对每个 item 都新建一个 store 实例，因此
去重状态必须是跨实例共享的（类级），否则 csv/json/jsonl 每条都是全新空 guard、
去重完全失效。下面的 test_dedup_survives_across_create_store_instances /
test_two_writer_instances_share_dedup_state 就是针对这个缺陷的回归。
"""

from __future__ import annotations

import csv

import pytest

import config
from tools.async_file_writer import AsyncFileWriter, _DedupGuard


@pytest.fixture(autouse=True)
def _reset_dedup_state():
    """去重状态是进程级共享的类属性，用例之间必须还原，避免相互串味。"""
    _DedupGuard.reset()
    yield
    _DedupGuard.reset()


class TestDedupGuard:
    """直接测试 guard 本身：不涉及文件系统。"""

    def test_first_occurrence_writes(self):
        guard = _DedupGuard("xhs", "search")
        assert guard.should_write("contents", {"note_id": "n1"}) is True

    def test_duplicate_is_skipped(self):
        guard = _DedupGuard("xhs", "search")
        assert guard.should_write("contents", {"note_id": "n1"}) is True
        assert guard.should_write("contents", {"note_id": "n1"}) is False

    def test_different_item_type_same_id_both_write(self):
        guard = _DedupGuard("xhs", "search")
        assert guard.should_write("contents", {"note_id": "same-id"}) is True
        assert guard.should_write("comments", {"comment_id": "same-id"}) is True

    def test_missing_id_key_always_writes(self):
        """没有 note_id/comment_id 的项（比如 creator）不去重，一直放行。"""
        guard = _DedupGuard("xhs", "search")
        item = {"user_id": "u1"}
        assert guard.should_write("creators", item) is True
        assert guard.should_write("creators", item) is True

    def test_different_ids_both_write(self):
        guard = _DedupGuard("xhs", "search")
        assert guard.should_write("contents", {"note_id": "n1"}) is True
        assert guard.should_write("contents", {"note_id": "n2"}) is True

    def test_comment_item_dedups_by_comment_id_not_shared_note_id(self):
        """评论项同时带 note_id（父帖子）和 comment_id：必须按 comment_id 去重，
        否则同一帖子下的第二条评论会因为 note_id 相同被误判成重复而漏写。"""
        guard = _DedupGuard("xhs", "search")
        first_comment = {"comment_id": "c1", "note_id": "n1"}
        second_comment_same_note = {"comment_id": "c2", "note_id": "n1"}
        assert guard.should_write("comments", first_comment) is True
        assert guard.should_write("comments", second_comment_same_note) is True

    def test_duplicate_comment_id_is_skipped(self):
        guard = _DedupGuard("xhs", "search")
        comment = {"comment_id": "c1", "note_id": "n1"}
        assert guard.should_write("comments", comment) is True
        assert guard.should_write("comments", dict(comment)) is False

    # --- 回归：去重状态跨实例共享（否则 create_store() 每 item 新建 → 永远去不了重）---

    def test_two_guard_instances_same_scope_share_state(self):
        """两个独立 guard 实例、同一 (platform, crawler_type)：第二个应能看见第一个写过的 id。
        旧实现（实例级 _seen）下第二个实例的集合为空 → 会返回 True，本用例即失败。"""
        g1 = _DedupGuard("xhs", "search")
        g2 = _DedupGuard("xhs", "search")
        assert g1.should_write("contents", {"note_id": "shared"}) is True
        assert g2.should_write("contents", {"note_id": "shared"}) is False

    def test_scope_does_not_leak_across_platform(self):
        g_xhs = _DedupGuard("xhs", "search")
        g_weibo = _DedupGuard("weibo", "search")
        assert g_xhs.should_write("contents", {"note_id": "n1"}) is True
        # 不同平台同名 id 不应互相屏蔽
        assert g_weibo.should_write("contents", {"note_id": "n1"}) is True

    def test_scope_does_not_leak_across_crawler_type(self):
        g_search = _DedupGuard("xhs", "search")
        g_detail = _DedupGuard("xhs", "detail")
        assert g_search.should_write("contents", {"note_id": "n1"}) is True
        assert g_detail.should_write("contents", {"note_id": "n1"}) is True


def _read_csv_data_rows(file_path: str):
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [row for row in csv.reader(f) if row]
    # 第一行是表头
    return rows[1:]


@pytest.mark.asyncio
async def test_two_writer_instances_share_dedup_state(tmp_path, monkeypatch):
    """两个独立 AsyncFileWriter（模拟 create_store() 每 item 新建 writer）写同一 item，
    只应落一行。旧实现（实例级 _seen）下会落两行 → 本用例失败。"""
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    item = {"note_id": "dup-1", "title": "t"}

    writer1 = AsyncFileWriter(platform="test_dedup", crawler_type="search")
    writer2 = AsyncFileWriter(platform="test_dedup", crawler_type="search")
    await writer1.write_to_csv(item=dict(item), item_type="contents")
    await writer2.write_to_csv(item=dict(item), item_type="contents")

    data_rows = _read_csv_data_rows(writer1._get_file_path("csv", "contents"))
    assert len(data_rows) == 1


@pytest.mark.asyncio
async def test_dedup_survives_across_create_store_instances(tmp_path, monkeypatch):
    """通过真实入口 XhsStoreFactory.create_store() 走一遍：生产代码对每个 note 都
    create_store() 一次，两次写同一 note_id 只应落一行 CSV。

    这是针对"文件去重在生产里是 no-op"缺陷的端到端回归——旧实现下两次 create_store()
    拿到两个各自持空 _seen 的 writer，会写两行数据。"""
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "csv")

    from store.xhs import XhsStoreFactory

    store1 = XhsStoreFactory.create_store()
    store2 = XhsStoreFactory.create_store()
    # 前提复现：工厂每次都返回新实例（这正是缺陷的根因）
    assert store1 is not store2

    item = {"note_id": "note-xyz", "title": "hello"}
    await store1.store_content(dict(item))
    await store2.store_content(dict(item))

    data_rows = _read_csv_data_rows(store1.writer._get_file_path("csv", "contents"))
    assert len(data_rows) == 1
