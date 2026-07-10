# -*- coding: utf-8 -*-
"""
Unit tests for the in-process dedup guard used by file save modes
(csv/json/jsonl/excel). 设计见
docs/superpowers/specs/2026-07-10-dedup-hardening-design.md 注意点 2。

跨 run / 跨文件去重不在范围内（需要全文件扫描，代价不划算）：这里只验证
"同一进程运行期间，同一 item_type 下相同 id 的重复项只写一次"。
"""

from __future__ import annotations

import pytest

import config
from tools.async_file_writer import AsyncFileWriter, _DedupGuard


class TestDedupGuard:
    """直接测试 guard 本身：不涉及文件系统。"""

    def test_first_occurrence_writes(self):
        guard = _DedupGuard()
        assert guard.should_write("contents", {"note_id": "n1"}) is True

    def test_duplicate_is_skipped(self):
        guard = _DedupGuard()
        assert guard.should_write("contents", {"note_id": "n1"}) is True
        assert guard.should_write("contents", {"note_id": "n1"}) is False

    def test_different_item_type_same_id_both_write(self):
        guard = _DedupGuard()
        assert guard.should_write("contents", {"note_id": "same-id"}) is True
        assert guard.should_write("comments", {"comment_id": "same-id"}) is True

    def test_missing_id_key_always_writes(self):
        """没有 note_id/comment_id 的项（比如 creator）不去重，一直放行。"""
        guard = _DedupGuard()
        item = {"user_id": "u1"}
        assert guard.should_write("creators", item) is True
        assert guard.should_write("creators", item) is True

    def test_different_ids_both_write(self):
        guard = _DedupGuard()
        assert guard.should_write("contents", {"note_id": "n1"}) is True
        assert guard.should_write("contents", {"note_id": "n2"}) is True

    def test_comment_item_dedups_by_comment_id_not_shared_note_id(self):
        """评论项同时带 note_id（父帖子）和 comment_id：必须按 comment_id 去重，
        否则同一帖子下的第二条评论会因为 note_id 相同被误判成重复而漏写。"""
        guard = _DedupGuard()
        first_comment = {"comment_id": "c1", "note_id": "n1"}
        second_comment_same_note = {"comment_id": "c2", "note_id": "n1"}
        assert guard.should_write("comments", first_comment) is True
        assert guard.should_write("comments", second_comment_same_note) is True

    def test_duplicate_comment_id_is_skipped(self):
        guard = _DedupGuard()
        comment = {"comment_id": "c1", "note_id": "n1"}
        assert guard.should_write("comments", comment) is True
        assert guard.should_write("comments", dict(comment)) is False


@pytest.mark.asyncio
async def test_async_file_writer_csv_writes_duplicate_item_once(tmp_path, monkeypatch):
    """集成性测试：同一 AsyncFileWriter 实例对同一 item 写两次 CSV，只落一行数据。"""
    monkeypatch.setattr(config, "SAVE_DATA_PATH", str(tmp_path))
    writer = AsyncFileWriter(platform="test_dedup", crawler_type="search")
    item = {"note_id": "dup-1", "title": "t"}

    await writer.write_to_csv(item=dict(item), item_type="contents")
    await writer.write_to_csv(item=dict(item), item_type="contents")

    file_path = writer._get_file_path("csv", "contents")
    with open(file_path, "r", encoding="utf-8-sig") as f:
        lines = [line for line in f.readlines() if line.strip()]

    # 表头 + 1 行数据，而不是表头 + 2 行
    assert len(lines) == 2
