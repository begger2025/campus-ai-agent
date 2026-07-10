# -*- coding: utf-8 -*-
"""知乎搜索单页处理（_filter_and_store_page）的 mock 边界测试，仿 test_tieba_search_flow.py。

过滤顺序：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 入库计数；
page_resolved_ts 在一切跳过/过滤决策之外收集（早停只看整页发布时间）。
词表用真实 config（中山大学相关词 / 考研机构负面词 / 求推荐救回词）。
"""

from typing import List

import pytest

import config
from media_platform.zhihu.core import ZhihuCrawler
from model.m_zhihu import ZhihuContent
from store import zhihu as zhihu_store
from tools.run_history import RunState

TS_2026_06_12 = 1_781_193_600  # 秒级 epoch，仅需相对大小正确


def make_content(content_id: str, title: str, created_time: int = TS_2026_06_12) -> ZhihuContent:
    return ZhihuContent(
        content_id=content_id,
        content_type="answer",
        content_text=f"{title} 的正文内容",
        content_url=f"https://www.zhihu.com/question/1/answer/{content_id}",
        title=title,
        desc=f"{title} 的摘要",
        created_time=created_time,
    )


def make_run_state() -> RunState:
    return RunState(platform="zhihu", source_keyword="中山大学 宿舍", started_at=0)


@pytest.fixture
def stored_contents(monkeypatch) -> List[ZhihuContent]:
    """默认桩：入库全部成功并记录；已存查询返回空集。"""
    saved: List[ZhihuContent] = []

    async def fake_update_zhihu_content(content):
        saved.append(content)

    async def fake_batch_get_existing_note_ids(note_ids):
        return set()

    monkeypatch.setattr(zhihu_store, "update_zhihu_content", fake_update_zhihu_content)
    monkeypatch.setattr(zhihu_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    return saved


@pytest.mark.asyncio
async def test_topic_filter_keeps_relevant_and_drops_unrelated(stored_contents):
    crawler = ZhihuCrawler()
    run_state = make_run_state()
    contents = [
        make_content("a1", "中山大学宿舍条件怎么样"),
        make_content("a2", "北京的胡同游玩攻略"),
    ]

    stored, page_resolved_ts = await crawler._filter_and_store_page(
        contents, None, None, False, run_state
    )

    assert [c.content_id for c in stored] == ["a1"]
    assert run_state.items_stored == 1
    assert len(page_resolved_ts) == 2  # 被主题过滤的条目仍贡献发布时间


@pytest.mark.asyncio
async def test_marketing_noise_dropped_but_rescue_terms_keep(stored_contents):
    crawler = ZhihuCrawler()
    run_state = make_run_state()
    contents = [
        make_content("m1", "中山大学考研机构春季班火热报名"),
        make_content("m2", "中山大学有没有靠谱的考研机构求推荐"),
    ]

    stored, _ = await crawler._filter_and_store_page(contents, None, None, False, run_state)

    # 纯营销文案被过滤；带救回词（求推荐）的真实求助保留
    assert [c.content_id for c in stored] == ["m2"]
    assert run_state.items_stored == 1


@pytest.mark.asyncio
async def test_skip_existing_not_stored_but_contributes_page_ts(stored_contents, monkeypatch):
    async def fake_batch_get_existing_note_ids(note_ids):
        return {"a1"}

    monkeypatch.setattr(zhihu_store, "batch_get_existing_note_ids", fake_batch_get_existing_note_ids)
    monkeypatch.setattr(config, "ZHIHU_SKIP_EXISTING_NOTES", True)

    crawler = ZhihuCrawler()
    run_state = make_run_state()
    contents = [
        make_content("a1", "中山大学宿舍条件怎么样", created_time=TS_2026_06_12),
        make_content("a2", "中山大学食堂测评", created_time=TS_2026_06_12 + 100),
    ]

    stored, page_resolved_ts = await crawler._filter_and_store_page(
        contents, None, None, False, run_state
    )

    # 已入库条目不再入库、不烧配额，但它的发布时间仍参与整页早停判定
    assert [c.content_id for c in stored] == ["a2"]
    assert run_state.items_stored == 1
    assert TS_2026_06_12 * 1000 in page_resolved_ts


@pytest.mark.asyncio
async def test_store_failure_not_counted(stored_contents, monkeypatch):
    async def flaky_update_zhihu_content(content):
        if content.content_id == "a1":
            raise RuntimeError("db down")
        stored_contents.append(content)

    monkeypatch.setattr(zhihu_store, "update_zhihu_content", flaky_update_zhihu_content)

    crawler = ZhihuCrawler()
    run_state = make_run_state()
    contents = [
        make_content("a1", "中山大学宿舍条件怎么样"),
        make_content("a2", "中山大学食堂测评"),
    ]

    stored, _ = await crawler._filter_and_store_page(contents, None, None, False, run_state)

    assert [c.content_id for c in stored] == ["a2"]
    assert run_state.items_stored == 1


@pytest.mark.asyncio
async def test_window_filter_drops_old_but_contributes_page_ts(stored_contents):
    crawler = ZhihuCrawler()
    run_state = make_run_state()
    window_lo = TS_2026_06_12 * 1000  # 毫秒
    old_ts = TS_2026_06_12 - 10 * 24 * 3600
    contents = [
        make_content("old1", "中山大学宿舍条件怎么样", created_time=old_ts),
        make_content("new1", "中山大学食堂测评", created_time=TS_2026_06_12 + 100),
    ]

    stored, page_resolved_ts = await crawler._filter_and_store_page(
        contents, window_lo, None, True, run_state
    )

    assert [c.content_id for c in stored] == ["new1"]
    assert run_state.items_stored == 1
    assert old_ts * 1000 in page_resolved_ts  # 窗口过滤的条目仍贡献发布时间
