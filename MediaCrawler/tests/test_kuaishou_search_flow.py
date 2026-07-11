# -*- coding: utf-8 -*-
"""快手搜索管线测试，仿 test_zhihu_search_flow.py。

_filter_and_store_page：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 入库计数；
page_resolved_ts 在一切跳过/过滤决策之外收集。
search()：游标 no_more 停止、配额按入库数、异常只中断当前关键词，均落 run_history。
词表用真实 config（中山大学相关词 / 考研机构负面词 / 求推荐救回词）。
"""

from typing import Dict, List

import pytest

import config
from media_platform.kuaishou.core import KuaishouCrawler
from media_platform.kuaishou.exception import DataFetchError
from store import kuaishou as kuaishou_store
from store import run_history as run_history_store
from tools.run_history import RunState

TS_MS = 1_781_193_600_000  # 2026-06-12 前后，仅需相对大小正确


def make_feed(video_id: str, caption: str, ts_ms: int = TS_MS) -> Dict:
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


def make_run_state() -> RunState:
    return RunState(platform="ks", source_keyword="中山大学 宿舍", started_at=0)


@pytest.fixture
def stored_ids(monkeypatch) -> List[str]:
    """默认桩：入库全部成功并记录 video_id；已存查询返回空集。"""
    saved: List[str] = []

    async def fake_update_kuaishou_video(video_item):
        saved.append(video_item["photo"]["id"])

    async def fake_batch_get_existing_note_ids(note_ids):
        return set()

    monkeypatch.setattr(kuaishou_store, "update_kuaishou_video", fake_update_kuaishou_video)
    monkeypatch.setattr(kuaishou_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    return saved


# ---------- _filter_and_store_page ----------

@pytest.mark.asyncio
async def test_topic_filter_keeps_relevant_and_drops_unrelated(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样"),
        make_feed("a2", "北京胡同游玩vlog"),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, None, None, False, run_state
    )

    assert kept_ids == ["a1"]
    assert run_state.items_stored == 1
    assert len(page_resolved_ts) == 2  # 被主题过滤的条目仍贡献发布时间


@pytest.mark.asyncio
async def test_marketing_noise_dropped_but_rescue_terms_keep(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("m1", "中山大学考研机构春季班火热报名"),
        make_feed("m2", "中山大学有没有靠谱的考研机构求推荐"),
    ]

    kept_ids, _ = await crawler._filter_and_store_page(feeds, None, None, False, run_state)

    assert kept_ids == ["m2"]
    assert run_state.items_stored == 1


@pytest.mark.asyncio
async def test_window_filter_drops_old_but_contributes_page_ts(stored_ids):
    crawler = KuaishouCrawler()
    run_state = make_run_state()
    window_lo = TS_MS
    old_ts = TS_MS - 10 * 24 * 3600 * 1000
    feeds = [
        make_feed("old1", "中山大学宿舍条件怎么样", ts_ms=old_ts),
        make_feed("new1", "中山大学食堂测评", ts_ms=TS_MS + 100),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, window_lo, None, True, run_state
    )

    assert kept_ids == ["new1"]
    assert run_state.items_stored == 1
    assert old_ts in page_resolved_ts  # 窗口过滤的条目仍贡献发布时间


@pytest.mark.asyncio
async def test_skip_existing_not_stored_but_contributes_page_ts(stored_ids, monkeypatch):
    async def fake_batch_get_existing_note_ids(note_ids):
        return {"a1"}

    monkeypatch.setattr(kuaishou_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    monkeypatch.setattr(config, "KS_SKIP_EXISTING_NOTES", True, raising=False)

    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样", ts_ms=TS_MS),
        make_feed("a2", "中山大学食堂测评", ts_ms=TS_MS + 100),
    ]

    kept_ids, page_resolved_ts = await crawler._filter_and_store_page(
        feeds, None, None, False, run_state
    )

    assert kept_ids == ["a2"]
    assert run_state.items_stored == 1
    assert TS_MS in page_resolved_ts


@pytest.mark.asyncio
async def test_store_failure_not_counted(stored_ids, monkeypatch):
    async def flaky_update(video_item):
        if video_item["photo"]["id"] == "a1":
            raise RuntimeError("db down")
        stored_ids.append(video_item["photo"]["id"])

    monkeypatch.setattr(kuaishou_store, "update_kuaishou_video", flaky_update)

    crawler = KuaishouCrawler()
    run_state = make_run_state()
    feeds = [
        make_feed("a1", "中山大学宿舍条件怎么样"),
        make_feed("a2", "中山大学食堂测评"),
    ]

    kept_ids, _ = await crawler._filter_and_store_page(feeds, None, None, False, run_state)

    assert kept_ids == ["a2"]
    assert run_state.items_stored == 1


# ---------- search() 停止语义 ----------

class FakeKsClient:
    """按预置页序列应答；页数用完后返回 no_more 空页。"""

    def __init__(self, pages: List[Dict]):
        self._pages = list(pages)
        self.calls: List[str] = []

    async def search_info_by_keyword(self, keyword: str, pcursor: str, search_session_id: str = ""):
        self.calls.append(pcursor)
        if self._pages:
            return self._pages.pop(0)
        return {"visionSearchPhoto": {"result": 1, "feeds": [], "pcursor": "no_more"}}


def make_page(feeds: List[Dict], pcursor: str) -> Dict:
    return {"visionSearchPhoto": {"result": 1, "feeds": feeds, "pcursor": pcursor, "searchSessionId": "sid-1"}}


@pytest.fixture
def search_env(monkeypatch, stored_ids):
    """search() 级公共桩：单关键词、无窗口、无 jitter、不抓评论、历史落行捕获。"""
    rows: List[Dict] = []

    async def fake_save_history(row):
        rows.append(row)

    monkeypatch.setattr(run_history_store, "save_crawler_run_history", fake_save_history)
    monkeypatch.setattr(config, "KEYWORDS", "宿舍")
    monkeypatch.setattr(config, "START_PAGE", 1)
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 20)
    monkeypatch.setattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_START", "", raising=False)
    monkeypatch.setattr(config, "CRAWL_PUBLISH_TIME_END", "", raising=False)
    monkeypatch.setattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0, raising=False)
    return rows


@pytest.mark.asyncio
async def test_search_stops_on_no_more_and_saves_history(search_env, stored_ids):
    rows = search_env
    crawler = KuaishouCrawler()
    crawler.ks_client = FakeKsClient(
        [make_page([make_feed("v1", "中山大学宿舍vlog")], pcursor="no_more")]
    )

    await crawler.search()

    assert stored_ids == ["v1"]
    assert len(rows) == 1
    assert rows[0]["platform"] == "ks"
    assert rows[0]["stop_reason"] == "empty_page"  # 服务端明示无更多结果
    assert rows[0]["pages_fetched"] == 1
    assert rows[0]["items_stored"] == 1


@pytest.mark.asyncio
async def test_search_quota_counted_by_stored(search_env, stored_ids):
    rows = search_env
    feeds = [make_feed(f"v{i}", f"中山大学宿舍vlog第{i}期") for i in range(20)]
    crawler = KuaishouCrawler()
    crawler.ks_client = FakeKsClient([make_page(feeds, pcursor="next-cursor")])

    await crawler.search()

    assert len(stored_ids) == 20
    assert rows[0]["stop_reason"] == "quota_reached"
    assert rows[0]["pages_fetched"] == 1  # 配额已满，不再翻第二页


@pytest.mark.asyncio
async def test_search_exception_only_breaks_current_keyword(search_env, stored_ids, monkeypatch):
    rows = search_env
    monkeypatch.setattr(config, "KEYWORDS", "宿舍,食堂")

    class ExplodingThenOkClient(FakeKsClient):
        async def search_info_by_keyword(self, keyword, pcursor, search_session_id=""):
            if "宿舍" in keyword:
                raise DataFetchError("boom")
            return await super().search_info_by_keyword(keyword, pcursor, search_session_id)

    crawler = KuaishouCrawler()
    crawler.ks_client = ExplodingThenOkClient(
        [make_page([make_feed("v1", "中山大学食堂测评")], pcursor="no_more")]
    )

    await crawler.search()

    assert stored_ids == ["v1"]
    assert len(rows) == 2
    assert rows[0]["stop_reason"] == "exception"
    assert rows[1]["stop_reason"] == "empty_page"
