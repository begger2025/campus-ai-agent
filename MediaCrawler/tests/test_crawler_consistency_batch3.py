# -*- coding: utf-8 -*-
"""审计第3批：五平台一致性缺陷（xhs/ks 已做对、其余漏抄）。

- 空关键词：结尾逗号产生空串，只有 xhs 有 `if not keyword: continue`，
  其余四平台会对空串跑一整轮真实搜索。
- 逐条 store 隔离：weibo/tieba 单条 store 异常会中断整个关键词（知乎/快手/xhs 有隔离）。
  （CancelledError 假遥测的四平台补拦是纯 except-block 结构改动，由源码审阅保证，
   无法在不真跑事件循环取消的情况下单测，此处不覆盖。）
"""

import pytest

import config
from media_platform.tieba.core import TieBaCrawler
from model.m_baidu_tieba import TiebaNote
from store import tieba as tieba_store


def make_note(note_id: str) -> TiebaNote:
    return TiebaNote(
        note_id=note_id, title=f"t{note_id}", desc="d",
        note_url=f"https://tieba.baidu.com/p/{note_id}",
        user_nickname="u", user_link="x", tieba_name="f", tieba_link="y",
        publish_time="2026-5-23",
    )


@pytest.mark.asyncio
async def test_tieba_single_store_failure_does_not_abort_the_rest(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_GET_COMMENTS", False)
    saved = []

    async def flaky_update(note):
        if note.note_id == "bad":
            raise RuntimeError("db hiccup on one row")
        saved.append(note.note_id)

    monkeypatch.setattr(tieba_store, "update_tieba_note", flaky_update)
    crawler = TieBaCrawler()

    stored = await crawler._handle_search_notes([make_note("a"), make_note("bad"), make_note("c")])

    assert stored == 2, "坏的一条被跳过，其余两条照常入库"
    assert saved == ["a", "c"], "单条 store 失败不中断整批"


def test_empty_keyword_guard_present_in_all_platforms():
    """结尾逗号的空串必须被跳过——源码层面确认四平台都补上了守卫。"""
    import inspect

    from media_platform.weibo.core import WeiboCrawler
    from media_platform.zhihu.core import ZhihuCrawler
    from media_platform.kuaishou.core import KuaishouCrawler
    from media_platform.tieba.core import TieBaCrawler

    for crawler_cls in (WeiboCrawler, ZhihuCrawler, KuaishouCrawler, TieBaCrawler):
        src = inspect.getsource(crawler_cls.search)
        assert "if not keyword:" in src, f"{crawler_cls.__name__}.search 缺空关键词守卫"


def test_cancellederror_guard_present_in_all_platforms():
    """CancelledError 假遥测：四平台的 search 必须显式拦 asyncio.CancelledError。"""
    import inspect

    from media_platform.weibo.core import WeiboCrawler
    from media_platform.zhihu.core import ZhihuCrawler
    from media_platform.tieba.core import TieBaCrawler
    from media_platform.xhs.core import XiaoHongShuCrawler

    for crawler_cls in (WeiboCrawler, ZhihuCrawler, TieBaCrawler, XiaoHongShuCrawler):
        src = inspect.getsource(crawler_cls.search)
        assert "asyncio.CancelledError" in src, f"{crawler_cls.__name__}.search 缺 CancelledError 拦截"
