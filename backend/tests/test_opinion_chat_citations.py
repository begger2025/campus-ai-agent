from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.services.critic import ReviewResult
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


FAKE_NOTES = [
    OpinionNote(note_id="1", title="食堂排队太久", content="食堂排队太久", heat_score=50.0),
    OpinionNote(note_id="2", title="食堂新窗口不错", content="食堂新窗口不错", heat_score=30.0),
]


def report_route():
    return IntentRoute(intent="report", keyword="食堂", source="llm")


class ChatReportCitationTest(unittest.TestCase):
    """report 意图的引用链路：正常路径带引用审计，LLM 降级/空数据不误报。"""

    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)

    def chat(self, notes: list[OpinionNote], gen_side_effect, critic: MagicMock):
        service = OpinionChatService(db=None)
        with (
            patch.object(OpinionChatService, "_notes", return_value=notes),
            patch(
                "backend.services.opinion_chat_service.generate_llm_report",
                side_effect=gen_side_effect,
            ) as gen,
            patch("backend.services.opinion_chat_service.review_report", critic),
            patch(
                "backend.services.opinion_chat_service.route_intent",
                return_value=report_route(),
            ),
        ):
            response = service.chat("给我一份食堂简报", user_id="u1")
        return response, gen

    def test_normal_report_attaches_citations_and_critic_gets_map(self) -> None:
        critic = MagicMock(return_value=ReviewResult(verdict="pass", issues=[]))

        response, gen = self.chat(
            list(FAKE_NOTES),
            lambda **kwargs: "食堂排队时间长 [来源:p1]。",
            critic,
        )

        self.assertIn("p1", response["citations"])
        self.assertTrue(gen.call_args.kwargs["require_citations"])
        self.assertEqual(critic.call_args.kwargs["citations"], response["citations"])

    def test_degraded_llm_report_skips_citation_audit(self) -> None:
        # LLM 降级时返回规则版摘要（fallback 前缀 + 错误说明），不应触发"无引用"误报。
        def degraded(**kwargs):
            return f"{kwargs['fallback_text']}\n\n（大模型总结暂不可用，以下为规则版摘要。错误类型：timeout）"

        critic = MagicMock(return_value=ReviewResult(verdict="warn", issues=["不应出现"]))

        response, _gen = self.chat(list(FAKE_NOTES), degraded, critic)

        critic.assert_not_called()
        self.assertEqual(response["review"]["verdict"], "skipped")
        self.assertNotIn("审校提示", response["answer"])

    def test_empty_data_disables_citation_enforcement(self) -> None:
        # 无匹配数据 → cite_map 为空 → 不强制引用，也不把空映射交给 critic。
        critic = MagicMock(return_value=ReviewResult(verdict="pass", issues=[]))

        response, gen = self.chat([], lambda **kwargs: "目前没有相关数据。", critic)

        self.assertEqual(response["citations"], {})
        self.assertFalse(gen.call_args.kwargs.get("require_citations"))
        self.assertIsNone(critic.call_args.kwargs["citations"])


if __name__ == "__main__":
    unittest.main()
