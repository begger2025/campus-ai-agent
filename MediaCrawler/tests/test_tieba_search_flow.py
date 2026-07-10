import pytest

import config
from media_platform.tieba.core import TieBaCrawler
from model.m_baidu_tieba import TiebaNote
from store import tieba as tieba_store


def make_note(note_id: str) -> TiebaNote:
    return TiebaNote(
        note_id=note_id,
        title=f"title {note_id}",
        desc=f"desc {note_id}",
        note_url=f"https://tieba.baidu.com/p/{note_id}",
        user_nickname="sample user",
        user_link="https://tieba.baidu.com/home/main?id=abc",
        tieba_name="sample forum",
        tieba_link="https://tieba.baidu.com/f?kw=sample",
        publish_time="2026-5-23",
    )


@pytest.mark.asyncio
async def test_handle_search_notes_saves_cards_without_detail_when_comments_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    saved_notes = []

    async def fake_update_tieba_note(note):
        saved_notes.append(note)

    async def fail_get_specified_notes(*args, **kwargs):
        raise AssertionError("detail pages should not be fetched when comments are disabled")

    crawler = TieBaCrawler()
    monkeypatch.setattr(tieba_store, "update_tieba_note", fake_update_tieba_note)
    monkeypatch.setattr(crawler, "get_specified_notes", fail_get_specified_notes)

    note = TiebaNote(
        note_id="10737689970",
        title="sample title",
        desc="sample desc",
        note_url="https://tieba.baidu.com/p/10737689970",
        user_nickname="sample user",
        user_link="https://tieba.baidu.com/home/main?id=abc",
        tieba_name="sample forum",
        tieba_link="https://tieba.baidu.com/f?kw=sample",
        publish_time="2026-5-23",
    )

    await crawler._handle_search_notes([note])

    assert saved_notes == [note]


@pytest.mark.asyncio
async def test_handle_search_notes_returns_stored_count_when_comments_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    saved_notes = []

    async def fake_update_tieba_note(note):
        saved_notes.append(note)

    crawler = TieBaCrawler()
    monkeypatch.setattr(tieba_store, "update_tieba_note", fake_update_tieba_note)

    stored_count = await crawler._handle_search_notes([make_note("1"), make_note("2")])

    # 非评论路径：全部直接入库，返回值 = 实际 update_tieba_note 条数
    assert stored_count == 2
    assert len(saved_notes) == 2


@pytest.mark.asyncio
async def test_handle_search_notes_counts_only_successful_details_when_comments_enabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", True)
    saved_notes = []

    async def fake_update_tieba_note(note):
        saved_notes.append(note)

    crawler = TieBaCrawler()
    monkeypatch.setattr(tieba_store, "update_tieba_note", fake_update_tieba_note)

    # 详情抓取一成一败："1" 成功、"2" 失败返回 None（None 不会 update_tieba_note）
    async def fake_get_note_detail_async_task(note_id, semaphore):
        if note_id == "1":
            return make_note("1")
        return None

    async def fake_batch_get_note_comments(note_detail_list):
        return None

    monkeypatch.setattr(crawler, "get_note_detail_async_task", fake_get_note_detail_async_task)
    monkeypatch.setattr(crawler, "batch_get_note_comments", fake_batch_get_note_comments)

    stored_count = await crawler._handle_search_notes([make_note("1"), make_note("2")])

    # 评论路径：只有详情抓取成功的帖子才入库，失败的不虚计（贫瘠词判定依赖该数）
    assert stored_count == 1
    assert [note.note_id for note in saved_notes] == ["1"]
