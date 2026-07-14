"""查无时的出路：告诉用户库里有什么，而不是「已找到 0 条」。

「已找到 0 条相关校园公开内容。你可以进一步询问热点、风险或生成简报。」——
这是一条死路：用户不知道能问什么，只能瞎猜换词再撞一次。引导用算术组装
（列出已发布事件的标题），零 LLM 调用：查无本来就是零成本路径，不能为了
一句引导话反而引入生成延迟和幻觉面。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.agent.public_opinion_core.schemas import OpinionEvent
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


def _event(title: str) -> OpinionEvent:
    return OpinionEvent(
        event_key=f"sem:{title}",
        title=title,
        summary="",
        category="campus",
        risk_level="low",
        sentiment="neutral",
        heat_score=1.0,
        source_count=1,
        extra={"event_id": 1},
    )


class _NoHitService(OpinionChatService):
    """检索一无所获的库：话题查询空，但全库有已发布事件可列。"""

    def __init__(self):
        self.db = None
        self._notes_cache = {}

    def _published_events(self, keyword: str = "", limit: int = 8):
        if keyword:
            return []  # 用户问的话题：查无
        return [_event("东校区宿舍搬迁"), _event("康某论文调查")]  # 全库：可列给用户

    def _search_ranked_notes(self, keyword: str = "", limit: int = 10):
        return []


def _route():
    return IntentRoute(intent="search", keyword="操场翻新", source="llm", topic="switch")


class NoResultGuidanceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)

    def test_zero_hits_lists_askable_topics_instead_of_a_dead_end(self) -> None:
        service = _NoHitService()
        with patch("backend.services.opinion_chat_service.route_intent", return_value=_route()):
            response = service.chat("操场翻新有什么进展", user_id="u1")

        self.assertNotIn("已找到 0 条", response["answer"], "「已找到 0 条」是死路，不许再出现")
        self.assertIn("操场翻新", response["answer"], "要复述用户问的话题——让他知道系统理解了什么")
        self.assertIn("东校区宿舍搬迁", response["answer"], "要列出库里真实存在的话题给他选")
        self.assertIn("康某论文调查", response["answer"])

    def test_the_stream_path_says_exactly_the_same_thing(self) -> None:
        service = _NoHitService()
        with patch("backend.services.opinion_chat_service.route_intent", return_value=_route()):
            events = list(service.chat_stream("操场翻新有什么进展", user_id="u2"))

        text = "".join(p["text"] for k, p in events if k == "delta")
        done = next(p for k, p in events if k == "done")
        self.assertIn("东校区宿舍搬迁", text, "流式与阻塞必须同一句话——两套实现漂移=两种回答")
        self.assertEqual(done["answer"], text)

    def test_hits_keep_the_existing_summary_line(self) -> None:
        # 有结果时维持原文案（清单由前端 note-list 渲染），本次只修零结果分支。
        service = _NoHitService()
        note = type("N", (), {"title": "t", "sentiment": "neutral", "heat_score": 1.0, "url": ""})()
        with (
            patch("backend.services.opinion_chat_service.route_intent", return_value=_route()),
            patch.object(_NoHitService, "_search_ranked_notes", return_value=[note] * 3),
        ):
            response = service.chat("操场翻新有什么进展", user_id="u3")

        self.assertIn("已找到 3 条", response["answer"])

    def test_an_empty_event_library_still_gives_a_way_out(self) -> None:
        # 连可列的事件都没有（新部署/降级）：至少告诉用户可以怎么问，不许输出空引导。
        service = _NoHitService()
        with (
            patch("backend.services.opinion_chat_service.route_intent", return_value=_route()),
            patch.object(_NoHitService, "_published_events", return_value=[]),
        ):
            response = service.chat("操场翻新有什么进展", user_id="u4")

        self.assertNotIn("已找到 0 条", response["answer"])
        self.assertIn("热点", response["answer"], "库空时至少给出「问热点」这类通用出路")


if __name__ == "__main__":
    unittest.main()
