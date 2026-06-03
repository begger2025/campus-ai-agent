import pytest

import config
from media_platform.tieba.core import TieBaCrawler
from model.m_baidu_tieba import TiebaNote
from store import tieba as tieba_store


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
