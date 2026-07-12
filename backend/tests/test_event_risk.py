"""事件风险研判的**部署侧接线**（backend/services/event_risk.py）+ 服务层编排。

核心包（llm_risk.py）只认识一个 Callable：「给你事件标题和它的帖子，还我一份风险研判」。
它不认识 HTTP、模型名和 API key——`event_risk.py` 是把它接上真实模型的那一层，也是唯一读
EVENT_LLM_* 的地方（和 event_refiner.py 同一个注入模式）。

三件必须成立的事：
  1. **确定性**：temperature=0，走 call_llm 的 JSON 缓存（同一批事件第二次跑不再花钱，
     消融实验因此可复现）；
  2. **提示词里必须写明"流行度不是严重性"**：这正是被修的缺陷（10 万赞的宿舍日常 vlog
     不是高风险；没人点赞的火情播报是）；
  3. **拿不到就返回 None**：未配 key、超时、返回垃圾——一律 None，核心退回规则风险。

零网络、零数据库：call_llm 全程被换成假的。
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from backend.agent.public_opinion_core import AnalyzeRequest, PublicOpinionAgentService
from backend.services import event_risk
from backend.services.llm_client import LlmCallResult


TEXTS = [
    "中山大学东校区宿舍发生火情，现场楼道浓烟滚滚",
    "中山大学宿舍起火 校方通报：现场无人员伤亡",
]


def reply(payload: dict) -> LlmCallResult:
    return LlmCallResult(content=json.dumps(payload, ensure_ascii=False))


JUDGEMENT = {
    "risk_level": "high",
    "risk_score": 88,
    "risk_reasons": ["宿舍火情属人身安全事故"],
    "concerns": ["校园安全风险"],
}


_next_id = iter(range(1, 100))


def row(note_id: str, title: str, **kwargs) -> dict:
    post_id = next(_next_id)
    base = {
        "id": post_id,
        "processed_post_id": post_id,
        "note_id": note_id,
        "platform": "ks",
        "title": title,
        "content": title,
        "publish_date": "2026-03-24",
    }
    base.update(kwargs)
    return base


FIRE_ROWS = [
    row("ks:1", "中山大学东校区宿舍发生火情，现场楼道浓烟滚滚", heat_score=5, like_count=5),
    row("ks:2", "中山大学宿舍起火 校方通报：现场无人员伤亡", heat_score=3, like_count=3),
]
# 规则风险的"最高分"事件：学生吐槽作业多 + 高互动量（评论/转发/热度都在给风险加分）。
COURSEWORK_ROWS = [
    row("xhs:1", "本科课业压力好大，作业写不完", platform="xhs", heat_score=9000,
        like_count=8000, comment_count=60, share_count=40, heat_rank=99.0),
    row("xhs:2", "中大本科生吐槽课程作业太多 选课也难", platform="xhs", heat_score=7000,
        like_count=6000, comment_count=50, share_count=30, heat_rank=95.0),
]


class RiskAssessorAvailabilityTest(unittest.TestCase):
    def test_no_assessor_without_api_key(self) -> None:
        with mock.patch.object(event_risk, "EVENT_LLM_API_KEY", ""):
            self.assertIsNone(event_risk.get_risk_assessor())

    def test_no_assessor_when_disabled(self) -> None:
        with (
            mock.patch.object(event_risk, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_risk, "EVENT_RISK_ENABLED", False),
        ):
            self.assertIsNone(event_risk.get_risk_assessor())

    def test_assessor_available_when_configured(self) -> None:
        with (
            mock.patch.object(event_risk, "EVENT_LLM_API_KEY", "sk-test"),
            mock.patch.object(event_risk, "EVENT_RISK_ENABLED", True),
        ):
            self.assertIs(event_risk.get_risk_assessor(), event_risk.assess_event_risk)


class RiskAssessorCallTest(unittest.TestCase):
    def test_parses_judgement_from_json_reply(self) -> None:
        with mock.patch.object(event_risk, "call_llm", return_value=reply(JUDGEMENT)) as call:
            judgement = event_risk.assess_event_risk("东校区宿舍火灾", TEXTS)

        self.assertEqual(judgement["risk_level"], "high")
        self.assertEqual(judgement["risk_score"], 88)
        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)  # 可复现
        self.assertEqual(kwargs["model"], event_risk.EVENT_LLM_MODEL)

    def test_prompt_states_the_domain_frame_and_that_popularity_is_not_severity(self) -> None:
        with mock.patch.object(event_risk, "call_llm", return_value=reply(JUDGEMENT)) as call:
            event_risk.assess_event_risk("东校区宿舍火灾", TEXTS)

        prompt = "\n".join(m["content"] for m in call.call_args.args[0])
        self.assertIn("校园", prompt)  # 领域框架：这是校园舆情，不是通用风控
        self.assertIn("流行度不是严重性", prompt)  # 本次缺陷的核心
        self.assertIn("点赞", prompt)  # 互动量不得作为风险依据
        self.assertIn("食堂", prompt)  # 日常抱怨（饭菜/课业/选课）不是高风险
        self.assertIn("<data>", prompt)  # 采集内容当数据、不当指令
        self.assertIn("东校区宿舍火灾", prompt)  # 事件标题进了提示词
        self.assertIn("浓烟滚滚", prompt)  # 帖子正文进了提示词

    def test_llm_error_returns_none(self) -> None:
        with mock.patch.object(event_risk, "call_llm", return_value=LlmCallResult(error="Timeout")):
            self.assertIsNone(event_risk.assess_event_risk("东校区宿舍火灾", TEXTS))

    def test_unparseable_reply_returns_none(self) -> None:
        with mock.patch.object(event_risk, "call_llm", return_value=LlmCallResult(content="风险很高")):
            self.assertIsNone(event_risk.assess_event_risk("东校区宿舍火灾", TEXTS))

    def test_no_texts_returns_none_without_calling_the_model(self) -> None:
        with mock.patch.object(event_risk, "call_llm") as call:
            self.assertIsNone(event_risk.assess_event_risk("东校区宿舍火灾", []))
        call.assert_not_called()


class ServiceRiskWiringTest(unittest.TestCase):
    """服务层编排：注入 assessor -> 事件风险被重判、事件按新风险重排、模式记进 run_log。"""

    def run_service(self, assessor):
        return PublicOpinionAgentService().analyze_from_rows(
            FIRE_ROWS + COURSEWORK_ROWS,
            AnalyzeRequest(limit=10),
            min_cluster_size=2,
            risk_assessor=assessor,
        )

    def test_rules_only_ranks_the_fire_below_the_coursework_complaint(self) -> None:
        """缺陷现场（无 LLM）：吐槽作业的高互动事件排在火灾前面。"""

        result = self.run_service(None)
        titles = [event.title for event in result.events]
        fire = next(e for e in result.events if "宿舍" in e.title)
        coursework = next(e for e in result.events if "课程" in e.title or "教务" in e.title)

        self.assertEqual(fire.risk_level, "low")
        self.assertLess(fire.risk_score, coursework.risk_score)
        self.assertLess(titles.index(coursework.title), titles.index(fire.title))
        self.assertEqual(result.run_log.extra["risk_mode"], "rules")
        self.assertEqual(result.run_log.extra["risk_assessed"], 0)

    def test_llm_assessor_promotes_the_fire_to_high_and_reorders_events(self) -> None:
        def assessor(title: str, texts: list[str]) -> dict:
            if any("火" in text or "浓烟" in text for text in texts):
                return dict(JUDGEMENT)
            return {
                "risk_level": "low",
                "risk_score": 12,
                "risk_reasons": ["日常课业抱怨，无需学校立即处置"],
                "concerns": ["课程与教务安排"],
            }

        result = self.run_service(assessor)
        fire = next(e for e in result.events if "宿舍" in e.title)

        self.assertEqual(fire.risk_level, "high")
        self.assertEqual(fire.risk_score, 88.0)
        # 排序键的第一位是风险：重判之后必须重排，否则事件列表还是旧顺序。
        self.assertEqual(result.events[0].title, fire.title)
        self.assertEqual(result.run_log.extra["risk_mode"], "llm")
        self.assertEqual(result.run_log.extra["risk_assessed"], 2)

    def test_heat_fields_are_identical_with_and_without_the_llm(self) -> None:
        """严重性变了，热度不许变：heat_score/heat_rank/ranking_score 是算术，不是判断。"""

        def heat(result):
            return {e.title: (e.heat_score, e.heat_rank, e.ranking_score) for e in result.events}

        rules = heat(self.run_service(None))
        llm = heat(self.run_service(lambda title, texts: dict(JUDGEMENT)))

        self.assertEqual(rules, llm)

    def test_llm_failure_falls_back_to_rules_and_warns(self) -> None:
        def boom(title, texts):
            raise TimeoutError("read timed out")

        result = self.run_service(boom)
        fire = next(e for e in result.events if "宿舍" in e.title)

        self.assertEqual(fire.risk_level, "low")  # 规则结果原样保留
        self.assertEqual(result.run_log.extra["risk_mode"], "rules")
        self.assertEqual(result.run_log.extra["risk_assessed"], 0)
        # 降级必须在 agent_run_logs 里看得见——不能假装 AI 上过。
        self.assertTrue(any("llm risk unavailable" in w for w in result.warnings), result.warnings)
        self.assertTrue(any("llm risk unavailable" in w for w in result.run_log.warnings))

    def test_partial_failure_reports_llm_mode_with_a_warning(self) -> None:
        def assessor(title: str, texts: list[str]):
            if any("火" in text for text in texts):
                raise TimeoutError("read timed out")
            return dict(JUDGEMENT)

        result = self.run_service(assessor)

        self.assertEqual(result.run_log.extra["risk_mode"], "llm")
        self.assertEqual(result.run_log.extra["risk_assessed"], 1)
        self.assertTrue(any("llm risk unavailable" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
