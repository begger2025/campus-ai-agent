"""会话记忆持久化：重启不失忆、新对话两边一起翻篇、早前话题可追溯。

进程内记忆重启即丢——用户聊到一半重启服务，「那件事后来呢」就答非所问。
写穿本地 SQLite（绝不碰共享库）：每轮落一行，进程字典 miss 时水合。
持久层任何故障 → 退回"重启失忆"的老行为，绝不让对话报错。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import patch

from backend.services import chat_memory_store as store
from backend.services import opinion_chat_service as chat_mod
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


class _Env(unittest.TestCase):
    """每个用例一个独立的临时库文件。"""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(
            "os.environ", {"CHAT_MEMORY_DB_PATH": str(Path(self.tmp.name) / "mem.sqlite3")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)


class StoreRoundTripTests(_Env):
    def test_save_load_roundtrip(self) -> None:
        store.save(
            "u1", last_keyword="宿舍搬迁", last_intent="report",
            history=[("user", "问"), ("assistant", "答")], topic_trail=["食堂", "宿舍搬迁"],
        )

        loaded = store.load("u1")

        self.assertEqual(loaded["last_keyword"], "宿舍搬迁")
        self.assertEqual(loaded["history"], [("user", "问"), ("assistant", "答")])
        self.assertEqual(loaded["topic_trail"], ["食堂", "宿舍搬迁"])

    def test_expired_rows_are_dropped(self) -> None:
        store.save("u1", last_keyword="宿舍", last_intent="", history=[], topic_trail=[])
        with mock.patch.dict("os.environ", {"CHAT_MEMORY_TTL_HOURS": "0"}):
            self.assertIsNone(store.load("u1"), "过期记忆必须丢弃——舆情对话没有隔周续聊的语境")

    def test_broken_store_degrades_to_none(self) -> None:
        with mock.patch.object(store, "_connect", side_effect=RuntimeError("disk gone")):
            self.assertIsNone(store.load("u1"))
            store.save("u1", last_keyword="x", last_intent="", history=[], topic_trail=[])  # 不许抛


class ServiceHydrationTests(_Env):
    """服务层：重启（进程字典清空）后从持久层水合。"""

    def _chat(self, message: str, routed: IntentRoute, reset: bool = False) -> dict:
        service = OpinionChatService(db=None)
        with (
            patch.object(OpinionChatService, "_published_events", return_value=[]),
            patch.object(OpinionChatService, "_search_ranked_notes", return_value=[]),
            patch("backend.services.opinion_chat_service.route_intent", return_value=routed),
        ):
            return service.chat(message, user_id="u9", reset=reset)

    def test_memory_survives_a_process_restart(self) -> None:
        self._chat("宿舍搬迁怎么样了", IntentRoute(intent="search", keyword="宿舍搬迁", source="llm", topic="switch"))

        # 模拟重启：只清进程字典，不动持久层
        chat_mod._last_keyword_by_user.clear()
        chat_mod._last_intent_by_user.clear()
        chat_mod._history_by_user.clear()

        response = self._chat("后来呢", IntentRoute(intent="search", keyword="", source="llm", topic="continue"))

        self.assertEqual(response["keyword"], "宿舍搬迁", "重启后 continue 必须还接得上话题——持久层要能水合")

    def test_reset_clears_both_sides(self) -> None:
        self._chat("宿舍搬迁怎么样了", IntentRoute(intent="search", keyword="宿舍搬迁", source="llm", topic="switch"))

        self._chat("重新开始", IntentRoute(intent="search", keyword="", source="llm", topic="global"), reset=True)
        chat_mod._last_keyword_by_user.clear()
        chat_mod._last_intent_by_user.clear()
        chat_mod._history_by_user.clear()

        response = self._chat("后来呢", IntentRoute(intent="search", keyword="", source="llm", topic="continue"))

        # search 兜底会把 message 本身填进 keyword 字段（既有行为）；这里测的性质是
        # 旧话题「宿舍搬迁」不许从持久层诈尸回来。
        self.assertNotIn("宿舍搬迁", response["keyword"], "新对话必须两边一起翻篇——持久层不清会诈尸")


class TopicTrailTests(_Env):
    """早前话题轨迹：5 轮滑窗之外的话题不该凭空消失。"""

    def test_switched_topics_accumulate_in_the_history_block(self) -> None:
        service = OpinionChatService(db=None)
        for keyword in ("食堂", "宿舍搬迁"):
            with (
                patch.object(OpinionChatService, "_published_events", return_value=[]),
                patch.object(OpinionChatService, "_search_ranked_notes", return_value=[]),
                patch(
                    "backend.services.opinion_chat_service.route_intent",
                    return_value=IntentRoute(intent="search", keyword=keyword, source="llm", topic="switch"),
                ),
            ):
                service.chat(f"{keyword}的情况", user_id="u9")

        block = chat_mod._history_block("u9")

        self.assertIn("食堂", block, "更早聊过的话题要留在轨迹里，别让 5 轮滑窗把它吞了")


if __name__ == "__main__":
    unittest.main()
