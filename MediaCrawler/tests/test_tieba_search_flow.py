from typing import Dict, List

import pytest

import config
from media_platform.tieba.core import TieBaCrawler
from model.m_baidu_tieba import TiebaNote
from store import run_history as run_history_store
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


# ---------- search() 异常语义 ----------
#
# 审计发现（2026-07-17）：贴吧原本把**一切**页级异常吞掉后 break，search() 正常返回——
# 队列模式下瞬时网络错误也被标 done，不重试、数据静默少采；而微博同款错误会上抛标 failed。
# 贴吧 client 只抛裸 Exception 无类型可辨（对比 ks/zhihu 的 DataFetchError），无法区分
# 瞬时/致命——宁可失败可重试，不可静默少采：对齐微博语义，页级异常一律上抛。


@pytest.mark.asyncio
async def test_search_page_exception_propagates_and_still_writes_history(monkeypatch):
    rows: List[Dict] = []

    async def fake_save_history(row):
        rows.append(row)

    monkeypatch.setattr(run_history_store, "save_crawler_run_history", fake_save_history)
    monkeypatch.setattr(config, "KEYWORDS", "宿舍")
    monkeypatch.setattr(config, "START_PAGE", 1)
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 10)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_START", "", raising=False)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_END", "", raising=False)
    monkeypatch.setattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0, raising=False)

    class ExplodingClient:
        async def get_notes_by_keyword(self, **kwargs):
            raise RuntimeError("transient network error")

    crawler = TieBaCrawler()
    crawler.tieba_client = ExplodingClient()

    with pytest.raises(RuntimeError):
        await crawler.search()

    assert len(rows) == 1, "异常路径也必须落一行运行历史"
    assert rows[0]["platform"] == "tieba"
    assert rows[0]["stop_reason"] == "exception"


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
