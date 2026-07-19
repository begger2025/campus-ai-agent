# -*- coding: utf-8 -*-
"""订阅式爬取的增量刹车语义（tools/subscription.py）。

两道刹车缺一不可：追平停止管"日常轮次别空转"，页上限管"首轮冷启动别吞存量"
（中山大学吧 345 万帖）。这里把判定语义逐条钉死。
"""

from tools.subscription import (
    STOP_CAUGHT_UP,
    STOP_PAGE_CAP,
    split_new_ids,
    subscription_should_stop,
)


class TestSplitNewIds:
    def test_filters_existing_ids(self):
        assert split_new_ids(["1", "2", "3"], {"2"}) == ["1", "3"]

    def test_keeps_order(self):
        assert split_new_ids(["9", "1", "5"], set()) == ["9", "1", "5"]

    def test_drops_empty_and_whitespace(self):
        assert split_new_ids(["", "  ", "7", None], set()) == ["7"]

    def test_dedupes_within_page(self):
        # 同页重复卡片（置顶帖会重复出现在列表页）只算一条
        assert split_new_ids(["1", "1", "2"], set()) == ["1", "2"]

    def test_all_existing_yields_empty(self):
        assert split_new_ids(["1", "2"], {"1", "2"}) == []


class TestSubscriptionShouldStop:
    def test_caught_up_stops_immediately(self):
        stop, reason = subscription_should_stop(0, pages_fetched=1, max_pages=10)
        assert stop and reason == STOP_CAUGHT_UP

    def test_caught_up_wins_over_page_cap(self):
        # 第 10 页恰好 0 新帖：归因必须是"追平"而不是"到上限"——两者的运维含义不同
        stop, reason = subscription_should_stop(0, pages_fetched=10, max_pages=10)
        assert stop and reason == STOP_CAUGHT_UP

    def test_page_cap_stops(self):
        stop, reason = subscription_should_stop(5, pages_fetched=10, max_pages=10)
        assert stop and reason == STOP_PAGE_CAP

    def test_continues_when_new_posts_and_under_cap(self):
        stop, reason = subscription_should_stop(3, pages_fetched=2, max_pages=10)
        assert not stop and reason == ""

    def test_broken_config_still_brakes(self):
        # 配置写坏（0/负数）也不允许无限翻页：刹车不能因为配置失效
        stop, reason = subscription_should_stop(5, pages_fetched=1, max_pages=0)
        assert stop and reason == STOP_PAGE_CAP
