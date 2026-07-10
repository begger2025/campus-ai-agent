# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_publish_time_window.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import random
from datetime import datetime

import pytest

from tools.publish_time_window import (
    is_within_window,
    parse_tieba_publish_time_ms,
    parse_window,
    pick_zhihu_search_time_value,
    select_with_exploration,
)

DAY_MS = 24 * 3600 * 1000


def _ms(y, m, d, hh=0, mm=0, ss=0):
    return int(datetime(y, m, d, hh, mm, ss).timestamp() * 1000)


class TestParseWindow:
    def test_both_bounds(self):
        lo, hi = parse_window("2026-06-10", "2026-06-15")
        assert lo == _ms(2026, 6, 10)
        # 闭区间：END 含当天最后一毫秒
        assert hi == _ms(2026, 6, 16) - 1

    def test_empty_means_disabled(self):
        assert parse_window("", "") == (None, None)
        assert parse_window(None, None) == (None, None)

    def test_open_ended(self):
        lo, hi = parse_window("2026-06-10", "")
        assert lo == _ms(2026, 6, 10) and hi is None

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_window("2026/06/10", "")
        with pytest.raises(ValueError):
            parse_window("", "06-15")

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            parse_window("2026-06-15", "2026-06-10")


class TestIsWithinWindow:
    LO, HI = _ms(2026, 6, 10), _ms(2026, 6, 16) - 1

    def test_inside(self):
        assert is_within_window(_ms(2026, 6, 12), self.LO, self.HI)

    def test_boundaries_inclusive(self):
        assert is_within_window(self.LO, self.LO, self.HI)
        assert is_within_window(self.HI, self.LO, self.HI)

    def test_outside(self):
        assert not is_within_window(_ms(2026, 6, 9, 23, 59), self.LO, self.HI)
        assert not is_within_window(_ms(2026, 6, 16), self.LO, self.HI)

    def test_unknown_respects_keep_flag(self):
        assert is_within_window(None, self.LO, self.HI, keep_unknown=True)
        assert not is_within_window(None, self.LO, self.HI, keep_unknown=False)

    def test_no_window_keeps_everything(self):
        assert is_within_window(_ms(2000, 1, 1), None, None)


class TestParseTiebaPublishTime:
    def test_date_only_single_digit(self):
        assert parse_tieba_publish_time_ms("2026-6-12") == _ms(2026, 6, 12)

    def test_datetime_format(self):
        assert parse_tieba_publish_time_ms("2026-06-12 09:30") == _ms(2026, 6, 12, 9, 30)

    def test_relative_and_garbage_return_none(self):
        assert parse_tieba_publish_time_ms("3天前") is None
        assert parse_tieba_publish_time_ms("") is None
        assert parse_tieba_publish_time_ms(None) is None
        assert parse_tieba_publish_time_ms("2026-13-40") is None  # 非法日期


class TestPickZhihuSearchTimeValue:
    NOW = 1_800_000_000_000  # 固定 now，毫秒

    def _lo(self, days_ago: float) -> int:
        return int(self.NOW - days_ago * DAY_MS)

    def test_no_window_returns_default(self):
        assert pick_zhihu_search_time_value(None, self.NOW) == ""

    def test_buckets(self):
        assert pick_zhihu_search_time_value(self._lo(0.5), self.NOW) == "a_day"
        assert pick_zhihu_search_time_value(self._lo(1), self.NOW) == "a_day"  # 边界含
        assert pick_zhihu_search_time_value(self._lo(6.9), self.NOW) == "a_week"
        assert pick_zhihu_search_time_value(self._lo(7), self.NOW) == "a_week"
        assert pick_zhihu_search_time_value(self._lo(31), self.NOW) == "a_month"
        assert pick_zhihu_search_time_value(self._lo(92), self.NOW) == "three_months"
        assert pick_zhihu_search_time_value(self._lo(183), self.NOW) == "half_a_year"
        assert pick_zhihu_search_time_value(self._lo(366), self.NOW) == "a_year"

    def test_older_than_a_year_returns_default(self):
        assert pick_zhihu_search_time_value(self._lo(400), self.NOW) == ""

    def test_future_lo_clamps_to_smallest_bucket(self):
        assert pick_zhihu_search_time_value(self.NOW + DAY_MS, self.NOW) == "a_day"


class TestSelectWithExploration:
    ITEMS = ["n1", "n2", "n3", "n4", "n5"]  # 已按最新优先排序

    def test_epsilon_zero_takes_head(self):
        assert select_with_exploration(self.ITEMS, 3, 0.0, rng=random.Random(1)) == ["n1", "n2", "n3"]

    def test_epsilon_one_explores_tail(self):
        # ε=1 且候选>1 时每个名额都从较旧候选抽：首个最新项 n1 不会被选中
        picked = select_with_exploration(self.ITEMS, 2, 1.0, rng=random.Random(7))
        assert "n1" not in picked
        assert len(picked) == 2

    def test_preserves_original_order(self):
        picked = select_with_exploration(self.ITEMS, 3, 1.0, rng=random.Random(42))
        indexes = [self.ITEMS.index(item) for item in picked]
        assert indexes == sorted(indexes)

    def test_quota_covers_all(self):
        assert select_with_exploration(self.ITEMS, 5, 0.5, rng=random.Random(3)) == self.ITEMS
        assert select_with_exploration(self.ITEMS, 99, 0.5, rng=random.Random(3)) == self.ITEMS

    def test_empty_and_zero_quota(self):
        assert select_with_exploration([], 3, 0.5, rng=random.Random(3)) == []
        assert select_with_exploration(self.ITEMS, 0, 0.5, rng=random.Random(3)) == []

    def test_deterministic_with_seed(self):
        a = select_with_exploration(self.ITEMS, 3, 0.5, rng=random.Random(99))
        b = select_with_exploration(self.ITEMS, 3, 0.5, rng=random.Random(99))
        assert a == b
