"""LLM 近重簇合并裁决：灰区相似度的簇对，「是不是同一件事」交给判断。

## 动机（2026-07-16 真库诊断）

发布事件里出现真·近重对：「中大招生与报考」vs「中大报考与名校宣传」——时间重叠、
话题相同、各自成事件。质心余弦落在合并阈值 0.86 之下，而 **0.85 实测塌方**
（最大簇吞掉 60% 语料），调阈值治不了。这是抽象层的老问题换了个方向：
embedding 只回答「像不像」，「是不是一件事」是判断。精修（llm_refine）管拆分
和命名，这里补上它缺的另一半：跨簇合并。

## 裁决范围（三道减法，每一道都是护栏）

1. 只裁**灰区** [gray_low, merge_threshold)：更高的 embedding 已经自动合并，
   更低的连"疑似"都算不上，不值得花 LLM；
2. **时间约束先行**：合并后成员时间跨度超过 max_span_days 的对根本不进候选——
   时间门控拆开的簇（2018 的宿舍咨询 vs 2026 的）是设计行为，模型看不见完整
   日期分布，不许它缝回去；
3. 每轮裁决对数封顶 max_pairs（按次计费的成本护栏），按相似度从高到低取。

## 失败方向

judge 返回 None / 抛异常 / 给不出合法布尔 → **不合并**并留 warning。
错误不对称：错合并两个真实事件 = 两件事的证据互相污染且无声；错保留拆分 =
读者看到两个相邻的事件，自己能看出来。宁可拆分，不可误并。

This module stays dependency-free on purpose（与 llm_refine 同口径）：
判断函数由运行环境注入（backend/services/event_merger.py），核心不认识 HTTP。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .clustering import note_rank_key
from .recency import note_time


# 输入：{"a": 簇摘要, "b": 簇摘要}（title/note_titles/time_range/size）。
# 输出：Mapping 含 same_event 布尔（或直接给布尔）。None/异常 = 本次裁决不可用。
MergePairJudge = Callable[[Mapping[str, Any]], Any]

# 灰区下限。0.70 与事件层语义匹配阈值同源（chat 侧实测该档位能拒绝无关话题）；
# 低于它的簇对连"疑似同一事件"都算不上。
DEFAULT_GRAY_LOW = 0.70
# 每轮最多裁决多少对。真库 119 簇的灰区对远多于此——从相似度最高的开始裁，
# 剩下的留给下一轮（事件每轮重新生成，不欠账）。
DEFAULT_MAX_PAIRS = 12


def _brief(cluster: dict) -> dict[str, Any]:
    """给裁决模型看的簇摘要：标题 + 代表帖题 + 时间范围 + 规模。"""

    notes = cluster["notes"]
    ranked = sorted(notes, key=note_rank_key, reverse=True)
    times = sorted(t for t in (note_time(note) for note in notes) if t is not None)
    return {
        "title": cluster.get("llm_title") or (ranked[0].title if ranked else ""),
        "note_titles": [note.title for note in ranked[:5]],
        "time_range": [
            times[0].date().isoformat() if times else "",
            times[-1].date().isoformat() if times else "",
        ],
        "size": len(notes),
    }


def _combined_span_days(a: dict, b: dict) -> float | None:
    times = [
        t
        for cluster in (a, b)
        for t in (note_time(note) for note in cluster["notes"])
        if t is not None
    ]
    if len(times) < 2:
        return None
    return (max(times) - min(times)).total_seconds() / 86400.0


def _verdict_is_same(raw: Any) -> bool | None:
    """把模型输出翻译成布尔；翻译不了返回 None（调用方按不可用处理）。"""

    if isinstance(raw, bool):
        return raw
    if isinstance(raw, Mapping) and isinstance(raw.get("same_event"), bool):
        return bool(raw["same_event"])
    return None


def merge_adjudicated_clusters(
    clusters: list[dict],
    judge: MergePairJudge | None,
    *,
    merge_threshold: float,
    make_cluster: Callable[[list], dict],
    gray_low: float = DEFAULT_GRAY_LOW,
    max_span_days: float = 0.0,
    max_pairs: int = DEFAULT_MAX_PAIRS,
    warnings: list[str] | None = None,
) -> tuple[list[dict], int]:
    """裁决灰区簇对并合并；返回（新簇列表, 合并次数）。judge=None 时是恒等变换。"""

    if judge is None or len(clusters) < 2:
        return clusters, 0
    log = warnings if warnings is not None else []

    # 候选对：灰区相似度 + 时间兼容，按相似度降序、封顶。
    candidates: list[tuple[float, int, int]] = []
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            similarity = sum(
                x * y for x, y in zip(clusters[i]["centroid"], clusters[j]["centroid"])
            )
            if not (gray_low <= similarity < merge_threshold):
                continue
            if max_span_days > 0:
                span = _combined_span_days(clusters[i], clusters[j])
                if span is not None and span > max_span_days:
                    continue  # 时间门控拆开的，不许缝回去
            candidates.append((similarity, i, j))
    candidates.sort(reverse=True)
    candidates = candidates[: max(int(max_pairs), 0)]

    # 贪心合并：吸收后的簇沿用代表下标，后续对若引用已死下标则跳过。
    # 合并后的质心会变，但不重算后续候选的相似度——每对裁决独立成立，
    # 重算只会让结果依赖裁决顺序。
    alive: dict[int, dict] = dict(enumerate(clusters))
    merged_count = 0
    for _similarity, i, j in candidates:
        if i not in alive or j not in alive:
            continue
        first, second = alive[i], alive[j]
        try:
            verdict = _verdict_is_same(judge({"a": _brief(first), "b": _brief(second)}))
        except Exception as exc:
            log.append(f"merge judge failed ({type(exc).__name__}); pair kept split")
            continue
        if verdict is None:
            log.append("merge judge returned no usable verdict; pair kept split")
            continue
        if not verdict:
            continue
        combined = make_cluster(list(first["members"]) + list(second["members"]))
        # LLM 标题跟着大簇走（事件身份以证据多的一侧为准）；小簇的标题随合并消失。
        bigger = first if len(first["notes"]) >= len(second["notes"]) else second
        if bigger.get("llm_title"):
            combined["llm_title"] = bigger["llm_title"]
            combined["llm_miscellaneous"] = bool(bigger.get("llm_miscellaneous"))
        combined["llm_merged"] = True
        alive[i] = combined
        del alive[j]
        merged_count += 1

    return [alive[key] for key in sorted(alive)], merged_count
