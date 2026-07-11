# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_cmd_arg.py
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

"""--fresh "新鲜优先"预设的 CLI 解析测试。

parse_cmd 会覆盖 config 全局状态，fixture 负责快照/恢复，避免污染其他测试。
"""

import pytest

import config
from cmd_arg.arg import parse_cmd


@pytest.fixture
def restore_config():
    """快照 config 所有大写配置项，测试后恢复（parse_cmd 直接改写全局 config）。"""
    snapshot = {key: getattr(config, key) for key in dir(config) if key.isupper()}
    yield
    for key, value in snapshot.items():
        setattr(config, key, value)


BASE_ARGS = ["--platform", "xhs", "--keywords", "中山大学 宿舍", "--lt", "qrcode"]


class TestFreshPreset:
    @pytest.mark.asyncio
    async def test_fresh_yes_applies_time_first_presets(self, restore_config):
        config.SORT_TYPE = "general"
        config.WEIBO_SEARCH_TYPE = "default"
        config.ZHIHU_SEARCH_SORT = ""
        await parse_cmd(BASE_ARGS + ["--fresh", "yes"])
        assert config.SORT_TYPE == "time_descending"
        assert config.WEIBO_SEARCH_TYPE == "real_time"
        assert config.ZHIHU_SEARCH_SORT == "created_time"

    @pytest.mark.asyncio
    async def test_fresh_defaults_to_no_and_keeps_config(self, restore_config):
        config.SORT_TYPE = "general"
        config.WEIBO_SEARCH_TYPE = "default"
        config.ZHIHU_SEARCH_SORT = ""
        await parse_cmd(list(BASE_ARGS))
        assert config.SORT_TYPE == "general"
        assert config.WEIBO_SEARCH_TYPE == "default"
        assert config.ZHIHU_SEARCH_SORT == ""

    @pytest.mark.asyncio
    async def test_fresh_no_keeps_config(self, restore_config):
        config.SORT_TYPE = "general"
        config.WEIBO_SEARCH_TYPE = "default"
        config.ZHIHU_SEARCH_SORT = ""
        await parse_cmd(BASE_ARGS + ["--fresh", "no"])
        assert config.SORT_TYPE == "general"
        assert config.WEIBO_SEARCH_TYPE == "default"
        assert config.ZHIHU_SEARCH_SORT == ""


class TestQueueFlags:
    @pytest.mark.asyncio
    async def test_from_queue_and_worker_parsed(self, restore_config):
        config.CRAWL_FROM_QUEUE = False
        config.CRAWL_WORKER_ID = ""
        await parse_cmd(BASE_ARGS + ["--from-queue", "yes", "--worker", "member-A"])
        assert config.CRAWL_FROM_QUEUE is True
        assert config.CRAWL_WORKER_ID == "member-A"

    @pytest.mark.asyncio
    async def test_from_queue_defaults_off(self, restore_config):
        config.CRAWL_FROM_QUEUE = True
        await parse_cmd(BASE_ARGS)
        assert config.CRAWL_FROM_QUEUE is False
