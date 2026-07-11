"""排序/选 top-N/加权重要性的调用点改用 heat_rank；展示仍用 heat_score。

这是整件事的落点：不换调用点的话，heat_rank 只是一个没人读的新列，weibo/zhihu/web
在任何热度排序视图里照样被 xhs/ks 埋掉。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent.public_opinion_core.adapter import processed_post_to_note
from backend.agent.public_opinion_core.clustering import build_event_from_group, sort_events
from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.agent.public_opinion_core.scoring import score_notes
from backend.agent.public_opinion_core.sentiment_risk import analyze_notes_sentiment_and_risk
from backend.database import Base
from backend.models import ProcessedPost, RawPost
from backend.services.public_opinion_adapter import processed_post_to_agent_row


def _note(note_id: str, *, platform: str, heat_score: float, heat_rank: float, title: str = "") -> OpinionNote:
    return OpinionNote(
        note_id=note_id,
        title=title or f"{platform} 帖子 {note_id}",
        content="宿舍热水又停了，报修没人管",
        platform=platform,
        heat_score=heat_score,
        heat_rank=heat_rank,
    )


class NoteCarriesHeatRankTest(unittest.TestCase):
    """heat_rank 必须一路从 processed_posts 流到 OpinionNote，否则调用点无从读起。"""

    def test_agent_row_carries_heat_rank_and_heat_score(self) -> None:
        post = ProcessedPost(
            id=1,
            raw_post_id=1,
            platform="weibo",
            note_id="weibo:1",
            title="标题",
            content="正文",
            heat_score=3.0,
            heat_rank=95.0,
        )
        row = processed_post_to_agent_row(post)
        self.assertEqual(row["heat_rank"], 95.0)
        self.assertEqual(row["heat_score"], 3.0)

    def test_adapter_reads_heat_rank_from_row(self) -> None:
        note = processed_post_to_note(
            {"id": 1, "title": "标题", "content": "正文", "platform": "weibo", "heat_rank": 95.0}
        )
        self.assertEqual(note.heat_rank, 95.0)

    def test_adapter_keeps_stored_heat_score_for_a_web_row_with_no_interactions(self) -> None:
        # web 行的 heat_score 来自来源权威度，用 0 互动量重算会把它抹成 0。
        note = processed_post_to_note(
            {"id": 1, "title": "中大发布通知", "content": "正文", "platform": "web", "heat_score": 100.0}
        )
        self.assertEqual(note.heat_score, 100.0)

    def test_adapter_still_computes_heat_score_when_the_row_has_none(self) -> None:
        note = processed_post_to_note(
            {"id": 1, "title": "标题", "content": "正文", "platform": "xhs", "like_count": 10, "comment_count": 2}
        )
        self.assertEqual(note.heat_score, 16.0)

    def test_score_notes_does_not_erase_an_interaction_free_heat_score(self) -> None:
        web = OpinionNote(note_id="w1", title="通知", content="正文", platform="web", heat_score=100.0)
        xhs = OpinionNote(note_id="x1", title="帖子", content="正文", platform="xhs", like_count=10)
        score_notes([web, xhs])
        self.assertEqual(web.heat_score, 100.0)
        self.assertEqual(xhs.heat_score, 10.0)


class ClusteringUsesHeatRankTest(unittest.TestCase):
    """代表帖挑选与事件排序：跨平台比较，必须用 heat_rank。"""

    def test_representative_note_is_the_top_ranked_not_the_loudest_platform(self) -> None:
        weibo = _note("w1", platform="weibo", heat_score=9.0, heat_rank=95.0, title="微博头部帖")
        xhs = _note("x1", platform="xhs", heat_score=12000.0, heat_rank=20.0, title="小红书长尾帖")

        event = build_event_from_group("dorm_life", "宿舍", "dorm_life", [xhs, weibo])

        # 原始热度差 3 个数量级，但微博是它平台里的头部，小红书那条是长尾。
        self.assertEqual(event.representative_notes[0].note_id, "w1")
        # 展示用的 heat_score 仍是成员原始热度之和，公式没变。
        self.assertEqual(event.heat_score, 12009.0)
        # 事件也拿到一个可跨平台比较的排序分。
        self.assertEqual(event.heat_rank, 115.0)

    def test_sort_events_ranks_by_heat_rank_within_the_same_risk_level(self) -> None:
        loud = OpinionEvent(
            event_key="loud", title="小红书长尾聚合", summary="", category="c",
            risk_level="low", sentiment="neutral", heat_score=24000.0, heat_rank=40.0, source_count=2,
        )
        important = OpinionEvent(
            event_key="important", title="微博头部事件", summary="", category="c",
            risk_level="low", sentiment="neutral", heat_score=18.0, heat_rank=190.0, source_count=2,
        )

        ordered = sort_events([loud, important])

        self.assertEqual([event.event_key for event in ordered], ["important", "loud"])

    def test_sort_events_falls_back_to_heat_score_when_no_rank_is_present(self) -> None:
        # 老数据/未归一化的行（heat_rank 全为 0）不能因为改造就退化成"随机顺序"。
        low = OpinionEvent(
            event_key="low", title="a", summary="", category="c",
            risk_level="low", sentiment="neutral", heat_score=10.0, source_count=1,
        )
        high = OpinionEvent(
            event_key="high", title="b", summary="", category="c",
            risk_level="low", sentiment="neutral", heat_score=90.0, source_count=1,
        )
        self.assertEqual([e.event_key for e in sort_events([low, high])], ["high", "low"])


class SentimentRiskUsesHeatRankTest(unittest.TestCase):
    """风险加权里的"综合热度较高"：绝对阈值 150 对 weibo（中位数 3）永远不可能触发。"""

    def test_top_ranked_weibo_note_gets_the_high_heat_risk_bump(self) -> None:
        note = _note("w1", platform="weibo", heat_score=9.0, heat_rank=96.0)
        analyze_notes_sentiment_and_risk([note])
        self.assertIn("综合热度较高", note.risk_reasons)

    def test_long_tail_note_does_not_get_the_bump_despite_a_huge_raw_heat_score(self) -> None:
        note = _note("x1", platform="xhs", heat_score=12000.0, heat_rank=20.0)
        analyze_notes_sentiment_and_risk([note])
        self.assertNotIn("综合热度较高", note.risk_reasons)

    def test_unranked_note_falls_back_to_the_absolute_threshold(self) -> None:
        note = _note("x1", platform="xhs", heat_score=400.0, heat_rank=0.0)
        analyze_notes_sentiment_and_risk([note])
        self.assertIn("综合热度较高", note.risk_reasons)


class ChatServiceSortsByHeatRankTest(unittest.TestCase):
    """对话检索的 top-N 也是选择，不是展示。"""

    def setUp(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
        self.addCleanup(self.db.close)

    def _add(self, platform: str, heat_score: float, heat_rank: float, title: str) -> None:
        raw = RawPost(platform=platform, external_id=title, title=title)
        self.db.add(raw)
        self.db.flush()
        self.db.add(
            ProcessedPost(
                raw_post_id=raw.id,
                platform=platform,
                note_id=f"{platform}:{raw.id}",
                title=title,
                content="宿舍热水停了",
                heat_score=heat_score,
                heat_rank=heat_rank,
            )
        )
        self.db.commit()

    def test_search_notes_are_ordered_by_heat_rank_but_still_show_heat_score(self) -> None:
        from backend.services.opinion_chat_service import OpinionChatService

        self._add("xhs", 12000.0, 20.0, "小红书长尾帖")
        self._add("weibo", 9.0, 95.0, "微博头部帖")

        service = OpinionChatService(self.db)
        notes = service._search_ranked_notes("", limit=2)

        self.assertEqual([note.title for note in notes], ["微博头部帖", "小红书长尾帖"])
        # 展示的仍是真实热度值，不是百分位。
        self.assertEqual(notes[0].heat_score, 9.0)


if __name__ == "__main__":
    unittest.main()
