"""LLM 近重簇合并裁决：灰区相似度的簇对，「是不是同一件事」交给判断。

## 为什么（2026-07-16 真库诊断）

发布事件里出现真·近重对：「中大招生与报考」vs「中大报考与名校宣传」（时间重叠、
话题相同、各自发布）。质心相似度落在合并阈值 0.86 之下——**调阈值治不了**：
0.85 实测塌方（最大簇吞掉 60% 语料）。「像不像」embedding 已经答了，
「是不是一件事」是判断——精修只做拆分+命名，缺的正是跨簇合并的裁决。

## 边界

- 只裁灰区 [gray_low, merge_threshold)：更高的 embedding 已合，更低的连疑似都算不上；
- **时间约束先行**：合并后跨度超 max_span_days 的对根本不进候选——时间门控
  拆开的（2018 的宿舍咨询 vs 2026 的）是设计行为，不许 LLM 缝回去；
- 失败方向：judge 返回 None/异常/非法 → 不合并（宁可拆分，不可误并）；
- 每轮裁决对数封顶（按次计费的成本护栏）。
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta

from backend.agent.public_opinion_core.llm_merge import merge_adjudicated_clusters
from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import (
    _make_cluster,
    cluster_notes_semantic,
)


def _vec(angle_degrees: float) -> list[float]:
    rad = math.radians(angle_degrees)
    return [math.cos(rad), math.sin(rad)]


def _note(note_id: str, title: str, days_ago: float = 3.0) -> OpinionNote:
    publish = datetime(2026, 7, 10) - timedelta(days=days_ago)
    return OpinionNote(
        note_id=note_id, title=title, content=title, heat_score=10.0,
        publish_time=publish.isoformat(),
    )


def _cluster(note_id: str, title: str, angle: float, days_ago: float = 3.0, llm_title: str = ""):
    cluster = _make_cluster([(_note(note_id, title, days_ago), 0, _vec(angle))])
    if llm_title:
        cluster["llm_title"] = llm_title
    return cluster


def yes_judge(_payload):
    return {"same_event": True}


def no_judge(_payload):
    return {"same_event": False}


class MergeAdjudicationTests(unittest.TestCase):
    """gray_low=0.70 ↔ merge_threshold=0.86 之间：cos30°≈0.866 之上不裁，cos20°≈0.94 已合。
    夹角 35°（cos≈0.819）落在灰区。"""

    def _merge(self, clusters, judge, **kwargs):
        warnings: list[str] = []
        merged, count = merge_adjudicated_clusters(
            clusters, judge,
            merge_threshold=0.86, gray_low=0.70, make_cluster=_make_cluster,
            warnings=warnings, **kwargs,
        )
        return merged, count, warnings

    def test_gray_zone_pair_is_merged_on_yes(self) -> None:
        clusters = [_cluster("a", "中大招生与报考", 0), _cluster("b", "中大报考与名校宣传", 35)]

        merged, count, _ = self._merge(clusters, yes_judge)

        self.assertEqual(count, 1)
        self.assertEqual(len(merged), 1)
        self.assertEqual({n.note_id for n in merged[0]["notes"]}, {"a", "b"})

    def test_no_verdict_keeps_the_split(self) -> None:
        clusters = [_cluster("a", "招生", 0), _cluster("b", "报考", 35)]

        merged, count, _ = self._merge(clusters, no_judge)

        self.assertEqual(count, 0)
        self.assertEqual(len(merged), 2)

    def test_pairs_outside_the_gray_zone_are_never_judged(self) -> None:
        calls = []

        def spy(payload):
            calls.append(payload)
            return {"same_event": True}

        # 夹角 60°（cos=0.5 < gray_low）：连疑似都算不上
        merged, count, _ = self._merge([_cluster("a", "食堂", 0), _cluster("b", "校车", 60)], spy)

        self.assertEqual(calls, [], "灰区之外的对不许花 LLM")
        self.assertEqual(count, 0)

    def test_time_incompatible_pairs_are_not_candidates(self) -> None:
        calls = []

        def spy(payload):
            calls.append(payload)
            return {"same_event": True}

        clusters = [
            _cluster("a", "宿舍咨询（2018）", 0, days_ago=2000),
            _cluster("b", "宿舍咨询（2026）", 35, days_ago=2),
        ]
        merged, count, _ = self._merge(clusters, spy, max_span_days=180.0)

        self.assertEqual(calls, [], "时间门控拆开的簇不许 LLM 缝回去——那是设计行为")
        self.assertEqual(len(merged), 2)

    def test_invalid_verdict_degrades_to_no_merge_with_warning(self) -> None:
        merged, count, warnings = self._merge(
            [_cluster("a", "招生", 0), _cluster("b", "报考", 35)], lambda _p: "咕咕咕"
        )

        self.assertEqual(count, 0)
        self.assertEqual(len(merged), 2)
        self.assertTrue(warnings, "裁决不可用必须留痕")

    def test_judge_exception_degrades_to_no_merge(self) -> None:
        def boom(_payload):
            raise RuntimeError("llm down")

        merged, count, warnings = self._merge([_cluster("a", "招生", 0), _cluster("b", "报考", 35)], boom)

        self.assertEqual(count, 0)
        self.assertEqual(len(merged), 2)
        self.assertTrue(warnings)

    def test_max_pairs_caps_the_llm_spend(self) -> None:
        calls = []

        def spy(payload):
            calls.append(payload)
            return {"same_event": False}

        # 三个簇彼此都在灰区（0/35/70 度两两夹角 35°）→ 3 对候选，cap=1 只裁 1 对
        clusters = [_cluster("a", "甲", 0), _cluster("b", "乙", 35), _cluster("c", "丙", 70)]
        self._merge(clusters, spy, max_pairs=1)

        self.assertEqual(len(calls), 1, "裁决对数必须封顶——按次计费")

    def test_merged_cluster_keeps_the_larger_llm_title(self) -> None:
        big = _make_cluster([
            (_note("a1", "招生宣传一"), 0, _vec(0)),
            (_note("a2", "招生宣传二"), 1, _vec(0)),
        ])
        big["llm_title"] = "中大招生与报考"
        small = _cluster("b", "报考讨论", 35, llm_title="中大报考宣传")

        merged, count, _ = self._merge([big, small], yes_judge)

        self.assertEqual(count, 1)
        self.assertEqual(merged[0].get("llm_title"), "中大招生与报考", "合并簇沿用大簇的 LLM 标题")

    def test_no_judge_is_identity(self) -> None:
        clusters = [_cluster("a", "招生", 0), _cluster("b", "报考", 35)]

        merged, count, _ = self._merge(clusters, None)

        self.assertEqual(count, 0)
        self.assertEqual(len(merged), 2)


class EndToEndTests(unittest.TestCase):
    def test_cluster_notes_semantic_reports_merged_count(self) -> None:
        notes = [_note("a", "中大招生与报考"), _note("b", "中大报考与名校宣传")]
        result = cluster_notes_semantic(
            notes,
            [_vec(0), _vec(35)],
            cluster_threshold=0.95,
            merge_threshold=0.86,
            merge_judge=yes_judge,
        )

        self.assertEqual(len(result.events), 1, "灰区近重对经 LLM 裁决后应合成一个事件")
        self.assertEqual(result.merged_clusters, 1)
        self.assertEqual(result.events[0].source_count, 2)


if __name__ == "__main__":
    unittest.main()
