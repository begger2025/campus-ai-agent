# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tests/test_run_history.py
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

from tools.run_history import (
    STOP_COMPLETED,
    STOP_EMPTY_PAGE,
    STOP_EXCEPTION,
    STOP_QUOTA_REACHED,
    STOP_REASONS,
    STOP_WINDOW_EXHAUSTED,
    RunState,
)


class TestRunStateAssembly:
    def test_initial_state(self):
        state = RunState(platform="wb", source_keyword="中山大学 宿舍", started_at=1000)
        assert state.platform == "wb"
        assert state.source_keyword == "中山大学 宿舍"
        assert state.started_at == 1000
        assert state.finished_at == 0
        assert state.pages_fetched == 0
        assert state.items_seen == 0
        assert state.items_stored == 0
        assert state.stop_reason == ""

    def test_counters_accumulate(self):
        state = RunState(platform="tieba", source_keyword="中大 食堂", started_at=1)
        state.add_page()
        state.add_seen(10)
        state.add_stored(3)
        state.add_page()
        state.add_seen(7)
        state.add_stored(0)
        assert state.pages_fetched == 2
        assert state.items_seen == 17
        assert state.items_stored == 3

    def test_negative_counts_ignored(self):
        state = RunState(platform="xhs", source_keyword="kw", started_at=1)
        state.add_seen(-5)
        state.add_stored(-1)
        assert state.items_seen == 0
        assert state.items_stored == 0

    def test_as_row_matches_table_columns(self):
        state = RunState(platform="wb", source_keyword="kw", started_at=100)
        state.add_page()
        state.add_seen(9)
        state.add_stored(2)
        state.mark_stop(STOP_QUOTA_REACHED)
        state.finish(finished_at=200)
        assert state.as_row() == {
            "platform": "wb",
            "source_keyword": "kw",
            "started_at": 100,
            "finished_at": 200,
            "pages_fetched": 1,
            "items_seen": 9,
            "items_stored": 2,
            "stop_reason": STOP_QUOTA_REACHED,
        }


class TestStopReasonResolution:
    def test_known_reasons_registry(self):
        assert STOP_REASONS == (
            STOP_QUOTA_REACHED,
            STOP_EMPTY_PAGE,
            STOP_WINDOW_EXHAUSTED,
            STOP_EXCEPTION,
            STOP_COMPLETED,
        )

    def test_first_reason_wins(self):
        state = RunState(platform="wb", source_keyword="kw", started_at=1)
        state.mark_stop(STOP_EMPTY_PAGE)
        state.mark_stop(STOP_QUOTA_REACHED)
        assert state.stop_reason == STOP_EMPTY_PAGE

    def test_unknown_or_empty_reason_ignored(self):
        state = RunState(platform="wb", source_keyword="kw", started_at=1)
        state.mark_stop("")
        state.mark_stop(None)
        state.mark_stop("not_a_reason")
        assert state.stop_reason == ""
        # 之后合法原因仍可正常落位
        state.mark_stop(STOP_WINDOW_EXHAUSTED)
        assert state.stop_reason == STOP_WINDOW_EXHAUSTED

    def test_finish_defaults_to_completed(self):
        state = RunState(platform="tieba", source_keyword="kw", started_at=1)
        state.finish(finished_at=99)
        assert state.finished_at == 99
        assert state.stop_reason == STOP_COMPLETED

    def test_finish_keeps_existing_reason(self):
        state = RunState(platform="xhs", source_keyword="kw", started_at=1)
        state.mark_stop(STOP_EXCEPTION)
        state.finish(finished_at=50)
        assert state.stop_reason == STOP_EXCEPTION
        assert state.finished_at == 50
