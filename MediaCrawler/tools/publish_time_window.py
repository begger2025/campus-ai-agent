# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/publish_time_window.py
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

"""发布时间窗口筛选与防饥饿候选选择的纯函数工具。

三平台搜索 API 均不支持服务端时间参数，窗口过滤只能在客户端做；
本模块集中可测的纯逻辑，各平台 core 只做接线。
设计：主项目 docs/superpowers/specs/2026-07-10-crawler-date-window-design.md
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

DATE_FORMAT = "%Y-%m-%d"

_TIEBA_ABS_TIME_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$")


def parse_window(start: Optional[str], end: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """把 "YYYY-MM-DD" 窗口解析为毫秒 epoch 闭区间；空/None 表示该端不限。非法格式抛 ValueError。"""

    lo: Optional[int] = None
    hi: Optional[int] = None
    start = (start or "").strip()
    end = (end or "").strip()
    if start:
        lo = int(datetime.strptime(start, DATE_FORMAT).timestamp() * 1000)
    if end:
        end_dt = datetime.strptime(end, DATE_FORMAT) + timedelta(days=1) - timedelta(milliseconds=1)
        hi = int(end_dt.timestamp() * 1000)
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"发布时间窗口起点晚于终点: {start} > {end}")
    return lo, hi


def is_within_window(
    ts_ms: Optional[int],
    lo: Optional[int],
    hi: Optional[int],
    keep_unknown: bool = True,
) -> bool:
    """判断毫秒时间戳是否落在闭区间内；解析不出时间（None）按 keep_unknown 处理。"""

    if ts_ms is None:
        return keep_unknown
    if lo is not None and ts_ms < lo:
        return False
    if hi is not None and ts_ms > hi:
        return False
    return True


def parse_tieba_publish_time_ms(text: Any) -> Optional[int]:
    """解析贴吧搜索结果的发布时间字符串（"2026-6-12" / "2026-06-12 09:30"）。

    相对文本（"3天前"）、空值、非法日期一律返回 None，由调用方按 keep_unknown 处理。
    """

    text = str(text or "").strip()
    match = _TIEBA_ABS_TIME_RE.match(text)
    if not match:
        return None
    hour = int(match.group(4)) if match.group(4) else 0
    minute = int(match.group(5)) if match.group(5) else 0
    try:
        moment = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), hour, minute)
    except ValueError:
        return None
    return int(moment.timestamp() * 1000)


def select_with_exploration(
    items: List[Any],
    quota: int,
    explore_prob: float,
    rng: Optional[random.Random] = None,
) -> List[Any]:
    """ε-greedy 候选选择：每个名额以 1-ε 取最新（头部），ε 从较旧候选随机抽（防饥饿）。

    items 需已按"最新优先"排序；返回选中项并保持原相对顺序。
    """

    chooser: Any = rng if rng is not None else random
    if quota <= 0 or not items:
        return []
    if len(items) <= quota:
        return list(items)
    indexed = list(enumerate(items))
    chosen = []
    for _ in range(quota):
        if len(indexed) > 1 and chooser.random() < explore_prob:
            pick = chooser.randrange(1, len(indexed))
        else:
            pick = 0
        chosen.append(indexed.pop(pick))
    chosen.sort(key=lambda pair: pair[0])
    return [item for _, item in chosen]
