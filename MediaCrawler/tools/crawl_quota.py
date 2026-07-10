# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/crawl_quota.py
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

"""微博/贴吧搜索配额的纯函数：按"新增入库条数"计而非页数。

被窗口/主题过滤或跳过已入库的帖子不再烧配额，与小红书"新增详情数"语义对齐；
页数保护上限防止贫瘠词无限翻页。
设计：主项目 docs/superpowers/specs/2026-07-10-keyword-quality-pipeline-design.md P1-5
"""

from __future__ import annotations


def should_fetch_next_page(
    stored_count: int,
    pages_fetched: int,
    max_notes: int,
    max_pages: int,
) -> bool:
    """新增入库条数未达配额 且 已抓页数未达保护上限 → 继续翻页。"""

    return int(stored_count) < int(max_notes) and int(pages_fetched) < int(max_pages)
