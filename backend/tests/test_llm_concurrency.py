"""事件流水线的 LLM 研判并行化：**快，而且逐位还是那个结果**。

**被修的缺陷**（实测）：`scripts/generate_public_events.py` 每跑一次要打 90+ 次**串行** LLM
调用——37 个事件 × 2（风险 + 状态）+ N 个簇（聚类精修），单次 4~7 秒，合计 7~8 分钟。
而这些事件**彼此互不依赖**：判「宿舍火灾有多严重」不需要先知道「食堂涨价」判成了什么。
串行在这里不是必要，是纯粹的浪费。

**并行化真正危险的地方不是崩溃，是"结果悄悄变了"**：这些研判要喂给消融实验
（`scripts/ablation_event_*.py`），而答辩的前提是"任何人重跑都得到同一份结果"。
线程池最自然的写法——

    for future in as_completed(futures):   # 谁先回来谁先进列表
        results.append(future.result())

——恰恰**按完成顺序**收集结果：网络快的事件排到前面，于是同一批输入每跑一次得到一个新顺序，
而且一个事件的研判会安在另一个事件头上。这是本文件一半用例在防的东西。

四条契约：

  1. **顺序**：输出顺序 == 输入顺序（哪怕 assessor 故意反着返回）；
  2. **一致**：并行结果与串行结果**逐字段相等**，连 warnings 的顺序都一样；
  3. **隔离**：一个事件的 assessor 炸了，只有它降级，别的事件照常出结果；
  4. **可配**：并发度可调，设成 1 时**真的**退回串行（连线程都不开）。

零网络、零数据库：assessor / refiner 全是打桩的假货（sleep 冒充 API 延迟）。
"""

from __future__ import annotations

import re
import threading
import time
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from backend.agent.public_opinion_core.clustering import build_event_from_group
from backend.agent.public_opinion_core.concurrency import (
    DEFAULT_LLM_CONCURRENCY,
    map_calls,
    resolve_concurrency,
)
from backend.agent.public_opinion_core.llm_lifecycle import assess_events_lifecycle
from backend.agent.public_opinion_core.llm_refine import refine_clusters
from backend.agent.public_opinion_core.llm_risk import assess_events_risk
from backend.agent.public_opinion_core.schemas import AnalyzeRequest, OpinionEvent, OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import _make_cluster
from backend.agent.public_opinion_core.service import PublicOpinionAgentService


EVENT_COUNT = 12

# 打桩的"网络延迟"。真实调用 4~7s，这里只要长到让线程真的重叠。
DELAY = 0.02

# 比较串行/并行两个臂时必须钉死的"现在"：recency_weight 是相对它算的，而两个臂是先后跑的。
# 不钉住，priority_score 会因为**时间流逝**（不是并发）在小数点第 6 位上不同。
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def index_of(text: str) -> int:
    """从打桩的标题里取回序号。

    事件标题在服务层会被加上「相关讨论」的尾巴（词频命名），所以只认第一串数字。
    """

    match = re.search(r"\d+", text)
    assert match is not None, text
    return int(match.group())


def make_notes(index: int) -> list[OpinionNote]:
    return [
        OpinionNote(
            note_id=f"n{index:02d}-{seq}",
            title=f"事件{index:02d} 的第 {seq} 条帖子",
            content=f"事件{index:02d} 的第 {seq} 条帖子正文",
            heat_score=float(seq),
        )
        for seq in range(3)
    ]


def make_event(index: int) -> OpinionEvent:
    return build_event_from_group(
        f"sem:{index:02d}", f"事件{index:02d}", "semantic", make_notes(index)
    )


def make_events(count: int = EVENT_COUNT) -> list[OpinionEvent]:
    return [make_event(index) for index in range(count)]


def judgement(index: int) -> dict[str, Any]:
    """每个事件一份**不同**的研判：结果一旦串位（张冠李戴）必然被断言抓到。

    分数用 index × 2：既保证每个事件互不相同，又保证 40 个事件时仍落在 0-100 内——
    越界的分数会被 `llm_risk._validate` 正当地打回（那是安全边界，不是打桩的自由）。
    """

    return {
        "risk_level": ("low", "medium", "high")[index % 3],
        "risk_score": float(index * 2),
        "risk_reasons": [f"事件{index:02d} 的风险依据"],
        "concerns": [f"事件{index:02d} 的关注点"],
    }


def verdict(index: int) -> dict[str, Any]:
    return {
        "lifecycle": ("resolved", "ongoing", "not_applicable")[index % 3],
        "lifecycle_reason": f"事件{index:02d} 的状态理由",
    }


class Probe:
    """打桩的 assessor：记录并发峰值与完成顺序，并**故意反序返回**。

    延迟 = DELAY × (总数 - 序号)：0 号睡得最久、最后一个返回。于是"完成顺序"与"输入顺序"
    必然相反——按完成顺序收集结果的实现（as_completed + append）会立刻露馅。
    """

    def __init__(self, respond, count: int = EVENT_COUNT, delay: float = DELAY) -> None:
        self._lock = threading.Lock()
        self._respond = respond
        self._count = count
        self._delay = delay
        self._active = 0
        self.peak = 0
        self.started: list[int] = []
        self.completed: list[int] = []

    def __call__(self, title: str, texts: list[str]) -> Any:
        index = index_of(title)
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)
            self.started.append(index)
        try:
            time.sleep(self._delay * (self._count - index))
            return self._respond(index, texts)
        finally:
            with self._lock:
                self._active -= 1
                self.completed.append(index)


# ---- 精修（per-cluster）的打桩件 ----

CLUSTER_COUNT = 6
CLUSTER_SIZE = 8


def make_clusters() -> list[dict]:
    clusters: list[dict] = []
    for index in range(CLUSTER_COUNT):
        members = [
            (
                OpinionNote(
                    note_id=f"c{index:02d}-{seq:02d}",
                    title=f"簇{index:02d} 第 {seq} 帖",
                    content=f"簇{index:02d} 第 {seq} 帖",
                ),
                index * CLUSTER_SIZE + seq,
                [1.0, 0.0],
            )
            for seq in range(CLUSTER_SIZE)
        ]
        clusters.append(_make_cluster(members))
    return clusters


def whole_cluster_topic(index: int, texts: list[str]) -> list[dict[str, Any]]:
    return [{"title": f"精修话题{index:02d}", "members": list(range(1, len(texts) + 1))}]


def refiner_probe(respond=whole_cluster_topic, delay: float = DELAY):
    """打桩 refiner：它只拿得到 texts（没有事件标题），从帖子正文里取回簇号。"""

    lock = threading.Lock()
    state: dict[str, Any] = {"active": 0, "peak": 0, "completed": []}

    def refiner(texts: list[str]) -> Any:
        index = index_of(texts[0])
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(delay * (CLUSTER_COUNT - index))  # 反序完成
            return respond(index, texts)
        finally:
            with lock:
                state["active"] -= 1
                state["completed"].append(index)

    return refiner, state


class MapCallsTest(unittest.TestCase):
    """并发原语本身：等长、同序、异常就地捕获、并发度不超上限。"""

    def test_default_concurrency_is_eight(self) -> None:
        self.assertEqual(DEFAULT_LLM_CONCURRENCY, 8)

    def test_results_follow_input_order_not_completion_order(self) -> None:
        completed: list[int] = []

        def call(item: int) -> int:
            time.sleep(DELAY * (10 - item))  # 反序完成
            completed.append(item)
            return item * 10

        outcomes = map_calls(call, list(range(10)), concurrency=10)

        self.assertEqual([outcome.value for outcome in outcomes], [item * 10 for item in range(10)])
        self.assertNotEqual(completed, sorted(completed), "打桩没造出乱序完成，这个用例就没在测东西")

    def test_exceptions_are_captured_per_item_not_raised(self) -> None:
        def call(item: int) -> int:
            if item == 1:
                raise TimeoutError("read timed out")
            return item

        outcomes = map_calls(call, [0, 1, 2], concurrency=4)

        self.assertEqual(outcomes[0].value, 0)
        self.assertIsNone(outcomes[1].value)
        self.assertIsInstance(outcomes[1].error, TimeoutError)
        self.assertEqual(outcomes[2].value, 2)  # 1 号炸了不影响 2 号

    def test_concurrency_is_capped(self) -> None:
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def call(item: int) -> int:
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(DELAY)
            with lock:
                state["active"] -= 1
            return item

        map_calls(call, list(range(20)), concurrency=4)

        self.assertGreater(state["peak"], 1, "根本没并发起来")
        self.assertLessEqual(state["peak"], 4, "并发度超过了上限")

    def test_concurrency_one_runs_inline_without_threads(self) -> None:
        """并发度 1 = **真串行**：不开线程池，调用就发生在调用者的线程里。"""

        caller = threading.current_thread().name
        seen: list[str] = []

        map_calls(lambda item: seen.append(threading.current_thread().name), [1, 2, 3], concurrency=1)

        self.assertEqual(seen, [caller, caller, caller])

    def test_empty_input_makes_no_calls(self) -> None:
        self.assertEqual(map_calls(lambda item: 1 / 0, [], concurrency=8), [])

    def test_resolve_concurrency_defaults_and_floors(self) -> None:
        self.assertEqual(resolve_concurrency(None), DEFAULT_LLM_CONCURRENCY)
        self.assertEqual(resolve_concurrency(4), 4)
        self.assertEqual(resolve_concurrency(0), 1)  # 0 / 负数 = 串行，不是"不调用"
        self.assertEqual(resolve_concurrency(-3), 1)


class RiskConcurrencyTest(unittest.TestCase):
    """风险研判：37 次调用并行跑，结果一个都不许串位。"""

    def test_assessor_is_actually_called_concurrently(self) -> None:
        probe = Probe(lambda index, texts: judgement(index))

        assess_events_risk(make_events(), probe, concurrency=8)

        self.assertGreater(probe.peak, 1, "assessor 仍然是串行调用的（没并发起来）")
        self.assertLessEqual(probe.peak, 8, "并发度超过了上限")
        self.assertEqual(len(probe.started), EVENT_COUNT)

    def test_every_event_gets_its_own_judgement(self) -> None:
        events = make_events()
        probe = Probe(lambda index, texts: judgement(index))

        assessed = assess_events_risk(events, probe, concurrency=8)

        self.assertEqual(assessed, EVENT_COUNT)
        # 完成顺序确实是乱的（否则这个用例证明不了任何东西）。
        self.assertNotEqual(probe.completed, list(range(EVENT_COUNT)))
        # 而结果必须逐个对上号：第 i 个事件拿到的是第 i 份研判。
        for index, event in enumerate(events):
            expected = judgement(index)
            self.assertEqual(event.risk_level, expected["risk_level"])
            self.assertEqual(event.risk_score, expected["risk_score"])
            self.assertEqual(event.risk_reasons, expected["risk_reasons"])
            self.assertEqual(event.concerns, expected["concerns"])

    def test_event_list_order_is_never_reshuffled(self) -> None:
        events = make_events()
        before = [event.event_key for event in events]

        assess_events_risk(events, Probe(lambda index, texts: judgement(index)), concurrency=8)

        self.assertEqual([event.event_key for event in events], before)

    def test_one_failing_event_does_not_poison_the_others(self) -> None:
        events = make_events()
        rule_level = events[5].risk_level
        warnings: list[str] = []

        def respond(index: int, texts: list[str]) -> dict[str, Any]:
            if index == 5:
                raise TimeoutError("read timed out")
            return judgement(index)

        assessed = assess_events_risk(events, Probe(respond), warnings=warnings, concurrency=8)

        self.assertEqual(assessed, EVENT_COUNT - 1)
        self.assertEqual(events[5].risk_level, rule_level)  # 规则结果原样保留
        self.assertNotIn("risk_assessed_by", events[5].extra)
        self.assertEqual(len(warnings), 1)
        self.assertIn("事件05", warnings[0])
        for index, event in enumerate(events):
            if index != 5:
                self.assertEqual(event.extra["risk_assessed_by"], "llm")

    def test_events_without_texts_are_never_sent_to_the_model(self) -> None:
        """没有正文就没有输入：这条既有语义在并行之后必须还在（不许模型凭标题硬编）。"""

        events = make_events(3)
        events[1].representative_notes = []
        probe = Probe(lambda index, texts: judgement(index), count=3)

        assessed = assess_events_risk(events, probe, concurrency=8)

        self.assertEqual(assessed, 2)
        self.assertEqual(sorted(probe.started), [0, 2])


class LifecycleConcurrencyTest(unittest.TestCase):
    """状态研判：与风险研判同一批事件、同一套并行契约。"""

    def test_assessor_is_actually_called_concurrently(self) -> None:
        probe = Probe(lambda index, texts: verdict(index))

        assess_events_lifecycle(make_events(), probe, concurrency=8)

        self.assertGreater(probe.peak, 1, "assessor 仍然是串行调用的（没并发起来）")
        self.assertLessEqual(probe.peak, 8)

    def test_every_event_gets_its_own_verdict(self) -> None:
        events = make_events()
        probe = Probe(lambda index, texts: verdict(index))

        assessed = assess_events_lifecycle(events, probe, concurrency=8)

        self.assertEqual(assessed, EVENT_COUNT)
        self.assertNotEqual(probe.completed, list(range(EVENT_COUNT)))
        for index, event in enumerate(events):
            expected = verdict(index)
            self.assertEqual(event.lifecycle, expected["lifecycle"])
            self.assertEqual(event.lifecycle_judgement, expected["lifecycle"])
            self.assertEqual(event.lifecycle_reason, expected["lifecycle_reason"])

    def test_one_failing_event_does_not_poison_the_others(self) -> None:
        events = make_events()
        warnings: list[str] = []

        def respond(index: int, texts: list[str]) -> dict[str, Any]:
            if index == 3:
                raise TimeoutError("read timed out")
            return verdict(index)

        assessed = assess_events_lifecycle(events, Probe(respond), warnings=warnings, concurrency=8)

        self.assertEqual(assessed, EVENT_COUNT - 1)
        self.assertEqual(events[3].lifecycle, "")  # 未研判（因子 1.0）
        self.assertEqual(len(warnings), 1)
        self.assertIn("事件03", warnings[0])


class RefineConcurrencyTest(unittest.TestCase):
    """聚类精修：per-cluster 的 LLM 调用同样并行；簇的划分与 warnings 顺序都不许变。"""

    def test_refiner_is_actually_called_concurrently(self) -> None:
        refiner, state = refiner_probe()

        _clusters, refined, _ejected = refine_clusters(
            make_clusters(), refiner, make_cluster=_make_cluster, min_size=4, concurrency=8
        )

        self.assertEqual(refined, CLUSTER_COUNT)
        self.assertGreater(state["peak"], 1, "refiner 仍然是串行调用的（没并发起来）")
        self.assertNotEqual(state["completed"], list(range(CLUSTER_COUNT)))

    def test_each_cluster_keeps_its_own_title(self) -> None:
        refiner, _state = refiner_probe()

        clusters, _refined, _ejected = refine_clusters(
            make_clusters(), refiner, make_cluster=_make_cluster, min_size=4, concurrency=8
        )

        # 每个簇拿到的必须是**它自己的**标题（结果串位的话这里必炸）。
        by_title = {cluster["llm_title"]: cluster for cluster in clusters}
        for index in range(CLUSTER_COUNT):
            cluster = by_title[f"精修话题{index:02d}"]
            self.assertEqual(
                [note.note_id for note in cluster["notes"]],
                [f"c{index:02d}-{seq:02d}" for seq in range(CLUSTER_SIZE)],
            )

    def test_one_failing_cluster_does_not_poison_the_others(self) -> None:
        def respond(index: int, texts: list[str]) -> Any:
            if index == 2:
                raise TimeoutError("read timed out")
            return whole_cluster_topic(index, texts)

        refiner, _state = refiner_probe(respond=respond)
        warnings: list[str] = []

        clusters, refined, _ejected = refine_clusters(
            make_clusters(),
            refiner,
            make_cluster=_make_cluster,
            min_size=4,
            warnings=warnings,
            concurrency=8,
        )

        self.assertEqual(refined, CLUSTER_COUNT - 1)
        titles = {cluster.get("llm_title") for cluster in clusters}
        self.assertNotIn("精修话题02", titles)  # 2 号退回 embedding 簇（没有 llm_title）
        self.assertEqual(len(warnings), 1)
        self.assertIn("unavailable", warnings[0])
        # 守恒：一条帖子都没丢
        self.assertEqual(
            sum(len(cluster["notes"]) for cluster in clusters), CLUSTER_COUNT * CLUSTER_SIZE
        )

    def test_clusters_below_min_size_are_still_skipped(self) -> None:
        """并行不改变"哪些簇值得一次 LLM 调用"：小簇一次调用都不许发。"""

        clusters = make_clusters()
        refiner, state = refiner_probe()

        refine_clusters(clusters, refiner, make_cluster=_make_cluster, min_size=99, concurrency=8)

        self.assertEqual(state["completed"], [], "小簇不该被送去精修")


class SerialParallelEquivalenceTest(unittest.TestCase):
    """**核心断言**：并行结果与串行结果逐位一致——消融实验的可复现性靠它。

    打桩里塞满了并行最容易出错的东西：反序返回、分散在不同位置的失败、格式非法的输出。
    比较的是**全部字段 + warnings 的完整列表（含顺序）**。
    """

    def risk_respond(self, index: int, texts: list[str]) -> Any:
        if index == 4:
            raise TimeoutError("read timed out")  # 挂了 -> 退回规则风险
        if index == 7:
            return {"risk_level": "critical", "risk_score": 140}  # 幻觉 -> 作废
        return judgement(index)

    def lifecycle_respond(self, index: int, texts: list[str]) -> Any:
        if index == 2:
            raise RuntimeError("502 bad gateway")
        if index == 9:
            return {"lifecycle": "dormant", "lifecycle_reason": "编的状态"}
        if index == 6:
            return {"lifecycle": "escalating", "lifecycle_reason": "模型越权"}  # -> 降级成 ongoing
        return verdict(index)

    def snapshot(self, events: list[OpinionEvent]) -> list[tuple]:
        return [
            (
                event.event_key,
                event.title,
                event.risk_level,
                event.risk_score,
                tuple(event.risk_reasons),
                tuple(event.concerns),
                event.agent_summary,
                event.lifecycle,
                event.lifecycle_judgement,
                event.lifecycle_reason,
                event.heat_score,
                event.ranking_score,
                event.source_count,
                tuple(sorted(event.extra.items())),
            )
            for event in events
        ]

    def run_risk(self, concurrency: int) -> tuple[list[tuple], list[str], int]:
        events = make_events()
        warnings: list[str] = []
        assessed = assess_events_risk(
            events, Probe(self.risk_respond), warnings=warnings, concurrency=concurrency
        )
        return self.snapshot(events), warnings, assessed

    def run_lifecycle(self, concurrency: int) -> tuple[list[tuple], list[str], int]:
        events = make_events()
        warnings: list[str] = []
        assessed = assess_events_lifecycle(
            events, Probe(self.lifecycle_respond), warnings=warnings, concurrency=concurrency
        )
        return self.snapshot(events), warnings, assessed

    def test_risk_parallel_equals_serial(self) -> None:
        serial = self.run_risk(concurrency=1)
        parallel = self.run_risk(concurrency=8)

        self.assertEqual(parallel[0], serial[0], "并行之后事件字段变了")
        self.assertEqual(parallel[1], serial[1], "并行之后 warnings 的内容或顺序变了")
        self.assertEqual(parallel[2], serial[2])
        self.assertEqual(serial[2], EVENT_COUNT - 2)  # 4 号超时 + 7 号幻觉
        self.assertEqual(len(serial[1]), 2)

    def test_lifecycle_parallel_equals_serial(self) -> None:
        serial = self.run_lifecycle(concurrency=1)
        parallel = self.run_lifecycle(concurrency=8)

        self.assertEqual(parallel[0], serial[0], "并行之后事件字段变了")
        self.assertEqual(parallel[1], serial[1], "并行之后 warnings 的内容或顺序变了")
        self.assertEqual(parallel[2], serial[2])
        # 2 号超时、9 号编状态 -> 未研判；6 号 escalating 降级成 ongoing（仍算研判成功）。
        self.assertEqual(serial[2], EVENT_COUNT - 2)
        self.assertEqual(len(serial[1]), 3)  # 超时 + 不可用 + 降级各一条

    def test_warnings_keep_input_order_not_completion_order(self) -> None:
        """warnings 是按**事件顺序**排的，不是按"谁先失败"排的。"""

        events = make_events()
        warnings: list[str] = []

        def respond(index: int, texts: list[str]) -> Any:
            if index in (1, 8, 10):
                raise TimeoutError("read timed out")
            return judgement(index)

        assess_events_risk(events, Probe(respond), warnings=warnings, concurrency=8)

        self.assertEqual(len(warnings), 3)
        # 反序返回 ⇒ 10 号最先失败。但 warnings 里必须依然是 1、8、10。
        self.assertIn("事件01", warnings[0])
        self.assertIn("事件08", warnings[1])
        self.assertIn("事件10", warnings[2])

    def test_refine_parallel_equals_serial(self) -> None:
        def respond(index: int, texts: list[str]) -> Any:
            if index == 1:
                raise TimeoutError("read timed out")  # -> 退回 embedding 簇
            if index == 3:
                return [{"title": "编号越界", "members": [99]}]  # -> 整簇作废
            if index == 4:  # 拆成两个话题 + 剔一条离群帖 + 漏一条（残余簇）
                return [
                    {"title": "精修话题04A", "members": [1, 2, 3]},
                    {"title": "精修话题04B", "members": [5, 6, 7]},
                    {"members": [8], "unrelated": True},
                ]
            return whole_cluster_topic(index, texts)

        def run(concurrency: int):
            refiner, _state = refiner_probe(respond=respond)
            warnings: list[str] = []
            clusters, refined, ejected = refine_clusters(
                make_clusters(),
                refiner,
                make_cluster=_make_cluster,
                min_size=4,
                warnings=warnings,
                concurrency=concurrency,
            )
            shape = [
                (
                    cluster.get("llm_title"),
                    tuple(note.note_id for note in cluster["notes"]),
                    tuple(round(value, 12) for value in cluster["centroid"]),
                )
                for cluster in clusters
            ]
            return shape, warnings, refined, ejected

        serial = run(concurrency=1)
        parallel = run(concurrency=8)

        self.assertEqual(parallel[0], serial[0], "并行之后簇的划分/顺序/质心变了")
        self.assertEqual(parallel[1], serial[1], "并行之后 warnings 的内容或顺序变了")
        self.assertEqual((parallel[2], parallel[3]), (serial[2], serial[3]))
        self.assertEqual(serial[2], 4)  # 6 个簇：1 号超时、3 号作废 -> 4 个精修成功
        self.assertEqual(serial[3], 1)  # 4 号剔了 1 条


class ConcurrencyIsConfigurableTest(unittest.TestCase):
    def test_concurrency_one_is_strictly_serial(self) -> None:
        probe = Probe(lambda index, texts: judgement(index))

        assess_events_risk(make_events(), probe, concurrency=1)

        self.assertEqual(probe.peak, 1, "并发度 1 却出现了重叠调用")
        self.assertEqual(probe.started, list(range(EVENT_COUNT)), "并发度 1 时调用顺序必须是输入顺序")
        self.assertEqual(probe.completed, list(range(EVENT_COUNT)))

    def test_lifecycle_concurrency_one_is_strictly_serial(self) -> None:
        probe = Probe(lambda index, texts: verdict(index))

        assess_events_lifecycle(make_events(), probe, concurrency=1)

        self.assertEqual(probe.peak, 1)
        self.assertEqual(probe.started, list(range(EVENT_COUNT)))

    def test_refine_concurrency_one_is_strictly_serial(self) -> None:
        refiner, state = refiner_probe()

        refine_clusters(
            make_clusters(), refiner, make_cluster=_make_cluster, min_size=4, concurrency=1
        )

        self.assertEqual(state["peak"], 1)
        self.assertEqual(state["completed"], list(range(CLUSTER_COUNT)))

    def test_default_concurrency_parallelizes_without_being_asked(self) -> None:
        """默认就是并行（8）：不传参数的调用方（消融脚本）也白拿到加速。"""

        probe = Probe(lambda index, texts: judgement(index))

        assess_events_risk(make_events(), probe)

        self.assertGreater(probe.peak, 1)
        self.assertLessEqual(probe.peak, DEFAULT_LLM_CONCURRENCY)


class SpeedupTest(unittest.TestCase):
    """并行到底快了多少：40 个事件 × 0.05s 的打桩延迟（不打真 API、不烧钱）。"""

    EVENTS = 40
    STUB_LATENCY = 0.05

    def elapsed(self, concurrency: int) -> float:
        events = make_events(self.EVENTS)

        def slow(title: str, texts: list[str]) -> dict[str, Any]:
            time.sleep(self.STUB_LATENCY)
            return judgement(index_of(title))

        started = time.perf_counter()
        assessed = assess_events_risk(events, slow, concurrency=concurrency)
        self.assertEqual(assessed, self.EVENTS)
        return time.perf_counter() - started

    def test_eight_workers_beat_serial_by_a_wide_margin(self) -> None:
        serial = self.elapsed(concurrency=1)
        parallel = self.elapsed(concurrency=8)

        self.assertGreater(serial, self.EVENTS * self.STUB_LATENCY * 0.9)
        # 理论加速 8 倍；只断言 3 倍，给 CI 上的调度抖动留足余量。
        self.assertLess(
            parallel,
            serial / 3,
            f"并行没带来实质加速：串行 {serial:.2f}s vs 并行 {parallel:.2f}s",
        )


class ServiceWiringTest(unittest.TestCase):
    """service 层：一个 llm_concurrency 参数贯穿风险 / 状态 / 精修三处调用。"""

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": index + 1,
                "note_id": f"n{index:02d}",
                "title": f"事件{index:02d}",
                "content": f"事件{index:02d} 的正文",
                "platform": "xhs",
            }
            for index in range(EVENT_COUNT)
        ]

    def analyze(self, **kwargs):
        return PublicOpinionAgentService().analyze_from_rows(
            self.rows(),
            AnalyzeRequest(limit=50),
            # 每条帖子一个正交向量 -> 每条帖子自成一簇 -> EVENT_COUNT 个事件（各一次 LLM）。
            embedder=lambda texts: [
                [1.0 if column == row else 0.0 for column in range(len(texts))]
                for row in range(len(texts))
            ],
            cluster_threshold=0.9,
            min_cluster_size=1,
            **kwargs,
        )

    def test_service_passes_concurrency_to_risk_and_lifecycle(self) -> None:
        risk = Probe(lambda index, texts: judgement(index))
        lifecycle = Probe(lambda index, texts: verdict(index))

        result = self.analyze(risk_assessor=risk, lifecycle_assessor=lifecycle, llm_concurrency=8)

        self.assertEqual(len(result.events), EVENT_COUNT)
        self.assertGreater(risk.peak, 1, "service 没有把并发度传给风险研判")
        self.assertGreater(lifecycle.peak, 1, "service 没有把并发度传给状态研判")
        self.assertEqual(result.run_log.extra["risk_mode"], "llm")
        self.assertEqual(result.run_log.extra["lifecycle_mode"], "llm")

    def test_service_concurrency_one_is_serial(self) -> None:
        risk = Probe(lambda index, texts: judgement(index))

        self.analyze(risk_assessor=risk, llm_concurrency=1)

        self.assertEqual(risk.peak, 1)

    def test_service_result_is_identical_serial_vs_parallel(self) -> None:
        """整条流水线的产物逐位一致——**包括 priority_score 和它决定的事件排序**。

        `now` 必须钉死。recency_weight = 0.5 ** (age / half_life) 是相对"现在"算的，而两个臂
        是先后跑的：不注入 now，priority_score 会在小数点第 6 位上不同——那是**时间流逝**，
        不是并发（实测中真的撞上过）。核心早就为此把 now 做成可注入的，消融脚本同样注入。
        """

        def snapshot(result) -> list[tuple]:
            return [
                (
                    event.event_key,
                    event.title,
                    event.risk_level,
                    event.risk_score,
                    tuple(event.risk_reasons),
                    tuple(event.concerns),
                    event.agent_summary,
                    event.lifecycle,
                    event.lifecycle_reason,
                    event.recency_weight,
                    event.priority_score,  # 排序键：并行一旦串位，事件顺序就会变
                    event.heat_score,
                    event.source_count,
                )
                for event in result.events
            ]

        def run(concurrency: int):
            return self.analyze(
                risk_assessor=Probe(lambda index, texts: judgement(index)),
                lifecycle_assessor=Probe(lambda index, texts: verdict(index)),
                llm_concurrency=concurrency,
                now=NOW,
            )

        serial, parallel = run(1), run(8)

        self.assertEqual(snapshot(parallel), snapshot(serial))
        self.assertEqual(parallel.warnings, serial.warnings)
        self.assertEqual(parallel.run_log.extra["risk_assessed"], serial.run_log.extra["risk_assessed"])
        self.assertEqual(
            parallel.run_log.extra["lifecycle_assessed"], serial.run_log.extra["lifecycle_assessed"]
        )


class AdapterWiringTest(unittest.TestCase):
    """部署侧接线：`.env` 的 EVENT_LLM_CONCURRENCY 必须真的走到核心包。

    不碰数据库：persist=False 时 `run_public_opinion_analysis` 只通过被打桩的
    count/query 两个函数接触 db，其余全是纯函数。
    """

    def test_llm_config_exposes_event_llm_concurrency(self) -> None:
        from backend.services import llm_config

        self.assertGreaterEqual(llm_config.EVENT_LLM_CONCURRENCY, 1)

    def rows(self) -> list[dict[str, Any]]:
        # 每个话题两条帖子：min_cluster_size=2（.env 默认）也照样成事件。
        return [
            {
                "id": index * 2 + seq + 1,
                "processed_post_id": index * 2 + seq + 1,
                "note_id": f"xhs:{index:02d}-{seq}",
                "platform": "xhs",
                "title": f"事件{index:02d}",
                "content": f"事件{index:02d} 的第 {seq} 条正文",
                "publish_date": "2026-03-24",
            }
            for index in range(EVENT_COUNT)
            for seq in range(2)
        ]

    def test_configured_concurrency_reaches_the_assessors(self) -> None:
        from backend.services import public_opinion_adapter as adapter

        rows = self.rows()
        risk = Probe(lambda index, texts: judgement(index))

        def embedder(texts: list[str]) -> list[list[float]]:
            # 同一个事件的两条帖子共用一个向量，不同事件正交。
            return [
                [1.0 if column == index // 2 else 0.0 for column in range(EVENT_COUNT)]
                for index in range(len(texts))
            ]

        with (
            mock.patch.object(adapter, "count_agent_rows", return_value=len(rows)),
            mock.patch.object(adapter, "query_agent_rows", return_value=rows),
            mock.patch.object(adapter, "get_embedder", return_value=embedder),
            mock.patch.object(adapter, "get_sentiment_classifier", return_value=None),
            mock.patch.object(adapter, "get_cluster_refiner", return_value=None),
            mock.patch.object(adapter, "get_risk_assessor", return_value=risk),
            mock.patch.object(adapter, "get_lifecycle_assessor", return_value=None),
            mock.patch.object(adapter, "MEMORY_SNAPSHOT_PATH", "/nonexistent/memory.json"),
            mock.patch.object(adapter, "EVENT_MIN_CLUSTER_SIZE", 2),
            mock.patch.object(adapter, "EVENT_LLM_CONCURRENCY", 8),
        ):
            result = adapter.run_public_opinion_analysis(None, limit=0, persist=False)

        self.assertEqual(result["event_count"], EVENT_COUNT)
        self.assertGreater(risk.peak, 1, "adapter 没有把 EVENT_LLM_CONCURRENCY 传下去")
        self.assertLessEqual(risk.peak, 8)

    def test_configured_concurrency_of_one_stays_serial(self) -> None:
        from backend.services import public_opinion_adapter as adapter

        rows = self.rows()
        risk = Probe(lambda index, texts: judgement(index))

        def embedder(texts: list[str]) -> list[list[float]]:
            return [
                [1.0 if column == index // 2 else 0.0 for column in range(EVENT_COUNT)]
                for index in range(len(texts))
            ]

        with (
            mock.patch.object(adapter, "count_agent_rows", return_value=len(rows)),
            mock.patch.object(adapter, "query_agent_rows", return_value=rows),
            mock.patch.object(adapter, "get_embedder", return_value=embedder),
            mock.patch.object(adapter, "get_sentiment_classifier", return_value=None),
            mock.patch.object(adapter, "get_cluster_refiner", return_value=None),
            mock.patch.object(adapter, "get_risk_assessor", return_value=risk),
            mock.patch.object(adapter, "get_lifecycle_assessor", return_value=None),
            mock.patch.object(adapter, "MEMORY_SNAPSHOT_PATH", "/nonexistent/memory.json"),
            mock.patch.object(adapter, "EVENT_MIN_CLUSTER_SIZE", 2),
            mock.patch.object(adapter, "EVENT_LLM_CONCURRENCY", 1),
        ):
            adapter.run_public_opinion_analysis(None, limit=0, persist=False)

        self.assertEqual(risk.peak, 1)


if __name__ == "__main__":
    unittest.main()
