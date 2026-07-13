"""话题继承的闸门：只有真正的追问才继承上一轮话题，泛问不许被旧话题绑架。

## 线上实况（2026-07-13 用户截图）

用户在某段对话里问过「辅导员」相关的问题，之后切到别的页面再回来，
问 UI 上的头号示例问句：

    「最近有什么热点？」   →   话题：辅导员，只命中 1 个规则聚类小事件

机制：这是一句零话题的泛问（规则抢答正确地给出 keyword=""），但
`keyword = routed.keyword or last_keyword` 把空话题词当成"追问"，
自动续上了进程记忆里的旧话题「辅导员」。检索范围从"全部已发布事件"
塌缩成"辅导员"，答案完全跑偏——同一句话的回答取决于一个用户看不见的
隐藏状态。

## 规则

继承**只**发生在句子确实在指代上文时（含 FOLLOW_UP_SIGNALS 里的
指代信号：再/继续/刚才/那个/展开…）：

    「再展开讲讲」        → 继承上一轮话题 ✓（这正是继承存在的意义）
    「最近有什么热点？」  → keyword=""，检索全部 ✓（泛问的正确语义）
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


FAKE_NOTES = [
    OpinionNote(note_id="1", title="辅导员通知", content="辅导员相关讨论", heat_score=50.0),
]


class TopicInheritanceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        for patcher in (
            patch.object(OpinionChatService, "_notes", return_value=list(FAKE_NOTES)),
            patch.object(OpinionChatService, "_published_events", return_value=[]),
            patch(
                "backend.services.opinion_chat_service.generate_llm_report",
                return_value="回答",
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def chat(self, message: str, route: IntentRoute):
        service = OpinionChatService(db=None)
        with patch(
            "backend.services.opinion_chat_service.route_intent", return_value=route
        ):
            return service.chat(message, user_id="u1")

    def seed_stale_topic(self) -> None:
        """第一轮：聊出一个话题词「辅导员」，留在进程记忆里。"""

        self.chat("辅导员的事怎么看", IntentRoute(intent="opinion_answer", keyword="辅导员", source="llm"))


class GeneralQuestionTests(TopicInheritanceTestBase):
    def test_a_general_question_does_not_inherit_the_stale_topic(self):
        self.seed_stale_topic()

        response = self.chat(
            "最近有什么热点？",
            IntentRoute(intent="hotspots", keyword="", source="rules"),
        )

        self.assertEqual(
            response["keyword"],
            "",
            "「最近有什么热点？」是自足的泛问，不含任何指代——它被扣上了旧话题，"
            "检索范围从全部事件塌缩成上一轮的话题（用户截图实证：话题:辅导员）",
        )

    def test_a_general_question_streams_without_the_stale_topic(self):
        """流式与阻塞同一语义。"""

        self.seed_stale_topic()
        service = OpinionChatService(db=None)
        with patch(
            "backend.services.opinion_chat_service.route_intent",
            return_value=IntentRoute(intent="hotspots", keyword="", source="rules"),
        ), patch(
            "backend.services.opinion_chat_service.stream_llm_report",
            side_effect=lambda outcome=None, **_k: iter(["回答"]),
        ):
            events = list(service.chat_stream("最近有什么热点？", user_id="u1"))

        meta = dict(events)["meta"]
        self.assertEqual(meta["keyword"], "", "流式版的泛问同样不许继承旧话题")


class RouterTopicStateTests(TopicInheritanceTestBase):
    """路由给出 topic 判断时，service 必须服从它——判断收归 LLM，算术只做兜底。"""

    def test_continue_inherits_even_without_signal_words(self):
        """「你觉得为什么学生会产生负面的情绪」——没有任何指代词，但路由判了 continue。

        这正是指代词表学不会的那一类（用户七轮实测：省去背景词后答案基于全部事件）。
        """

        self.seed_stale_topic()

        response = self.chat(
            "你觉得为什么学生会产生负面的情绪",
            IntentRoute(intent="opinion_answer", keyword="", source="llm", topic="continue"),
        )

        self.assertEqual(
            response["keyword"],
            "辅导员",
            "路由判定 continue 时必须沿用上一轮话题——哪怕句子里一个指代词都没有",
        )

    def test_continue_does_not_let_a_new_noun_hijack_the_topic(self):
        """「关键是我搬到的新宿舍条件更差」——句中冒出的新名词不是换话题。"""

        self.seed_stale_topic()

        response = self.chat(
            "关键是我搬到的新宿舍，条件比原来的还差",
            IntentRoute(intent="opinion_answer", keyword="新宿舍", source="llm", topic="continue"),
        )

        self.assertEqual(response["keyword"], "辅导员", "continue 时沿用旧话题，新名词不接管检索")
        # 话题记忆也不许被顺手改掉——下一轮的 continue 还要靠它
        from backend.services.opinion_chat_service import _last_keyword_by_user

        self.assertEqual(_last_keyword_by_user.get("u1"), "辅导员", "continue 不许覆盖话题记忆")

    def test_global_ignores_the_stale_topic(self):
        self.seed_stale_topic()

        response = self.chat(
            "最近有什么热点？",
            IntentRoute(intent="hotspots", keyword="", source="rules", topic="global"),
        )

        self.assertEqual(response["keyword"], "")

    def test_switch_updates_the_topic_memory(self):
        self.seed_stale_topic()

        response = self.chat(
            "换个话题，食堂最近怎么样",
            IntentRoute(intent="opinion_answer", keyword="食堂", source="llm", topic="switch"),
        )
        from backend.services.opinion_chat_service import _last_keyword_by_user

        self.assertEqual(response["keyword"], "食堂")
        self.assertEqual(_last_keyword_by_user.get("u1"), "食堂", "switch 才更新话题记忆")


class FollowUpTests(TopicInheritanceTestBase):
    def test_a_real_follow_up_still_inherits_the_topic(self):
        """「再展开讲讲」含指代信号——继承是它的正确语义，不许误伤。"""

        self.seed_stale_topic()

        response = self.chat(
            "再展开讲讲",
            IntentRoute(intent="opinion_answer", keyword="", source="llm"),
        )

        self.assertEqual(response["keyword"], "辅导员", "真正的追问必须继续沿用上一轮话题")

    def test_an_explicit_new_topic_always_wins(self):
        self.seed_stale_topic()

        response = self.chat(
            "食堂怎么样",
            IntentRoute(intent="opinion_answer", keyword="食堂", source="llm"),
        )

        self.assertEqual(response["keyword"], "食堂", "路由提取到新话题时，新话题优先")


if __name__ == "__main__":
    unittest.main()
