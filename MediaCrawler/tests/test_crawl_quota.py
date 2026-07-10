# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_crawl_quota.py
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

from tools.crawl_quota import should_fetch_next_page


class TestShouldFetchNextPage:
    def test_continues_when_both_below_limits(self):
        assert should_fetch_next_page(stored_count=0, pages_fetched=0, max_notes=10, max_pages=10)
        assert should_fetch_next_page(stored_count=9, pages_fetched=9, max_notes=10, max_pages=10)

    def test_zero_quota_never_fetches(self):
        assert not should_fetch_next_page(stored_count=0, pages_fetched=0, max_notes=0, max_pages=10)

    def test_stops_exactly_at_quota(self):
        assert not should_fetch_next_page(stored_count=10, pages_fetched=3, max_notes=10, max_pages=10)

    def test_stops_beyond_quota(self):
        assert not should_fetch_next_page(stored_count=11, pages_fetched=3, max_notes=10, max_pages=10)

    def test_page_guard_triggers_first(self):
        # 入库数远未达标，但页数保护上限已到 → 停
        assert not should_fetch_next_page(stored_count=1, pages_fetched=10, max_notes=100, max_pages=10)

    def test_zero_max_pages_never_fetches(self):
        assert not should_fetch_next_page(stored_count=0, pages_fetched=0, max_notes=10, max_pages=0)

    def test_filtered_items_do_not_burn_quota(self):
        # 被过滤/跳过的帖子不计入 stored_count：抓了 3 页但只入库 2 条，仍可继续
        assert should_fetch_next_page(stored_count=2, pages_fetched=3, max_notes=10, max_pages=10)
