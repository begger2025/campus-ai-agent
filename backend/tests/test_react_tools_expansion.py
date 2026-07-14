"""ReAct 工具扩容：研判下钻 / 发帖趋势 / 情绪分布。

## 为什么

原有 4 个工具（搜帖/热点/风险/概览）只能横着看，竖着问就答不动：
「EVT-49 为什么是中风险」「宿舍话题最近在涨吗」「大家情绪怎么样」——
这些数据全在读模型里躺着（四轴分解/风险依据/生命周期理由/发帖时间/规则情绪），
差的只是让 ReAct 够得着。

三个新工具全是**算术封装**：不新增 LLM 调用、不新增依赖，返回库里的事实。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.agent.public_opinion_core.schemas import OpinionEvent, OpinionNote
from backend.services.opinion_chat_service import OpinionChatService


def _note(note_id: str, days_ago: float, sentiment: str = "neutral") -> OpinionNote:
    # 相对 now 而不是固定日期：trend 工具按"距今几天"分桶，锚死日期的夹具一周后就红
    publish = datetime.now() - timedelta(days=days_ago)
    return OpinionNote(
        note_id=note_id,
        title=f"帖子{note_id}",
        content="内容",
        publish_time=publish.isoformat(),
        sentiment=sentiment,
        heat_score=10.0,
    )


def _event() -> OpinionEvent:
    return OpinionEvent(
        event_key="sem:evt",
        title="东校区宿舍搬迁",
        summary="搬迁讨论。",
        category="campus",
        risk_level="medium",
        risk_score=62.0,
        sentiment="negative",
        heat_score=1150.0,
        source_count=6,
        risk_reasons=["搬迁通知仓促，学生诉求未被回应"],
        lifecycle="escalating",
        lifecycle_judgement="ongoing",
        lifecycle_reason="学校尚未给出明确时间表",
        growth={"growing": True, "recent_notes": 4, "total_notes": 6},
        priority_score=1.95,
        recency_weight=0.108,
        concerns=["行李安置", "时间表不明"],
        representative_notes=[_note("r1", 2.0)],
        extra={"event_id": 49},
    )


class _StubService(OpinionChatService):
    def __init__(self, events=None, notes=None):
        self.db = None
        self._notes_cache = {}
        self._stub_events = events or []
        self._stub_notes = notes or []

    def _events(self, keyword: str = "", limit: int = 8):
        return self._stub_events

    def _notes(self, keyword: str = ""):
        return self._stub_notes


class EventDetailToolTests(unittest.TestCase):
    def _run(self, service, name, payload):
        return service._react_tools()[name].run(payload)

    def test_new_tools_are_registered_with_descriptions(self) -> None:
        tools = _StubService()._react_tools()

        for name in ("event_detail", "trend", "sentiment_breakdown"):
            self.assertIn(name, tools, f"工具 {name} 必须注册进 ReAct")
            self.assertTrue(tools[name].description, "没有描述 LLM 就不知道什么时候该用它")

    def test_event_detail_returns_the_judgement_evidence_chain(self) -> None:
        service = _StubService(events=[_event()])

        result = self._run(service, "event_detail", {"keyword": "宿舍搬迁"})

        detail = result["event"]
        self.assertEqual(detail["title"], "东校区宿舍搬迁")
        self.assertEqual(detail["risk_level"], "medium")
        self.assertEqual(detail["risk_reasons"], ["搬迁通知仓促，学生诉求未被回应"], "「凭什么中风险」的依据必须带上")
        self.assertEqual(detail["lifecycle"], "escalating")
        self.assertEqual(detail["lifecycle_reason"], "学校尚未给出明确时间表")
        self.assertTrue(detail["growth"]["growing"], "增长证据是「凭什么标持续发酵」的测量部分")
        self.assertEqual(detail["priority_score"], 1.95)

    def test_event_detail_with_no_match_says_so(self) -> None:
        service = _StubService(events=[])

        result = self._run(service, "event_detail", {"keyword": "不存在"})

        self.assertEqual(result["count"], 0)

    def test_trend_counts_recent_versus_baseline(self) -> None:
        # 窗口 14 天：近半 4 条、前半 1 条 → growing；窗口外的老帖不计入。
        notes = [_note("a", 1), _note("b", 2), _note("c", 3), _note("d", 5), _note("e", 10), _note("old", 400)]
        service = _StubService(notes=notes)

        result = self._run(service, "trend", {"keyword": "宿舍", "days": 14})

        self.assertEqual(result["window_days"], 14)
        self.assertEqual(result["recent_half"], 4)
        self.assertEqual(result["earlier_half"], 1)
        self.assertTrue(result["growing"])
        self.assertEqual(result["total_in_window"], 5)

    def test_trend_without_timestamps_is_honest(self) -> None:
        note = OpinionNote(note_id="x", title="无时间戳", content="", publish_time="")
        service = _StubService(notes=[note])

        result = self._run(service, "trend", {"keyword": "宿舍"})

        self.assertEqual(result["total_in_window"], 0)
        self.assertFalse(result["growing"], "没有任何可解析时间时不许编造增长")

    def test_sentiment_breakdown_counts_by_rule_sentiment(self) -> None:
        notes = [
            _note("a", 1, "negative"),
            _note("b", 1, "negative"),
            _note("c", 1, "neutral"),
            _note("d", 1, "positive"),
        ]
        service = _StubService(notes=notes)

        result = self._run(service, "sentiment_breakdown", {"keyword": "食堂"})

        self.assertEqual(result["distribution"], {"negative": 2, "neutral": 1, "positive": 1})
        self.assertEqual(result["total"], 4)


if __name__ == "__main__":
    unittest.main()
