"""事件级 LLM 风险研判（`public_opinion_core/llm_risk.py`）：核心包侧的契约与降级。

**被修的缺陷**（真实数据实测）：规则风险分把「东校区宿舍火灾」判成全库最低风险
（`low` / 4.0），而「本科课业压力争议」（学生吐槽作业多）是最高风险（`medium` / 64.0）。
两个成因：

1. `HIGH_RISK_WORDS` 只有六个电诈词（诈骗/银行卡/验证码/陌生人/尾随/缴费链接）——
   系统对"高风险"的全部认识就是这六个词，没有火灾、伤亡、食物中毒、性骚扰、学术不端……
   而校园出事的方式**穷举不完**：这是"闭集词表"的结构性死穴，也是必须上 LLM 的理由。
2. 风险分被**互动量**污染（评论≥25 加 8 分、转发≥10 加 10 分、高热加 8 分）：于是它
   量的是**流行度**而不是**严重性**。没人点赞的火情播报（heat 3/5/9）因此隐形。

本模块把**严重性**（LLM 研判）与**热度**（算术）解耦：assessor 只准动 risk_*，
`heat_score / heat_rank / ranking_score` 一个字节都不许改（见 HeatIsUntouchedTest）。

零网络、零数据库：assessor 全部是注入的假货。
"""

from __future__ import annotations

import unittest

from backend.agent.public_opinion_core.clustering import build_event_from_group
from backend.agent.public_opinion_core.llm_risk import assess_events_risk
from backend.agent.public_opinion_core.schemas import OpinionNote


def note(note_id: str, title: str, **kwargs) -> OpinionNote:
    return OpinionNote(note_id=note_id, title=title, content=kwargs.pop("content", title), **kwargs)


FIRE_NOTES = [
    note("ks:1", "中山大学东校区宿舍发生火情，现场楼道浓烟滚滚", heat_score=5.0),
    note("ks:2", "中山大学广州校区宿舍发生火灾，消防及时到场处置", heat_score=9.0),
    note("ks:3", "中山大学宿舍起火 校方通报：现场无人员伤亡", heat_score=3.0),
]

COURSEWORK_NOTES = [
    note("xhs:1", "中大本科课业压力好大 天天写作业", heat_score=8000.0, comment_count=40),
    note("xhs:2", "本科生吐槽课程作业太多", heat_score=6000.0, comment_count=30),
]


def fire_event():
    return build_event_from_group("sem:fire", "东校区宿舍火灾", "semantic", list(FIRE_NOTES))


def coursework_event():
    return build_event_from_group("sem:course", "本科课业压力争议", "semantic", list(COURSEWORK_NOTES))


def judgement(**overrides) -> dict:
    payload = {
        "risk_level": "high",
        "risk_score": 90,
        "risk_reasons": ["宿舍火情属于人身安全事故，需保卫处/后勤立即处置"],
        "concerns": ["校园安全风险"],
    }
    payload.update(overrides)
    return payload


class AssessorAppliedTest(unittest.TestCase):
    def test_no_assessor_keeps_rule_result(self) -> None:
        event = fire_event()
        rule_level, rule_score = event.risk_level, event.risk_score

        assessed = assess_events_risk([event], None)

        self.assertEqual(assessed, 0)
        self.assertEqual(event.risk_level, rule_level)
        self.assertEqual(event.risk_score, rule_score)
        self.assertNotIn("risk_assessed_by", event.extra)

    def test_llm_judgement_replaces_rule_risk(self) -> None:
        """规则给火灾判 low；LLM 判 high 之后，事件必须真的变成 high。"""

        event = fire_event()
        self.assertEqual(event.risk_level, "low")  # 缺陷现场：六个电诈词认不出火灾

        assessed = assess_events_risk([event], lambda title, texts: judgement())

        self.assertEqual(assessed, 1)
        self.assertEqual(event.risk_level, "high")
        self.assertEqual(event.risk_score, 90.0)
        self.assertEqual(event.risk_reasons, ["宿舍火情属于人身安全事故，需保卫处/后勤立即处置"])
        self.assertEqual(event.concerns, ["校园安全风险"])
        self.assertEqual(event.extra["risk_assessed_by"], "llm")
        # 事件摘要里写着"风险等级为 X"，不跟着改就会和 risk_level 自相矛盾。
        self.assertIn("high", event.agent_summary)

    def test_assessor_receives_title_and_member_texts(self) -> None:
        seen: list[tuple[str, list[str]]] = []

        def assessor(title: str, texts: list[str]) -> dict:
            seen.append((title, list(texts)))
            return judgement()

        assess_events_risk([fire_event()], assessor)

        title, texts = seen[0]
        self.assertEqual(title, "东校区宿舍火灾")
        self.assertEqual(len(texts), 3)
        self.assertTrue(any("浓烟" in text for text in texts), texts)

    def test_each_event_is_assessed_independently(self) -> None:
        fire, coursework = fire_event(), coursework_event()

        def assessor(title: str, texts: list[str]) -> dict:
            if "火灾" in title:
                return judgement()
            return judgement(risk_level="low", risk_score=15, risk_reasons=["日常课业抱怨，不需要学校立即处置"], concerns=[])

        assessed = assess_events_risk([fire, coursework], assessor)

        self.assertEqual(assessed, 2)
        self.assertEqual(fire.risk_level, "high")
        self.assertEqual(coursework.risk_level, "low")


class HeatIsUntouchedTest(unittest.TestCase):
    """严重性与热度解耦：assessor 不许发明热度。"""

    def test_heat_fields_survive_the_llm_pass(self) -> None:
        event = fire_event()
        before = (event.heat_score, event.heat_rank, event.ranking_score, event.source_count)

        assess_events_risk(
            [event],
            lambda title, texts: judgement(heat_score=99999, source_count=999, ranking_score=42),
        )

        self.assertEqual(
            (event.heat_score, event.heat_rank, event.ranking_score, event.source_count), before
        )


class DegradationTest(unittest.TestCase):
    """LLM 挂了/胡说了，事件照出，退回规则结果并留痕。"""

    def assert_kept_rule_result(self, assessor, expected_warning: str) -> None:
        event = fire_event()
        rule_level, rule_score, rule_reasons = event.risk_level, event.risk_score, list(event.risk_reasons)
        warnings: list[str] = []

        assessed = assess_events_risk([event], assessor, warnings=warnings)

        self.assertEqual(assessed, 0)
        self.assertEqual(event.risk_level, rule_level)
        self.assertEqual(event.risk_score, rule_score)
        self.assertEqual(event.risk_reasons, rule_reasons)
        self.assertNotIn("risk_assessed_by", event.extra)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(expected_warning, warnings[0])

    def test_assessor_raises(self) -> None:
        def boom(title, texts):
            raise TimeoutError("read timed out")

        self.assert_kept_rule_result(boom, "unavailable")

    def test_assessor_returns_none(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: None, "unusable")

    def test_invented_risk_level(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: judgement(risk_level="critical"), "unusable")

    def test_score_above_100(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: judgement(risk_score=140), "unusable")

    def test_negative_score(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: judgement(risk_score=-5), "unusable")

    def test_non_numeric_score(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: judgement(risk_score="很高"), "unusable")

    def test_boolean_score_is_not_a_number(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: judgement(risk_score=True), "unusable")

    def test_missing_reasons(self) -> None:
        """无依据的判决不算判决：风险等级要能对人解释，否则退回规则结果。"""

        self.assert_kept_rule_result(lambda title, texts: judgement(risk_reasons=[]), "unusable")

    def test_not_a_mapping(self) -> None:
        self.assert_kept_rule_result(lambda title, texts: ["high"], "unusable")

    def test_one_bad_event_does_not_poison_the_others(self) -> None:
        fire, coursework = fire_event(), coursework_event()
        warnings: list[str] = []

        def assessor(title: str, texts: list[str]) -> dict:
            if "火灾" in title:
                raise TimeoutError("read timed out")
            return judgement(risk_level="low", risk_score=10, risk_reasons=["日常课业抱怨"])

        assessed = assess_events_risk([fire, coursework], assessor, warnings=warnings)

        self.assertEqual(assessed, 1)
        self.assertEqual(fire.risk_level, "low")  # 规则结果原样保留
        self.assertNotIn("risk_assessed_by", fire.extra)
        self.assertEqual(coursework.extra["risk_assessed_by"], "llm")
        self.assertEqual(len(warnings), 1)


class NormalizationTest(unittest.TestCase):
    def test_level_case_and_whitespace_are_tolerated(self) -> None:
        event = fire_event()
        assess_events_risk([event], lambda title, texts: judgement(risk_level=" HIGH "))
        self.assertEqual(event.risk_level, "high")

    def test_score_boundaries_are_inclusive(self) -> None:
        low, high = fire_event(), fire_event()
        assess_events_risk([low], lambda title, texts: judgement(risk_level="low", risk_score=0))
        assess_events_risk([high], lambda title, texts: judgement(risk_score=100))
        self.assertEqual((low.risk_score, high.risk_score), (0.0, 100.0))

    def test_reasons_and_concerns_are_cleaned(self) -> None:
        event = fire_event()
        assess_events_risk(
            [event],
            lambda title, texts: judgement(
                risk_reasons=["  人身安全事故  ", "", "人身安全事故"],
                concerns=["校园安全风险", "  ", "校园安全风险"],
            ),
        )
        self.assertEqual(event.risk_reasons, ["人身安全事故"])  # 去空白、去空串、去重
        self.assertEqual(event.concerns, ["校园安全风险"])


if __name__ == "__main__":
    unittest.main()
