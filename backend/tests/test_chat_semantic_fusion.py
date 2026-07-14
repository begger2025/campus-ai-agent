"""聊天帖子层的混合检索：字面命中优先入集，语义补字面漏掉的。

顺序在这一层刻意不讲究——下游 `_search_ranked_notes` 按 note_rank_key 重排、
聚类按热度序处理，这里唯一重要的是**集合**：哪些帖子进了检索范围。
字面命中是高精度信号（正文真的含这个词），永远全收；语义候选只补集，
且已经被阈值筛过（见 semantic_posts）。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.services.opinion_chat_service import CHAT_NOTE_LIMIT, OpinionChatService, reset_chat_memory


def _row(post_id: int, title: str) -> dict:
    return {
        "id": post_id,
        "processed_post_id": post_id,
        "raw_post_id": post_id,
        "platform": "xhs",
        "note_id": f"xhs:{post_id}",
        "title": title,
        "content": f"{title}的内容",
        "url": "",
        "like_count": 1,
        "collect_count": 0,
        "comment_count": 0,
        "share_count": 0,
    }


class SemanticFusionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        self.service = OpinionChatService(db=None)

    def _notes(self, literal_rows, semantic_ids, semantic_rows):
        def fake_query(db, **kwargs):
            if kwargs.get("ids") is not None:
                wanted = kwargs["ids"]
                by_id = {row["id"]: row for row in semantic_rows}
                return [by_id[i] for i in wanted if i in by_id]
            return list(literal_rows)

        with (
            patch("backend.services.opinion_chat_service.query_agent_rows", side_effect=fake_query),
            patch(
                "backend.services.opinion_chat_service.semantic_post_ids",
                return_value=list(semantic_ids),
            ),
        ):
            return self.service._notes("饭堂涨价")

    def test_semantic_hits_join_the_literal_ones(self) -> None:
        notes = self._notes(
            literal_rows=[_row(1, "饭堂涨价了")],
            semantic_ids=[7, 8],
            semantic_rows=[_row(7, "食堂调价通知"), _row(8, "套餐贵了三块")],
        )

        titles = {note.title for note in notes}
        self.assertEqual(titles, {"饭堂涨价了", "食堂调价通知", "套餐贵了三块"},
                         "「饭堂涨价」的字面命中和「食堂调价」的语义命中必须都在检索集合里")

    def test_overlapping_ids_are_not_fetched_twice(self) -> None:
        captured: dict = {}

        def fake_query(db, **kwargs):
            if kwargs.get("ids") is not None:
                captured["ids"] = kwargs["ids"]
                return []
            return [_row(1, "饭堂涨价了")]

        with (
            patch("backend.services.opinion_chat_service.query_agent_rows", side_effect=fake_query),
            patch("backend.services.opinion_chat_service.semantic_post_ids", return_value=[1, 9]),
        ):
            self.service._notes("饭堂涨价")

        self.assertEqual(captured["ids"], [9], "字面已经拿到的帖子不许按 id 再取一遍")

    def test_no_semantic_hits_keeps_literal_only(self) -> None:
        notes = self._notes(literal_rows=[_row(1, "饭堂涨价了")], semantic_ids=[], semantic_rows=[])

        self.assertEqual([note.title for note in notes], ["饭堂涨价了"])

    def test_global_query_skips_semantic_search(self) -> None:
        # keyword 为空 = 全量检索，本来就没有"漏"可补；语义查询是纯浪费。
        with (
            patch(
                "backend.services.opinion_chat_service.query_agent_rows",
                return_value=[_row(1, "任意")],
            ),
            patch("backend.services.opinion_chat_service.semantic_post_ids") as sem,
        ):
            self.service._notes("")

        sem.assert_not_called()

    def test_semantic_alone_must_clear_a_stricter_threshold(self) -> None:
        """字面零命中时语义是孤证——门槛必须更高。

        真库实测（2026-07-15）：真改写命中 0.60+（饭堂涨价→食堂价格帖），
        假阳性最高 0.576（校车预约→升学宴）。字面有命中时 0.55 的语义补充
        有佐证兜底；字面零命中时若仍用 0.55，「校车预约」会拿一堆升学宴帖
        去回答——比查无引导更糟的静默错误答案。
        """

        captured: dict = {}

        def fake_sem(query, **kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("backend.services.opinion_chat_service.query_agent_rows", return_value=[]),
            patch("backend.services.opinion_chat_service.semantic_post_ids", side_effect=fake_sem),
        ):
            self.service._notes("校车预约")

        self.assertIs(captured.get("corroborated"), False, "孤证必须用更严的阈值档")

    def test_corroborated_semantic_uses_the_default_threshold(self) -> None:
        captured: dict = {}

        def fake_sem(query, **kwargs):
            captured.update(kwargs)
            return []

        with (
            patch(
                "backend.services.opinion_chat_service.query_agent_rows",
                return_value=[_row(1, "字面命中")],
            ),
            patch("backend.services.opinion_chat_service.semantic_post_ids", side_effect=fake_sem),
        ):
            self.service._notes("饭堂涨价")

        self.assertIs(captured.get("corroborated"), True, "字面有命中时用默认阈值档（语义只是补充）")

    def test_the_note_limit_still_caps_the_merged_set(self) -> None:
        literal = [_row(i, f"字面{i}") for i in range(1, CHAT_NOTE_LIMIT + 1)]
        semantic_rows = [_row(9001, "语义补充")]

        notes = self._notes(literal_rows=literal, semantic_ids=[9001], semantic_rows=semantic_rows)

        self.assertEqual(len(notes), CHAT_NOTE_LIMIT, "融合后的集合仍要封顶——prompt 不是无底洞")


if __name__ == "__main__":
    unittest.main()
