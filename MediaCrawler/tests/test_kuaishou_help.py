# -*- coding: utf-8 -*-
"""快手翻页游标决策纯函数测试。

上游原实现把页码当游标传且丢弃服务端真实 pcursor；改造后优先服务端游标，
"no_more" → None（停止翻页），缺失回退页码字符串。
"""

from media_platform.kuaishou.help import resolve_next_pcursor


def test_prefers_server_pcursor():
    assert resolve_next_pcursor("opaque-cursor-xyz", 3) == "opaque-cursor-xyz"


def test_no_more_returns_none():
    assert resolve_next_pcursor("no_more", 3) is None


def test_missing_falls_back_to_page_number():
    assert resolve_next_pcursor(None, 4) == "4"
    assert resolve_next_pcursor("", 4) == "4"
    assert resolve_next_pcursor("   ", 4) == "4"
