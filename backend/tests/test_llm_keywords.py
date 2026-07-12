"""LLM 从事件生成检索词——**规则结构上做不到的那一半**。

「中大杰青实名举报」应该让系统想去爬「学术不端」。可 **「学术不端」不出现在任何标题、
任何标签、任何用户提问里**（实测：该事件的 top_tags 是 学术/热点/新闻/社会新闻/上海/广州）。
现行 planner 只能给**字面上已经出现过**的词排序，所以它**永远**提不出这个词。
这不是一条僵化的规则，这是一条**生不出语言**的规则——这才是 LLM 真正该站的地方。

安全边界（全部用注入的假 proposer 测，零网络、零 DB）：
  - 模型的产物必须过 planner 现有的卫生规则（normalize_keyword / GENERIC_BLACKLIST /
    MAX_KEYWORD_LEN）：LLM 说「校园生活」和用户说「校园生活」一样被拒；
  - 模型不可用 / 抛异常 / 返回 None / 返回垃圾 / 全被拒 —— **逐事件**作废，记 warning，
    别的事件照常工作；
  - LLM 只在**算术已经说它重要**的那几个事件上花钱（按 priority 取 top-N）。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.agent.public_opinion_core.keyword_planner import EventRecord, plan_keywords
from backend.agent.public_opinion_core.llm_keywords import (
    DEFAULT_MAX_KEYWORDS_PER_EVENT,
    generate_event_keywords,
)

NOW = datetime(2026, 7, 12, 12, 0, 0)
HALF_LIFE = 21.0


def _event(
    event_id: str = "20",
    title: str = "中大杰青实名举报",
    *,
    risk_level: str = "high",
    lifecycle: str = "ongoing",
    days_ago: float = 21.0,
    texts: list[str] | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        title=title,
        risk_level=risk_level,
        lifecycle=lifecycle,
        event_time=NOW - timedelta(days=days_ago),
        keywords=["学术"],
        # `texts or [...]` 会把显式传入的 [] 折成默认值——这里要能测"没有正文"的分支
        texts=list(["耿同学杀疯了 继续举报中山大学另一位杰青"] if texts is None else texts),
    )


class GenerateEventKeywordsTest(unittest.TestCase):
    def test_accepted_keywords_land_on_the_event(self) -> None:
        event = _event()
        warnings: list[str] = []
        stats = generate_event_keywords(
            [event],
            lambda title, texts, risk, lifecycle: ["学术不端", "杰青 举报"],
            now=NOW,
            half_life_days=HALF_LIFE,
            warnings=warnings,
        )
        self.assertEqual(event.generated_keywords, ["学术不端", "杰青 举报"])
        self.assertEqual((stats["accepted"], stats["rejected"], stats["events"]), (2, 0, 1))
        self.assertEqual(warnings, [])

    def test_the_proposer_sees_title_texts_risk_and_lifecycle(self) -> None:
        seen: list[tuple] = []

        def proposer(title, texts, risk, lifecycle):
            seen.append((title, tuple(texts), risk, lifecycle))
            return ["学术不端"]

        generate_event_keywords(
            [_event()], proposer, now=NOW, half_life_days=HALF_LIFE, warnings=[]
        )
        self.assertEqual(
            seen,
            [("中大杰青实名举报", ("耿同学杀疯了 继续举报中山大学另一位杰青",), "high", "ongoing")],
        )

    def test_dict_shaped_output_is_accepted(self) -> None:
        event = _event()
        generate_event_keywords(
            [event],
            lambda *_: {"keywords": ["学术不端"]},
            now=NOW, half_life_days=HALF_LIFE, warnings=[],
        )
        self.assertEqual(event.generated_keywords, ["学术不端"])

    def test_output_is_capped_and_deduplicated(self) -> None:
        event = _event()
        stats = generate_event_keywords(
            [event],
            lambda *_: ["学术不端", "学术不端", "杰青 举报", "论文造假", "实名举报",
                        "科研诚信", "撤稿", "调查通报"],
            now=NOW, half_life_days=HALF_LIFE, warnings=[],
        )
        self.assertEqual(len(event.generated_keywords), DEFAULT_MAX_KEYWORDS_PER_EVENT)
        self.assertEqual(len(set(event.generated_keywords)), DEFAULT_MAX_KEYWORDS_PER_EVENT)
        self.assertEqual(stats["accepted"], DEFAULT_MAX_KEYWORDS_PER_EVENT)


class HygieneTest(unittest.TestCase):
    def test_generic_proposals_are_rejected_by_the_planners_own_rules(self) -> None:
        event = _event()
        warnings: list[str] = []
        stats = generate_event_keywords(
            [event],
            lambda *_: ["校园生活", "中山大学", "日常", "学术不端"],
            now=NOW, half_life_days=HALF_LIFE, warnings=warnings,
        )
        self.assertEqual(event.generated_keywords, ["学术不端"])
        self.assertEqual((stats["accepted"], stats["rejected"]), (1, 3))
        self.assertTrue(any("校园生活" in w for w in warnings), warnings)

    def test_all_rejected_means_no_keywords_and_a_warning(self) -> None:
        event = _event()
        warnings: list[str] = []
        stats = generate_event_keywords(
            [event], lambda *_: ["校园", "生活", "分享"],
            now=NOW, half_life_days=HALF_LIFE, warnings=warnings,
        )
        self.assertEqual(event.generated_keywords, [])
        self.assertEqual(stats["accepted"], 0)
        self.assertTrue(any("全部被卫生规则拒绝" in w for w in warnings), warnings)


class DegradationTest(unittest.TestCase):
    def test_no_proposer_is_a_no_op(self) -> None:
        event = _event()
        stats = generate_event_keywords(
            [event], None, now=NOW, half_life_days=HALF_LIFE, warnings=[]
        )
        self.assertEqual(event.generated_keywords, [])
        self.assertEqual(stats["events"], 0)

    def test_one_event_blowing_up_does_not_stop_the_others(self) -> None:
        boom = _event("20", "中大杰青实名举报")
        fine = _event("49", "东校区宿舍搬迁", risk_level="medium")
        warnings: list[str] = []

        def proposer(title, texts, risk, lifecycle):
            if title == "中大杰青实名举报":
                raise TimeoutError("api gateway timeout")
            return ["宿舍搬迁"]

        stats = generate_event_keywords(
            [boom, fine], proposer, now=NOW, half_life_days=HALF_LIFE, warnings=warnings
        )
        self.assertEqual(boom.generated_keywords, [])
        self.assertEqual(fine.generated_keywords, ["宿舍搬迁"])
        self.assertEqual(stats["accepted"], 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("TimeoutError", warnings[0])
        self.assertIn("中大杰青实名举报", warnings[0])

    def test_unusable_outputs_are_discarded_per_event(self) -> None:
        for raw in (None, "学术不端", 42, [], {"nope": 1}, [None, 7]):
            with self.subTest(raw=raw):
                event = _event()
                warnings: list[str] = []
                generate_event_keywords(
                    [event], lambda *_, r=raw: r,
                    now=NOW, half_life_days=HALF_LIFE, warnings=warnings,
                )
                self.assertEqual(event.generated_keywords, [])
                self.assertEqual(len(warnings), 1)

    def test_event_without_texts_is_not_sent_to_the_model(self) -> None:
        """没有正文就没有输入：不许模型只凭标题硬编（同 llm_risk 的口径）。"""

        event = _event(texts=[])
        calls: list[str] = []
        generate_event_keywords(
            [event], lambda title, *_: calls.append(title) or ["学术不端"],
            now=NOW, half_life_days=HALF_LIFE, warnings=[],
        )
        self.assertEqual(calls, [])
        self.assertEqual(event.generated_keywords, [])

    def test_a_failed_event_still_contributes_its_tag_keywords_to_the_planner(self) -> None:
        event = _event()
        generate_event_keywords(
            [event], lambda *_: None, now=NOW, half_life_days=HALF_LIFE, warnings=[]
        )
        suggestions = plan_keywords(
            [], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE
        )
        self.assertEqual([s.keyword for s in suggestions], ["学术"])  # 算术那一半照常工作


class SpendGateTest(unittest.TestCase):
    """LLM 只在**算术已经说它重要**的事件上花钱：按 priority 取 top-N。"""

    def test_only_the_top_events_by_priority_are_sent_to_the_model(self) -> None:
        top = _event("20", "中大杰青实名举报", risk_level="high", lifecycle="ongoing")
        mid = _event("49", "东校区宿舍搬迁", risk_level="medium", lifecycle="ongoing")
        junk = _event("25", "中大火箭试验成功", risk_level="low", lifecycle="not_applicable")
        calls: list[str] = []

        stats = generate_event_keywords(
            [junk, mid, top],
            lambda title, *_: calls.append(title) or ["学术不端"],
            now=NOW, half_life_days=HALF_LIFE, warnings=[], top_events=2,
        )
        self.assertEqual(calls, ["中大杰青实名举报", "东校区宿舍搬迁"])  # priority 降序
        self.assertEqual(stats["events"], 2)
        self.assertEqual(junk.generated_keywords, [])


if __name__ == "__main__":
    unittest.main()
