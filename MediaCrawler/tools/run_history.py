# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/run_history.py
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

"""通用爬取历史（crawler_run_history）的纯逻辑：行组装、计数、stop_reason 归结。

每个关键词一轮搜索写一行，读侧（推荐端 adapter）据 items_stored 判定贫瘠词。
设计：主项目 docs/superpowers/specs/2026-07-10-keyword-quality-pipeline-design.md P1-2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

# stop_reason 归结：首个合法原因生效，finish 时未标记则落 completed
STOP_QUOTA_REACHED = "quota_reached"  # 新增入库条数达到配额
STOP_EMPTY_PAGE = "empty_page"  # 平台返回空页/无更多内容
STOP_WINDOW_EXHAUSTED = "window_exhausted"  # 整页发布时间早于窗口起点
STOP_EXCEPTION = "exception"  # 异常中断
STOP_COMPLETED = "completed"  # 正常跑完（含页保护上限触发）
STOP_PARSER_MISMATCH = "parser_mismatch"  # 页面有数据但解析器不认识（DOM 变化，重试无用，需人工适配）

STOP_REASONS = (
    STOP_QUOTA_REACHED,
    STOP_EMPTY_PAGE,
    STOP_WINDOW_EXHAUSTED,
    STOP_EXCEPTION,
    STOP_COMPLETED,
    STOP_PARSER_MISMATCH,
)


@dataclass
class RunState:
    """单关键词一轮搜索的运行状态，as_row() 输出与 crawler_run_history 表列一一对应。"""

    platform: str
    source_keyword: str
    started_at: int
    finished_at: int = 0
    pages_fetched: int = 0
    items_seen: int = 0
    items_stored: int = 0
    stop_reason: str = ""

    def add_page(self, count: int = 1) -> None:
        """记一次实际发出的搜索翻页请求（jitter 跳过的页不计）。"""
        if int(count) > 0:
            self.pages_fetched += int(count)

    def add_seen(self, count: int) -> None:
        """累计平台返回的原始条数（过滤前）。"""
        if int(count) > 0:
            self.items_seen += int(count)

    def add_stored(self, count: int) -> None:
        """累计过滤/跳过后真正入库的条数。"""
        if int(count) > 0:
            self.items_stored += int(count)

    def mark_stop(self, reason: Any) -> None:
        """归结 stop_reason：首个合法原因生效，后续与非法原因均忽略。"""
        if self.stop_reason:
            return
        normalized = str(reason or "").strip()
        if normalized in STOP_REASONS:
            self.stop_reason = normalized

    def finish(self, finished_at: int) -> None:
        """收尾：落结束时间；未标记过停止原因则视为正常跑完。"""
        self.finished_at = int(finished_at)
        if not self.stop_reason:
            self.stop_reason = STOP_COMPLETED

    def as_row(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "source_keyword": self.source_keyword,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pages_fetched": self.pages_fetched,
            "items_seen": self.items_seen,
            "items_stored": self.items_stored,
            "stop_reason": self.stop_reason,
        }
