"""事件状态研判（生命周期）：**悬而未决的事不该随时间沉底**。

时效衰减（17d5ef2）只看年龄：同样 3 个月的两个事件被一视同仁地打折。但——

- 「东校区宿舍火情」：火已扑灭、校方已通报、无人员伤亡、调查已立案。**事情结束了**，
  严重性是历史事实，学校已经不需要再对它做动作。
- 「中大杰青实名举报」：调查有结论吗？没有结论就不是历史，是**一个还开着的口子**。

「已了结」还是「悬而未决」是对**内容**的判断，不是时间的函数：时间戳答不了，词表也答不了，
读一遍帖子的模型能答。这是时间这根轴上唯一该上 LLM 的地方——衰减本身是算术，一个字节都不许动。

**第四根正交轴**（前三根：严重性 risk_* / 流行度 heat_* / 时效性 recency_weight）：

    priority = severity_weight(risk_level) × recency_weight × lifecycle_weight(lifecycle)

`lifecycle_weight` = {escalating: 4, ongoing: 2, resolved: 0.5}，未研判 = 1.0（**恒等**：
LLM 不可用时逐位退化回改造前的排序）。取 2 的幂是为了能用半衰期解释：×2 = 「当作年轻了
一个半衰期（21 天）」，×0.5 = 「当作老了一个半衰期」。

零网络、零数据库：assessor 全是注入的假货。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest import mock

from backend.agent.public_opinion_core import AnalyzeRequest, PublicOpinionAgentService
from backend.agent.public_opinion_core.clustering import build_event_from_group, sort_events
from backend.agent.public_opinion_core.llm_lifecycle import (
    VALID_LIFECYCLES,
    assess_events_lifecycle,
)
from backend.agent.public_opinion_core.payload_builder import build_public_event_payloads
from backend.agent.public_opinion_core.recency import (
    LIFECYCLE_WEIGHTS,
    annotate_events_with_recency,
    lifecycle_from_payload,
    lifecycle_weight,
    priority_score,
    recency_weight,
    severity_weight,
)
from backend.agent.public_opinion_core.schemas import AnalyzeResult, OpinionNote
from backend.services import event_lifecycle
from backend.services.llm_client import LlmCallResult

NOW = datetime(2026, 7, 12, 12, 0, 0)


def note(note_id: str, title: str, **kwargs) -> OpinionNote:
    return OpinionNote(note_id=note_id, title=title, content=kwargs.pop("content", title), **kwargs)


# 火情：已通报、无伤亡、已立案 —— 严重（high/95），但**已了结**。
FIRE_NOTES = [
    note("ks:1", "中山大学东校区宿舍发生火情，现场楼道浓烟滚滚", publish_time="2026-03-28 10:00:00"),
    note("ks:2", "中山大学宿舍起火 校方通报：明火已扑灭，无人员伤亡", publish_time="2026-03-29 10:00:00"),
    note("ks:3", "东校区宿舍火情调查已立案，后勤发布整改通知", publish_time="2026-03-30 10:00:00"),
]

# 实名举报：调查没有结论 —— **悬而未决**。
REPORT_NOTES = [
    note("xhs:1", "中大杰青被实名举报学术不端，校方称已收到材料", publish_time="2026-05-08 10:00:00"),
    note("xhs:2", "举报两个月了，中大还没有给出调查结论", publish_time="2026-05-10 10:00:00"),
]

# 咨询：**这根本不是一件要学校处置的事**（问问题，不是提诉求）——既不是悬而未决，也不是已了结。
QUESTION_NOTES = [
    note("xhs:9", "请问中大图书馆对校外人员开放吗？需要预约吗", publish_time="2026-05-09 10:00:00"),
    note("xhs:10", "中大南校区可以随便参观吗，食堂能不能刷现金", publish_time="2026-05-10 10:00:00"),
]


def fire_event():
    event = build_event_from_group("sem:fire", "东校区宿舍火情", "semantic", list(FIRE_NOTES))
    event.risk_level, event.risk_score = "high", 95.0
    return event


def report_event():
    event = build_event_from_group("sem:report", "中大杰青实名举报", "semantic", list(REPORT_NOTES))
    event.risk_level, event.risk_score = "high", 90.0
    return event


def question_event():
    event = build_event_from_group(
        "sem:ask", "中大图书馆对外开放咨询", "semantic", list(QUESTION_NOTES)
    )
    event.risk_level, event.risk_score = "low", 10.0
    return event


def verdict(**overrides) -> dict:
    payload = {"lifecycle": "ongoing", "lifecycle_reason": "校方未给出调查结论，诉求仍未回应"}
    payload.update(overrides)
    return payload


class LifecycleWeightTest(unittest.TestCase):
    """因子的形状与量级：纯算术，可用半衰期解释。"""

    def test_states_are_exactly_four(self) -> None:
        """第四个状态 `not_applicable`：**这压根不是一件要学校处置的事**（咨询/攻略/分享）。

        原本只有三档，而三档全都预设了"存在一件待处置的事"——于是「图书馆对校外开放吗」这种
        **提问**只能被塞进 ongoing（"未见校方结论"），看板上挂出「悬而未决」。那是句假话。
        """

        self.assertEqual(
            set(VALID_LIFECYCLES), {"resolved", "ongoing", "escalating", "not_applicable"}
        )

    def test_not_applicable_does_not_compete_with_incidents(self) -> None:
        """无诉求的内容不该抗衰减：它不急（≠ ongoing 的 ×2），但也不是"处置完了"的事。"""

        self.assertEqual(lifecycle_weight("not_applicable"), 0.5)
        self.assertLess(lifecycle_weight("not_applicable"), lifecycle_weight("ongoing"))
        self.assertLess(lifecycle_weight("not_applicable"), 1.0)

    def test_unassessed_event_is_identity(self) -> None:
        """未研判（LLM 关掉/失败）= 1.0：排序逐位退化回改造前，这是降级保证的基石。"""

        self.assertEqual(lifecycle_weight(""), 1.0)
        self.assertEqual(lifecycle_weight(None), 1.0)

    def test_invented_state_is_identity_not_a_boost(self) -> None:
        self.assertEqual(lifecycle_weight("critical"), 1.0)
        self.assertEqual(lifecycle_weight("持续发酵"), 1.0)

    def test_unresolved_resists_decay_and_resolved_ages_faster(self) -> None:
        self.assertEqual(lifecycle_weight("escalating"), 4.0)
        self.assertEqual(lifecycle_weight("ongoing"), 2.0)
        self.assertEqual(lifecycle_weight("resolved"), 0.5)
        self.assertEqual(lifecycle_weight(" ONGOING "), 2.0)

    def test_factors_are_powers_of_two_so_they_read_as_half_lives(self) -> None:
        """×2 = 当作年轻一个半衰期（21 天）；×0.5 = 当作老一个半衰期。

        等价性：0.5 ** ((age - 21) / 21) == 2 × 0.5 ** (age / 21)。
        """

        younger = recency_weight(64.0 - 21.0, half_life_days=21.0)
        boosted = LIFECYCLE_WEIGHTS["ongoing"] * recency_weight(64.0, half_life_days=21.0)
        self.assertAlmostEqual(younger, boosted, places=9)

    def test_lifecycle_never_overturns_high_vs_low_at_the_same_age(self) -> None:
        """量级上限：整根轴的动态范围 8×（0.5→4）< 严重性的 9×（low→high）。

        「持续发酵的低风险」永远压不过「已了结的高风险」——生命周期是第四根轴，
        不是一个可以把严重性推翻的后门。
        """

        self.assertLess(
            priority_score("low", 1.0, "escalating"), priority_score("high", 1.0, "resolved")
        )

    def test_no_state_lets_lifecycle_overturn_severity(self) -> None:
        """把上一条推广到**全部四档**：整根轴的动态范围必须 < 严重性的 9×（low→high）。

        这条不变量正是 `not_applicable` 的权重下界（>= 4/9）：一个被误判成「非事件」的**真事件**
        绝不能因此掉到一个低风险事件之下。2 的幂里唯一同时满足「< 1（不急）」和「>= 4/9
        （不许翻盘严重性）」的值就是 **0.5**。
        """

        for state in VALID_LIFECYCLES:
            with self.subTest(state=state):
                self.assertLess(
                    priority_score("low", 1.0, "escalating"), priority_score("high", 1.0, state)
                )

    def test_priority_multiplies_the_three_axes(self) -> None:
        self.assertAlmostEqual(
            priority_score("high", 0.125, "ongoing"),
            severity_weight("high") * 0.125 * lifecycle_weight("ongoing"),
            places=9,
        )

    def test_priority_without_lifecycle_is_the_old_two_axis_formula(self) -> None:
        self.assertAlmostEqual(
            priority_score("high", 0.125), severity_weight("high") * 0.125, places=9
        )


class AssessorAppliedTest(unittest.TestCase):
    def test_no_assessor_leaves_events_unassessed(self) -> None:
        event = fire_event()

        assessed = assess_events_lifecycle([event], None)

        self.assertEqual(assessed, 0)
        self.assertEqual(event.lifecycle, "")
        self.assertEqual(event.lifecycle_reason, "")
        self.assertNotIn("lifecycle_assessed_by", event.extra)

    def test_llm_verdict_is_recorded_with_its_reason(self) -> None:
        event = report_event()

        assessed = assess_events_lifecycle([event], lambda title, texts: verdict())

        self.assertEqual(assessed, 1)
        self.assertEqual(event.lifecycle, "ongoing")
        self.assertEqual(event.lifecycle_reason, "校方未给出调查结论，诉求仍未回应")
        self.assertEqual(event.extra["lifecycle_assessed_by"], "llm")

    def test_not_applicable_is_a_legitimate_verdict(self) -> None:
        """「这不是一件需要处置的事」是一个**合法的判断**，不是降级。"""

        event = question_event()

        assessed = assess_events_lifecycle(
            [event],
            lambda title, texts: verdict(
                lifecycle="not_applicable", lifecycle_reason="咨询开放政策，无待处置诉求"
            ),
        )

        self.assertEqual(assessed, 1)
        self.assertEqual(event.lifecycle, "not_applicable")
        self.assertEqual(event.lifecycle_reason, "咨询开放政策，无待处置诉求")
        self.assertEqual(event.extra["lifecycle_assessed_by"], "llm")
        self.assertEqual(lifecycle_weight(event.lifecycle), 0.5)

    def test_assessor_receives_title_and_member_texts(self) -> None:
        seen: list[tuple[str, list[str]]] = []

        def assessor(title: str, texts: list[str]) -> dict:
            seen.append((title, list(texts)))
            return verdict(lifecycle="resolved", lifecycle_reason="明火已扑灭并通报，无伤亡")

        assess_events_lifecycle([fire_event()], assessor)

        title, texts = seen[0]
        self.assertEqual(title, "东校区宿舍火情")
        self.assertEqual(len(texts), 3)
        self.assertTrue(any("扑灭" in text for text in texts), texts)

    def test_severity_heat_and_recency_are_untouched(self) -> None:
        """第四根轴：状态研判只写 lifecycle_*，别的字段一个字节都不许动。"""

        event = fire_event()
        before = (
            event.risk_level,
            event.risk_score,
            event.risk_reasons,
            event.heat_score,
            event.heat_rank,
            event.ranking_score,
            event.event_time,
            event.recency_weight,
        )

        assess_events_lifecycle(
            [event],
            lambda title, texts: verdict(
                risk_level="low", risk_score=1, heat_score=99999, recency_weight=1.0
            ),
        )

        self.assertEqual(
            (
                event.risk_level,
                event.risk_score,
                event.risk_reasons,
                event.heat_score,
                event.heat_rank,
                event.ranking_score,
                event.event_time,
                event.recency_weight,
            ),
            before,
        )


class DegradationTest(unittest.TestCase):
    """LLM 挂了/胡说了：该事件退回"没有状态"，其余事件不受影响，降级留痕。"""

    def assert_unassessed(self, assessor, expected_warning: str) -> None:
        event = fire_event()
        warnings: list[str] = []

        assessed = assess_events_lifecycle([event], assessor, warnings=warnings)

        self.assertEqual(assessed, 0)
        self.assertEqual(event.lifecycle, "")
        self.assertEqual(event.lifecycle_reason, "")
        self.assertNotIn("lifecycle_assessed_by", event.extra)
        # 没有状态 = 因子 1.0 = 改造前的行为（不是把它当成 resolved 沉底）。
        self.assertEqual(lifecycle_weight(event.lifecycle), 1.0)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(expected_warning, warnings[0])

    def test_assessor_raises(self) -> None:
        def boom(title, texts):
            raise TimeoutError("read timed out")

        self.assert_unassessed(boom, "unavailable")

    def test_assessor_returns_none(self) -> None:
        self.assert_unassessed(lambda title, texts: None, "unusable")

    def test_invented_state(self) -> None:
        self.assert_unassessed(lambda title, texts: verdict(lifecycle="dormant"), "unusable")

    def test_empty_reason(self) -> None:
        """无理由的状态不算研判：管理员必须看得到「凭什么这条 3 个月前的事还在前面」。"""

        self.assert_unassessed(lambda title, texts: verdict(lifecycle_reason="   "), "unusable")

    def test_reason_is_not_a_string(self) -> None:
        self.assert_unassessed(lambda title, texts: verdict(lifecycle_reason=["ongoing"]), "unusable")

    def test_not_a_mapping(self) -> None:
        self.assert_unassessed(lambda title, texts: ["ongoing"], "unusable")

    def test_one_bad_event_does_not_poison_the_others(self) -> None:
        fire, report = fire_event(), report_event()
        warnings: list[str] = []

        def assessor(title: str, texts: list[str]) -> dict:
            if "火情" in title:
                raise TimeoutError("read timed out")
            return verdict()

        assessed = assess_events_lifecycle([fire, report], assessor, warnings=warnings)

        self.assertEqual(assessed, 1)
        self.assertEqual(fire.lifecycle, "")
        self.assertEqual(report.lifecycle, "ongoing")
        self.assertEqual(len(warnings), 1)


class SortingTest(unittest.TestCase):
    """真实取舍：同龄同险的两个事件，悬而未决的那个必须排在已了结的前面。"""

    def annotate(self, events):
        annotate_events_with_recency(events, now=NOW, half_life_days=21.0)
        return events

    def test_unresolved_outranks_a_resolved_event_of_the_same_age(self) -> None:
        resolved, ongoing = fire_event(), fire_event()
        resolved.event_key, ongoing.event_key = "resolved", "ongoing"
        resolved.lifecycle, resolved.lifecycle_reason = "resolved", "已通报、无伤亡、已立案"
        ongoing.lifecycle, ongoing.lifecycle_reason = "ongoing", "校方未回应"

        ordered = sort_events(self.annotate([resolved, ongoing]))

        self.assertEqual([event.event_key for event in ordered], ["ongoing", "resolved"])

    def test_a_resolved_severe_event_still_ranks_above_an_old_low_risk_one(self) -> None:
        """已了结不等于删除：95 分的火情仍然被严重性抬着，不会掉到同龄低风险事件之下。"""

        fire = fire_event()
        fire.lifecycle = "resolved"
        chatter = build_event_from_group("sem:chat", "宿舍热水吐槽", "semantic", list(FIRE_NOTES))
        chatter.risk_level, chatter.risk_score = "low", 10.0
        chatter.lifecycle = "ongoing"

        ordered = sort_events(self.annotate([chatter, fire]))

        self.assertEqual(ordered[0].event_key, "sem:fire")

    def test_ongoing_two_month_old_event_outranks_a_resolved_older_severe_one(self) -> None:
        """线上现场：3.5 个月的已了结火情 vs 2.1 个月的悬而未决举报。"""

        fire, report = fire_event(), report_event()
        fire.lifecycle, report.lifecycle = "resolved", "ongoing"

        ordered = sort_events(self.annotate([fire, report]))

        self.assertEqual(ordered[0].event_key, "sem:report")

    def test_a_question_no_longer_rides_the_unresolved_boost(self) -> None:
        """缺陷现场：同龄的「图书馆对外开放咨询」曾被判 ongoing（×2），冒充"悬而未决"。

        判成 not_applicable 之后它拿到 ×0.5：一个咨询贴不再压过**同龄同险**的未研判事件，
        更不该压过真事件。
        """

        asked, unassessed = question_event(), question_event()
        asked.event_key, unassessed.event_key = "asked", "unassessed"
        asked.lifecycle, asked.lifecycle_reason = "not_applicable", "咨询开放政策，无待处置诉求"

        ordered = sort_events(self.annotate([asked, unassessed]))

        self.assertEqual([event.event_key for event in ordered], ["unassessed", "asked"])
        self.assertLess(asked.priority_score, unassessed.priority_score)

    def test_unassessed_events_sort_exactly_as_before(self) -> None:
        """全部未研判（LLM 关掉）：顺序与改造前逐位相同。"""

        fire, report = fire_event(), report_event()
        annotated = self.annotate([fire, report])
        expected = sorted(
            annotated,
            key=lambda e: (
                severity_weight(e.risk_level) * e.recency_weight,
                e.ranking_score,
                e.heat_rank,
                e.heat_score,
            ),
            reverse=True,
        )

        self.assertEqual(
            [e.event_key for e in sort_events(annotated)], [e.event_key for e in expected]
        )

    def test_annotate_materializes_priority_with_the_lifecycle_factor(self) -> None:
        event = report_event()
        event.lifecycle = "ongoing"

        annotate_events_with_recency([event], now=NOW, half_life_days=21.0)

        self.assertAlmostEqual(
            event.priority_score,
            severity_weight("high") * event.recency_weight * 2.0,
            places=9,
        )


class PayloadTest(unittest.TestCase):
    """状态必须落库并回到前端：管理员要看得见「为什么这条 3 个月前的事还在前面」。"""

    def payload_of(self, event) -> dict:
        result = AnalyzeResult(request=AnalyzeRequest(), events=[event], run_log=None)  # type: ignore[arg-type]
        return build_public_event_payloads(result)[0]

    def test_date_range_json_carries_lifecycle_and_reason(self) -> None:
        event = report_event()
        event.lifecycle, event.lifecycle_reason = "ongoing", "举报两个月未见调查结论"

        date_range = json.loads(self.payload_of(event)["date_range_json"])

        self.assertEqual(date_range["lifecycle"], "ongoing")
        self.assertEqual(date_range["lifecycle_reason"], "举报两个月未见调查结论")
        # 严重性照旧落库、没有被状态改写。
        self.assertEqual(self.payload_of(event)["risk_level"], "high")

    def test_lifecycle_from_payload_reads_it_back(self) -> None:
        event = report_event()
        event.lifecycle, event.lifecycle_reason = "ongoing", "举报两个月未见调查结论"

        lifecycle, reason = lifecycle_from_payload(self.payload_of(event)["date_range_json"])

        self.assertEqual(lifecycle, "ongoing")
        self.assertEqual(reason, "举报两个月未见调查结论")

    def test_legacy_rows_without_lifecycle_read_back_as_unassessed(self) -> None:
        self.assertEqual(lifecycle_from_payload(""), ("", ""))
        self.assertEqual(lifecycle_from_payload('{"event_time":"2026-03-29T10:00:00"}'), ("", ""))
        self.assertEqual(lifecycle_from_payload("not json"), ("", ""))

    def test_not_applicable_survives_the_round_trip(self) -> None:
        event = question_event()
        event.lifecycle, event.lifecycle_reason = "not_applicable", "咨询开放政策，无待处置诉求"

        lifecycle, reason = lifecycle_from_payload(self.payload_of(event)["date_range_json"])

        self.assertEqual(lifecycle, "not_applicable")
        self.assertEqual(reason, "咨询开放政策，无待处置诉求")

    def test_invented_state_in_the_database_is_ignored(self) -> None:
        """库里的脏值也不许变成一个因子：只认枚举里的四个值。

        脏值退回**未研判**（1.0），**不是** not_applicable —— 不知道是不是事件 ≠ 它不是事件。
        """

        lifecycle, _reason = lifecycle_from_payload('{"lifecycle":"dormant","lifecycle_reason":"x"}')
        self.assertEqual(lifecycle, "")
        self.assertEqual(lifecycle_weight(lifecycle), 1.0)


ROWS = [
    {
        "id": index,
        "processed_post_id": index,
        "note_id": note_obj.note_id,
        "platform": "ks",
        "title": note_obj.title,
        "content": note_obj.content,
        "publish_time": note_obj.publish_time,
    }
    for index, note_obj in enumerate(FIRE_NOTES + REPORT_NOTES, start=1)
]


class ServiceWiringTest(unittest.TestCase):
    """服务层编排：注入 assessor -> 事件带上状态、按新优先级重排、模式记进 run_log。"""

    def run_service(self, assessor):
        return PublicOpinionAgentService().analyze_from_rows(
            ROWS,
            AnalyzeRequest(limit=10),
            min_cluster_size=2,
            lifecycle_assessor=assessor,
            now=NOW,
            recency_half_life_days=21.0,
        )

    def test_without_assessor_no_lifecycle_and_mode_is_none(self) -> None:
        result = self.run_service(None)

        self.assertTrue(result.events)
        for event in result.events:
            self.assertEqual(event.lifecycle, "")
        self.assertEqual(result.run_log.extra["lifecycle_mode"], "none")
        self.assertEqual(result.run_log.extra["lifecycle_assessed"], 0)

    def test_assessor_annotates_events_and_reorders_them(self) -> None:
        def assessor(title: str, texts: list[str]) -> dict:
            if any("火" in text or "浓烟" in text for text in texts):
                return verdict(lifecycle="resolved", lifecycle_reason="明火已扑灭并通报，无人员伤亡")
            return verdict()

        result = self.run_service(assessor)
        by_lifecycle = {event.lifecycle for event in result.events}

        self.assertEqual(by_lifecycle, {"resolved", "ongoing"})
        self.assertEqual(result.events[0].lifecycle, "ongoing")  # 悬而未决的排在前面
        self.assertEqual(result.run_log.extra["lifecycle_mode"], "llm")
        self.assertEqual(result.run_log.extra["lifecycle_assessed"], 2)

    def test_total_failure_reports_none_and_warns(self) -> None:
        """一个事件都没判成：如实记成 none（不许假装 AI 上过），事件照出。"""

        def boom(title, texts):
            raise TimeoutError("read timed out")

        result = self.run_service(boom)

        self.assertTrue(result.events)
        self.assertEqual(result.run_log.extra["lifecycle_mode"], "none")
        self.assertEqual(result.run_log.extra["lifecycle_assessed"], 0)
        self.assertTrue(any("lifecycle" in w for w in result.warnings), result.warnings)
        self.assertTrue(any("lifecycle" in w for w in result.run_log.warnings))

    def test_partial_failure_still_reports_llm_mode_with_a_warning(self) -> None:
        def assessor(title: str, texts: list[str]):
            if any("火" in text for text in texts):
                raise TimeoutError("read timed out")
            return verdict()

        result = self.run_service(assessor)

        self.assertEqual(result.run_log.extra["lifecycle_mode"], "llm")
        self.assertEqual(result.run_log.extra["lifecycle_assessed"], 1)
        self.assertTrue(any("lifecycle" in w for w in result.warnings))

    def test_risk_and_heat_are_identical_with_and_without_the_lifecycle_pass(self) -> None:
        def facts(result):
            return {
                event.title: (
                    event.risk_level,
                    event.risk_score,
                    event.heat_score,
                    event.heat_rank,
                    event.recency_weight,
                )
                for event in result.events
            }

        without = facts(self.run_service(None))
        with_llm = facts(self.run_service(lambda title, texts: verdict()))

        self.assertEqual(without, with_llm)


class DeploymentAssessorTest(unittest.TestCase):
    """部署侧接线（backend/services/event_lifecycle.py）：唯一读 EVENT_LLM_* 并发请求的地方。

    零网络：call_llm 全程被换成假的。
    """

    def reply(self, payload: dict) -> LlmCallResult:
        return LlmCallResult(content=json.dumps(payload, ensure_ascii=False))

    def test_no_assessor_without_api_key(self) -> None:
        with mock.patch.object(event_lifecycle, "EVENT_LLM_API_KEY", ""):
            self.assertIsNone(event_lifecycle.get_lifecycle_assessor())

    def test_no_assessor_when_disabled(self) -> None:
        with (
            mock.patch.object(event_lifecycle, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_lifecycle, "EVENT_LIFECYCLE_ENABLED", False),
        ):
            self.assertIsNone(event_lifecycle.get_lifecycle_assessor())

    def test_assessor_available_when_configured(self) -> None:
        with (
            mock.patch.object(event_lifecycle, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_lifecycle, "EVENT_LIFECYCLE_ENABLED", True),
        ):
            self.assertIs(
                event_lifecycle.get_lifecycle_assessor(), event_lifecycle.assess_event_lifecycle
            )

    def test_parses_verdict_and_is_deterministic(self) -> None:
        payload = {"lifecycle": "resolved", "lifecycle_reason": "明火已扑灭，校方已通报，无伤亡"}
        with mock.patch.object(event_lifecycle, "call_llm", return_value=self.reply(payload)) as call:
            got = event_lifecycle.assess_event_lifecycle("东校区宿舍火情", ["宿舍起火，明火已扑灭"])

        self.assertEqual(got["lifecycle"], "resolved")
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)  # 可复现（+ call_llm 的 JSON 缓存）
        self.assertEqual(kwargs["model"], event_lifecycle.EVENT_LLM_MODEL)

    def test_prompt_frames_the_question_as_state_not_severity(self) -> None:
        payload = {"lifecycle": "ongoing", "lifecycle_reason": "校方未回应"}
        with mock.patch.object(event_lifecycle, "call_llm", return_value=self.reply(payload)) as call:
            event_lifecycle.assess_event_lifecycle("中大杰青实名举报", ["举报两个月了还没结论"])

        prompt = "\n".join(message["content"] for message in call.call_args.args[0])
        self.assertIn("校园", prompt)
        for state in VALID_LIFECYCLES:
            self.assertIn(state, prompt)
        self.assertIn("严重", prompt)  # 状态 ≠ 严重性：严重的事也可以已了结
        self.assertIn("热度", prompt)  # 状态 ≠ 流行度
        self.assertIn("<data>", prompt)  # 采集内容当数据、不当指令
        self.assertIn("中大杰青实名举报", prompt)
        self.assertIn("举报两个月了还没结论", prompt)

    def test_prompt_routes_non_incidents_to_not_applicable_not_to_an_ongoing_fallback(self) -> None:
        """缺陷的根：提示词里的兜底是「拿不准就 ongoing」，于是**提问贴**成了「悬而未决」。

        新的兜底不许再系统性地抬高紧急度：
        - 提示词必须给"没有待处置事项"的内容一个明确的归属（`not_applicable`，点名咨询/攻略/分享）；
        - 「看不出结论时一律判 ongoing」这条无差别兜底必须消失（它正是把提问贴塞进 ongoing 的那条规则）；
        - 「已处置完毕」（resolved）和「本来就不需要处置」（not_applicable）必须被讲成两件事。
        """

        payload = {"lifecycle": "not_applicable", "lifecycle_reason": "咨询开放政策，无待处置诉求"}
        with mock.patch.object(event_lifecycle, "call_llm", return_value=self.reply(payload)) as call:
            event_lifecycle.assess_event_lifecycle("中大图书馆对外开放咨询", ["图书馆对校外开放吗"])

        prompt = "\n".join(message["content"] for message in call.call_args.args[0])
        self.assertIn("not_applicable", prompt)
        self.assertIn("咨询", prompt)
        self.assertIn("分享", prompt)
        self.assertIn("不需要处置", prompt)  # ≠ 已处置完毕
        self.assertNotIn("看不出结论时，判 ongoing", prompt)  # 那条无差别兜底

    def test_llm_error_returns_none(self) -> None:
        with mock.patch.object(event_lifecycle, "call_llm", return_value=LlmCallResult(error="Timeout")):
            self.assertIsNone(event_lifecycle.assess_event_lifecycle("x", ["y"]))

    def test_unparseable_reply_returns_none(self) -> None:
        with mock.patch.object(event_lifecycle, "call_llm", return_value=LlmCallResult(content="还没结束")):
            self.assertIsNone(event_lifecycle.assess_event_lifecycle("x", ["y"]))

    def test_no_texts_returns_none_without_calling_the_model(self) -> None:
        with mock.patch.object(event_lifecycle, "call_llm") as call:
            self.assertIsNone(event_lifecycle.assess_event_lifecycle("x", []))
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
