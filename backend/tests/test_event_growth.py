"""「持续发酵」是**测量**，不是**语气**：escalating 由发帖速率算出来，不由 LLM 猜出来。

**缺陷**（上一轮消融实测）：`escalating` 在 28 个事件上**一次都没触发**（0/28）。诚实的诊断是：
模型读的是一份**冻结的 fixture**，它看不见"新帖还在不在增加"，于是只能从**措辞和语气**里
嗅"发酵感"——`escalating` / `ongoing` 的边界事实上是由**文风**决定的。

**问 LLM「这件事还在扩大吗」和问它「这条帖子有多火」是同一类错误**：这是一个**测量**，
而每一条成员帖的 `publish_time` 就摆在那里。它是减法和除法，和时效衰减（17d5ef2）完全一样。

项目四个 commit 一以贯之的分工，这次把它补齐：

    测量 -> 算术        判断 -> LLM
    ---------------     -----------------
    热度（互动量）       严重性（多严重）
    年龄（多老）         悬而未决（还有没有待办动作）
    **还在不在增长**     非事件（本来就不需要处置）

于是问题一分为二：

- **LLM 只答判断**：「有没有一件悬而未决的事？」-> resolved / ongoing / not_applicable。
  `escalating` **被移出模型的枚举**（`LLM_LIFECYCLES`）——它不再是一个模型判词。
- **算术只答测量**：「这件事还在长吗？」-> `growth_signal(member_times, now)`。
- **合成**：`escalating` = `ongoing` **且** 算术判定仍在增长。

`resolved` / `not_applicable` **永远不会**被算术提升成 escalating：「已了结」和「本来就不是事」
是判断，算术推翻不了它们（那正是 not_applicable 权重分析里堵死的那个后门）。

零网络、零数据库：assessor 全是注入的假货，`now` 全是注入的。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

from backend.agent.public_opinion_core import AnalyzeRequest, PublicOpinionAgentService
from backend.agent.public_opinion_core.clustering import build_event_from_group, sort_events
from backend.agent.public_opinion_core.llm_lifecycle import (
    LLM_LIFECYCLES,
    VALID_LIFECYCLES,
    assess_events_lifecycle,
)
from backend.agent.public_opinion_core.payload_builder import build_public_event_payloads
from backend.agent.public_opinion_core.recency import (
    DEFAULT_GROWTH_MIN_NOTES,
    annotate_events_with_recency,
    effective_lifecycle,
    growth_signal,
    lifecycle_weight,
    member_times_from_payload,
)
from backend.agent.public_opinion_core.schemas import AnalyzeRequest as _Req  # noqa: F401
from backend.agent.public_opinion_core.schemas import AnalyzeResult, OpinionNote
from backend.services import event_lifecycle
from backend.services.llm_client import LlmCallResult

NOW = datetime(2026, 7, 12, 12, 0, 0)
WINDOW = 21.0  # = 时效半衰期。窗口不是新常数，见 recency.growth_signal 的注释。


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def times(*days: float) -> list[str]:
    return [ago(day) for day in days]


def note(note_id: str, title: str, age_days: float) -> OpinionNote:
    return OpinionNote(
        note_id=note_id, title=title, content=title, publish_time=ago(age_days)
    )


class GrowthSignalTest(unittest.TestCase):
    """算术判据本身：它读的是成员帖的 `publish_time` 分布，相对于**注入的** now。

    判据（两条，缺一不可）：
      1. 窗口内（近 21 天 = 一个半衰期）**至少 2 条**成员帖；
      2. 窗口内的发帖速率 **>=** 事件自己的历史平均速率。
    """

    def test_recent_posts_at_a_rising_rate_are_growth(self) -> None:
        signal = growth_signal(times(2, 5, 9, 40), NOW, window_days=WINDOW)

        self.assertTrue(signal["growing"])
        self.assertEqual(signal["recent_notes"], 3)
        self.assertEqual(signal["total_notes"], 4)

    def test_a_single_recent_post_is_not_growth(self) -> None:
        """一条掉队的新帖不是"还在长"——这正是 `event_reference_time` 拒绝 `latest` 口径的
        那个失败模式：一次转发、一条蹭话题的帖子，不许把整个事件重新贴上「持续发酵」。

        两条才构成一个**速率**；一条只是一个点。
        """

        signal = growth_signal(times(3, 60, 70, 80), NOW, window_days=WINDOW)

        self.assertEqual(signal["recent_notes"], 1)
        self.assertFalse(signal["growing"])
        self.assertEqual(DEFAULT_GROWTH_MIN_NOTES, 2)

    def test_an_old_dead_event_is_not_growing(self) -> None:
        signal = growth_signal(times(120, 130, 140), NOW, window_days=WINDOW)

        self.assertEqual(signal["recent_notes"], 0)
        self.assertFalse(signal["growing"])

    def test_a_big_archive_with_a_trickle_is_not_growth(self) -> None:
        """速率判据的作用：一个两年里攒了 100 帖的老话题，最近 3 周只来了 2 帖——

        它**没有在加速**（过去 ~0.14 帖/天 vs 近期 0.095 帖/天），只是还在滴水。
        光看"窗口内有 2 条"会把它误判成发酵；比速率不会。
        """

        stamps = times(*[5, 10] + [30 + index * 7 for index in range(98)])
        signal = growth_signal(stamps, NOW, window_days=WINDOW)

        self.assertEqual(signal["recent_notes"], 2)
        self.assertGreater(signal["baseline_rate"], signal["recent_rate"])
        self.assertFalse(signal["growing"])

    def test_a_brand_new_event_is_growing(self) -> None:
        """今天刚爆出来的事（2 帖，都在窗口内）：跨度几乎为 0，不许因此把历史速率算成无穷大。"""

        signal = growth_signal(times(0.5, 1.0), NOW, window_days=WINDOW)

        self.assertTrue(signal["growing"])

    def test_no_timestamps_is_not_growth(self) -> None:
        """"不知道它在不在长" ≠ "它在长"：没有证据不许抬高紧急度（同 recency 对未知年龄的口径）。"""

        self.assertFalse(growth_signal([], NOW)["growing"])
        self.assertFalse(growth_signal(["", "not a date"], NOW)["growing"])

    def test_signal_carries_the_evidence_not_just_a_verdict(self) -> None:
        """徽标背后必须有证据：管理员要看到"近 21 天 3/4 帖"，而不是一句"相信我"。"""

        signal = growth_signal(times(2, 5, 9, 40), NOW, window_days=WINDOW)

        self.assertEqual(signal["window_days"], WINDOW)
        self.assertAlmostEqual(signal["recent_share"], 0.75, places=6)
        self.assertAlmostEqual(signal["recent_rate"], 3 / WINDOW, places=9)

    def test_now_is_injected_never_read_from_the_clock(self) -> None:
        """同一批时间戳 + 不同的 now = 不同的结论，而且**只由参数决定**（消融要可复现）。"""

        stamps = times(2, 5, 9, 40)
        later = NOW + timedelta(days=60)

        self.assertTrue(growth_signal(stamps, NOW, window_days=WINDOW)["growing"])
        self.assertFalse(growth_signal(stamps, later, window_days=WINDOW)["growing"])


class CompositionTest(unittest.TestCase):
    """合成：escalating = ongoing ∧ 还在长。判断在前，算术在后，算术推翻不了判断。"""

    def test_ongoing_plus_growth_is_escalating(self) -> None:
        self.assertEqual(effective_lifecycle("ongoing", growing=True), "escalating")

    def test_ongoing_without_growth_stays_ongoing(self) -> None:
        self.assertEqual(effective_lifecycle("ongoing", growing=False), "ongoing")

    def test_resolved_is_never_promoted_by_arithmetic(self) -> None:
        """**已了结**的事件哪怕今天又来了 10 条帖子，也不会变成「持续发酵」。

        "这件事结束了"是一个判断（火灭了、通报发了、立案了），成员帖的时间分布推翻不了它。
        允许算术在这里翻盘，就等于开了一个后门：任何一个被转发到今天的旧事件都能自称在发酵。
        """

        self.assertEqual(effective_lifecycle("resolved", growing=True), "resolved")

    def test_not_applicable_is_never_promoted_by_arithmetic(self) -> None:
        """**非事件**（咨询/攻略/分享）今天又新增了 5 条帖子——它还是非事件。

        「校园与宿舍展示」这类内容在语料里恰恰是**最近发帖最多**的；如果算术能提升它，
        看板首屏就会挂出「持续发酵」的宿舍照片贴。这正是 not_applicable 那一档要防的事。
        """

        self.assertEqual(effective_lifecycle("not_applicable", growing=True), "not_applicable")

    def test_unassessed_is_never_promoted_by_arithmetic(self) -> None:
        """LLM 没判成（超时/幻觉）：因子必须留在恒等的 1.0。

        算术不知道"有没有待办动作"，它只知道"帖子还在来"。没有判断就没有 escalating——
        否则一次 LLM 超时就能让一个咨询贴凭"最近很多人问"冲上首屏。
        """

        self.assertEqual(effective_lifecycle("", growing=True), "")
        self.assertEqual(lifecycle_weight(effective_lifecycle("", growing=True)), 1.0)

    def test_composition_is_idempotent(self) -> None:
        """已经合成过的 escalating 再合成一次：还在长 -> 仍是 escalating；不长了 -> **退回 ongoing**。

        看板因此是**自我纠正**的：一个上周还在发酵的事件，这周没人再发帖，它自己就降回「悬而未决」。
        （这也是为什么 escalating **不落库**：它是 now 的函数，冻进数据库第二天就是错的。）
        """

        self.assertEqual(effective_lifecycle("escalating", growing=True), "escalating")
        self.assertEqual(effective_lifecycle("escalating", growing=False), "ongoing")

    def test_escalating_keeps_its_weight(self) -> None:
        self.assertEqual(lifecycle_weight("escalating"), 4.0)
        self.assertEqual(set(VALID_LIFECYCLES), set(LLM_LIFECYCLES) | {"escalating"})


class LlmEnumTest(unittest.TestCase):
    """`escalating` 被移出模型的枚举：它不再是一个模型判词。"""

    def test_the_model_may_only_answer_the_judgement(self) -> None:
        self.assertEqual(set(LLM_LIFECYCLES), {"resolved", "ongoing", "not_applicable"})
        self.assertNotIn("escalating", LLM_LIFECYCLES)

    def test_a_model_that_still_returns_escalating_is_demoted_to_ongoing(self) -> None:
        """模型仍然吐 escalating 时**不静默接受**——但也不整份作废。

        `escalating` 在语义上蕴含 `ongoing`（"没有结论**而且**还在扩大" => "没有结论"）。
        模型对**前半句**依然是权威的（它读了帖子），对**后半句**（还在不在扩大）已经不是了。
        所以：保留它答得了的那一半（判成 ongoing、留下理由），把"还在不在长"交还给算术，
        并且**留痕**（warning -> agent_run_logs）——降级必须看得见。

        如果算术同意它在长，它照样会被重新提升回 escalating；如果不同意，模型的语气就
        到此为止。整份作废（退回未研判）反而更糟：那会把一条**有效的判断**一起扔掉。
        """

        event = build_event_from_group("sem:x", "中大杰青实名举报", "semantic", [note("a", "举报", 2)])
        warnings: list[str] = []

        assessed = assess_events_lifecycle(
            [event],
            lambda title, texts: {"lifecycle": "escalating", "lifecycle_reason": "讨论仍在扩大"},
            warnings=warnings,
        )

        self.assertEqual(assessed, 1)
        self.assertEqual(event.lifecycle_judgement, "ongoing")
        self.assertEqual(event.lifecycle_reason, "讨论仍在扩大")
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("escalating", warnings[0])

    def test_the_prompt_no_longer_offers_escalating(self) -> None:
        payload = {"lifecycle": "ongoing", "lifecycle_reason": "校方未回应"}
        with mock.patch.object(
            event_lifecycle, "call_llm", return_value=LlmCallResult(content=json.dumps(payload))
        ) as call:
            event_lifecycle.assess_event_lifecycle("中大杰青实名举报", ["举报两个月了还没结论"])

        prompt = "\n".join(message["content"] for message in call.call_args.args[0])
        self.assertNotIn("escalating", prompt)
        for state in LLM_LIFECYCLES:
            self.assertIn(state, prompt)


class AnnotationTest(unittest.TestCase):
    """`annotate_events_with_recency` 是合成发生的地方——它已经拿着注入的 `now`。"""

    def event_with(self, judgement: str, *ages: float):
        notes = [note(f"n{index}", f"帖子{index}", age) for index, age in enumerate(ages)]
        event = build_event_from_group("sem:e", "中大杰青实名举报", "semantic", notes)
        event.risk_level, event.risk_score = "high", 90.0
        event.lifecycle = event.lifecycle_judgement = judgement
        event.lifecycle_reason = "校方未给出调查结论"
        return event

    def test_a_growing_unresolved_event_becomes_escalating(self) -> None:
        event = self.event_with("ongoing", 2, 5, 9, 40)

        annotate_events_with_recency([event], now=NOW, half_life_days=WINDOW)

        self.assertEqual(event.lifecycle, "escalating")
        self.assertEqual(event.lifecycle_judgement, "ongoing")  # 模型答的那一半，原样留着
        self.assertTrue(event.growth["growing"])
        self.assertEqual(event.growth["recent_notes"], 3)
        self.assertAlmostEqual(
            event.priority_score, 9.0 * event.recency_weight * 4.0, places=9
        )

    def test_a_quiet_unresolved_event_stays_ongoing(self) -> None:
        event = self.event_with("ongoing", 60, 70, 80)

        annotate_events_with_recency([event], now=NOW, half_life_days=WINDOW)

        self.assertEqual(event.lifecycle, "ongoing")
        self.assertFalse(event.growth["growing"])
        self.assertAlmostEqual(
            event.priority_score, 9.0 * event.recency_weight * 2.0, places=9
        )

    def test_a_busy_non_event_is_not_promoted(self) -> None:
        """语料里发帖最勤的恰恰是宿舍/攻略这类**非事件**——算术不许把它们抬上首屏。"""

        event = self.event_with("not_applicable", 1, 3, 6, 8)

        annotate_events_with_recency([event], now=NOW, half_life_days=WINDOW)

        self.assertTrue(event.growth["growing"])  # 它确实在长
        self.assertEqual(event.lifecycle, "not_applicable")  # 但它不是一件事
        self.assertEqual(lifecycle_weight(event.lifecycle), 0.5)

    def test_growth_does_not_touch_severity_heat_or_recency(self) -> None:
        event = self.event_with("ongoing", 2, 5, 9, 40)
        before = (event.risk_level, event.risk_score, event.heat_score, event.heat_rank)

        annotate_events_with_recency([event], now=NOW, half_life_days=WINDOW)

        self.assertEqual(
            (event.risk_level, event.risk_score, event.heat_score, event.heat_rank), before
        )

    def test_escalating_outranks_a_merely_ongoing_event_of_the_same_age(self) -> None:
        growing = self.event_with("ongoing", 2, 5, 9, 40)
        quiet = self.event_with("ongoing", 2, 5, 9, 40)
        growing.event_key, quiet.event_key = "growing", "quiet"
        quiet.member_times = times(40, 41, 42, 43)  # 同龄，但没有新帖

        ordered = sort_events(
            annotate_events_with_recency([quiet, growing], now=NOW, half_life_days=WINDOW)
        )

        self.assertEqual([event.event_key for event in ordered], ["growing", "quiet"])


ROWS = [
    {
        "id": index,
        "processed_post_id": index,
        "note_id": f"ks:{index}",
        "platform": "ks",
        "title": title,
        "content": title,
        "publish_time": ago(age),
    }
    for index, (title, age) in enumerate(
        [
            ("中大杰青被实名举报学术不端，校方称已收到材料", 30.0),
            ("举报两个月了，中大还没有给出调查结论", 9.0),
            ("中大杰青举报又添新证据，更多校友联署要求公开调查", 3.0),
        ],
        start=1,
    )
]


class ServiceWiringTest(unittest.TestCase):
    """端到端：注入 assessor + now -> 事件真的挂上「持续发酵」，run_log 里记下算术的证据。"""

    def run_service(self, judgement: str, now: datetime = NOW):
        return PublicOpinionAgentService().analyze_from_rows(
            ROWS,
            AnalyzeRequest(limit=10),
            min_cluster_size=2,
            lifecycle_assessor=lambda title, texts: {
                "lifecycle": judgement,
                "lifecycle_reason": "校方未给出调查结论",
            },
            now=now,
            recency_half_life_days=WINDOW,
        )

    def test_the_criterion_fires_end_to_end(self) -> None:
        """**这就是"给我看它真的会亮"的那个测试**：一个 LLM 判 ongoing、且近 21 天有 2 条新帖的
        事件，在整条流水线跑完之后，`lifecycle` 必须是 `escalating`。"""

        result = self.run_service("ongoing")
        event = result.events[0]

        self.assertEqual(event.lifecycle, "escalating")
        self.assertEqual(event.lifecycle_judgement, "ongoing")
        self.assertEqual(event.growth["recent_notes"], 2)
        self.assertEqual(result.run_log.extra["lifecycle_counts"]["escalating"], 1)
        self.assertEqual(result.run_log.extra["growth_window_days"], WINDOW)
        self.assertEqual(result.run_log.extra["growing_events"], 1)

    def test_the_same_events_stop_escalating_when_now_moves_on(self) -> None:
        """同一批帖子，把 `now` 往后推 60 天：新帖不再新，事件自己降回「悬而未决」。

        排序因此是**自我纠正**的，而不是靠一次跑批的快照永远钉死。
        """

        result = self.run_service("ongoing", now=NOW + timedelta(days=60))

        self.assertEqual(result.events[0].lifecycle, "ongoing")
        self.assertEqual(result.run_log.extra["growing_events"], 0)

    def test_a_resolved_event_with_fresh_posts_is_not_escalating(self) -> None:
        result = self.run_service("resolved")

        self.assertEqual(result.events[0].lifecycle, "resolved")
        self.assertTrue(result.events[0].growth["growing"])  # 算术看见了新帖
        self.assertEqual(result.run_log.extra["lifecycle_counts"].get("escalating", 0), 0)

    def test_without_the_llm_nothing_escalates(self) -> None:
        """LLM 关掉：没有判断 -> 没有 escalating -> 因子恒等 1.0（逐位退化回改造前）。"""

        result = PublicOpinionAgentService().analyze_from_rows(
            ROWS,
            AnalyzeRequest(limit=10),
            min_cluster_size=2,
            lifecycle_assessor=None,
            now=NOW,
            recency_half_life_days=WINDOW,
        )

        self.assertTrue(result.events)
        for event in result.events:
            self.assertEqual(event.lifecycle, "")
            self.assertEqual(lifecycle_weight(event.lifecycle), 1.0)


class PayloadTest(unittest.TestCase):
    """落库口径：**判断落库，测量不落库**。

    `lifecycle_judgement`（LLM 答的"有没有待办动作"）是对内容的判断，落库。
    `member_times`（成员帖的发布时间）是事实，落库。
    而"还在不在长"是 `now` 的函数——**冻进数据库第二天就是错的**（同 age_days / recency_weight），
    所以它在读侧现算。
    """

    def payload_of(self, event) -> dict:
        result = AnalyzeResult(request=AnalyzeRequest(), events=[event], run_log=None)  # type: ignore[arg-type]
        return build_public_event_payloads(result)[0]

    def growing_event(self):
        notes = [note(f"n{index}", f"帖子{index}", age) for index, age in enumerate([2, 5, 9, 40])]
        event = build_event_from_group("sem:e", "中大杰青实名举报", "semantic", notes)
        event.risk_level, event.risk_score = "high", 90.0
        event.lifecycle = event.lifecycle_judgement = "ongoing"
        event.lifecycle_reason = "举报两月未见调查结论"
        annotate_events_with_recency([event], now=NOW, half_life_days=WINDOW)
        return event

    def test_member_times_and_judgement_are_persisted(self) -> None:
        date_range = json.loads(self.payload_of(self.growing_event())["date_range_json"])

        self.assertEqual(date_range["lifecycle_judgement"], "ongoing")
        self.assertEqual(len(date_range["member_times"]), 4)
        self.assertEqual(member_times_from_payload(json.dumps(date_range)), date_range["member_times"])

    def test_legacy_rows_without_member_times_read_back_empty(self) -> None:
        self.assertEqual(member_times_from_payload(""), [])
        self.assertEqual(member_times_from_payload('{"event_time":"2026-03-29T10:00:00"}'), [])
        self.assertEqual(member_times_from_payload("not json"), [])


if __name__ == "__main__":
    unittest.main()
