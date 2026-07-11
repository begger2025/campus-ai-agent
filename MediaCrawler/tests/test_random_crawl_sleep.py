# -*- coding: utf-8 -*-
"""抖动 helper 测试：区间内取值、min>max 回退、非法值回退。"""

from unittest.mock import AsyncMock

import pytest

import config
from tools import utils


@pytest.mark.asyncio
async def test_sleeps_within_range(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", 8, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))
    monkeypatch.setattr(utils.random, "uniform", lambda a, b: (a + b) / 2)

    await utils.random_crawl_sleep()

    assert slept == [13.0]  # (8+18)/2


@pytest.mark.asyncio
async def test_min_gt_max_falls_back_to_max(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", 30, raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))

    await utils.random_crawl_sleep()

    assert slept == [18]  # min>max → 固定睡 max


@pytest.mark.asyncio
async def test_invalid_config_falls_back_to_max(monkeypatch):
    monkeypatch.setattr(config, "CRAWLER_MIN_SLEEP_SEC", "oops", raising=False)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 18, raising=False)
    slept = []
    monkeypatch.setattr(utils.asyncio, "sleep", AsyncMock(side_effect=lambda s: slept.append(s)))

    await utils.random_crawl_sleep()

    assert slept == [18]
