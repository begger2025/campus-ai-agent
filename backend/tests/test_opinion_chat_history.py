from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.services.critic import ReviewResult
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import (
    HISTORY_ANSWER_MAX_CHARS,
    OpinionChatService,
    reset_chat_memory,
)
from backend.services.react_loop import ReactResult


FAKE_NOTES = [
    OpinionNote(note_id="1", title="食堂排队太久", content="食堂排队太久", heat_score=50.0),
    OpinionNote(note_id="2", title="宿舍热水不稳定", content="宿舍热水不稳定", heat_score=30.0),
]


def hotspots_route():
    return IntentRoute(intent="hotspots", keyword="食堂", source="llm")


class ChatHistoryTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        self.tasks: list[str] = []

        def capture_report(**kwargs) -> str:
            self.tasks.append(kwargs["user_task"])
            return "这是助手的回答"

        for patcher in (
            patch.object(OpinionChatService, "_notes", return_value=list(FAKE_NOTES)),
            patch(
                "backend.services.opinion_chat_service.generate_llm_report",
                side_effect=capture_report,
            ),
            patch(
                "backend.services.opinion_chat_service.review_report",
                return_value=ReviewResult(),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, message: str, user_id: str = "u1", **kwargs):
        service = OpinionChatService(db=None)
        with patch(
            "backend.services.opinion_chat_service.route_intent",
            return_value=hotspots_route(),
        ):
            return service.chat(message, user_id=user_id, **kwargs)


class ChatHistoryTest(ChatHistoryTestBase):
    def test_first_turn_has_no_history_block(self) -> None:
        self.chat("最近有什么热点？")

        self.assertNotIn("最近对话回顾", self.tasks[0])

    def test_second_turn_includes_previous_round_in_user_task(self) -> None:
        self.chat("最近有什么热点？")
        self.chat("刚才那个再展开讲讲")

        self.assertIn("最近对话回顾", self.tasks[1])
        self.assertIn("最近有什么热点？", self.tasks[1])
        self.assertIn("这是助手的回答", self.tasks[1])
        self.assertIn("刚才那个再展开讲讲", self.tasks[1])

    def test_stored_answer_is_truncated(self) -> None:
        long_answer = "答" * 1000
        with patch(
            "backend.services.opinion_chat_service.generate_llm_report",
            side_effect=lambda **kwargs: long_answer,
        ):
            self.chat("第一问")
        self.chat("第二问")

        self.assertNotIn(long_answer, self.tasks[-1])
        self.assertIn("答" * HISTORY_ANSWER_MAX_CHARS + "…", self.tasks[-1])

    def test_history_keeps_only_last_five_rounds(self) -> None:
        # 窗口从 3 轮加到 5 轮（2026-07-13）：用户的真实对话七八轮起步，3 轮窗口意味着
        # 聊到后半段，开头交代的话题背景已经滑出窗口——"混乱感"的来源之一。
        for index in range(7):
            self.chat(f"第{index}个问题")

        # 第 7 问（第6个问题）时，deque(maxlen=10) 保留第 1~5 问五轮，第 0 问被挤出。
        last_task = self.tasks[-1]
        self.assertNotIn("第0个问题", last_task)
        self.assertIn("第1个问题", last_task)
        self.assertIn("第5个问题", last_task)

    def test_reset_clears_history(self) -> None:
        self.chat("第一问")
        self.chat("第二问", reset=True)

        self.assertNotIn("最近对话回顾", self.tasks[1])
        self.assertNotIn("第一问", self.tasks[1])

    def test_users_are_isolated(self) -> None:
        self.chat("甲用户的问题", user_id="ua")
        self.chat("乙用户的问题", user_id="ub")

        self.assertNotIn("甲用户的问题", self.tasks[1])

    def test_failed_turn_is_not_recorded(self) -> None:
        with patch(
            "backend.services.opinion_chat_service.generate_llm_report",
            side_effect=RuntimeError("provider down"),
        ):
            with self.assertRaises(RuntimeError):
                self.chat("会失败的问题")
        self.chat("第二问")

        self.assertNotIn("会失败的问题", self.tasks[-1])

    def test_complex_branch_passes_history_to_react(self) -> None:
        self.chat("最近有什么热点？")

        captured: dict = {}

        def fake_react(message, *, tools, max_steps=None):
            captured["message"] = message
            return ReactResult(answer="对比结论", steps=[], stop_reason="answered")

        service = OpinionChatService(db=None)
        with patch(
            "backend.services.opinion_chat_service.route_intent",
            return_value=IntentRoute(intent="complex_analysis", keyword="", source="llm"),
        ), patch("backend.services.opinion_chat_service.run_react", side_effect=fake_react):
            service.chat("对比一下食堂和宿舍", user_id="u1")

        self.assertIn("最近对话回顾", captured["message"])
        self.assertIn("最近有什么热点？", captured["message"])


if __name__ == "__main__":
    unittest.main()
