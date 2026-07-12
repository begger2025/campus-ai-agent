"""智能选题的第四路信号：**事件流水线**（纯算术，零 LLM、零 IO、now 注入）。

缺陷：选题 planner 从来没听说过"事件"。它的候选池只有两个来源——用户问过什么
（ChatQueryLog）和已经爬回来什么（ProcessedPost 标签）。于是系统一边把
「中大杰青实名举报」判成 high(91) / 悬而未决 / 全库第一优先级，一边让选题器
继续推荐「食堂」。左手不知道右手。

本文件钉死**算术那一半**：事件的严重性、生命周期、时效性**都已经算好并落库了**
（severity_weight / lifecycle_weight / recency_weight -> priority_score），把它们接进
planner 是**接线，不是智能**。这里一个 LLM 都不许出现。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.agent.public_opinion_core.keyword_planner import (
    W_EVENT,
    ContentStat,
    EventRecord,
    QueryRecord,
    event_priority,
    plan_keywords,
)

NOW = datetime(2026, 7, 12, 12, 0, 0)
HALF_LIFE = 21.0


def _event(
    event_id: str = "20",
    title: str = "中大杰青实名举报",
    *,
    risk_level: str = "high",
    lifecycle: str = "ongoing",
    days_ago: float = 67.0,
    keywords: list[str] | None = None,
    generated: list[str] | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        title=title,
        risk_level=risk_level,
        lifecycle=lifecycle,
        event_time=NOW - timedelta(days=days_ago),
        keywords=list(keywords or []),
        generated_keywords=list(generated or []),
    )


def _by_kw(suggestions) -> dict:
    return {s.keyword: s for s in suggestions}


class EventPriorityArithmeticTest(unittest.TestCase):
    """priority = severity_weight × recency_weight × lifecycle_weight —— 复用事件侧现成的算术。"""

    def test_priority_reuses_the_existing_three_factors(self) -> None:
        event = _event(days_ago=21.0)  # 恰好一个半衰期 -> recency 0.5
        # high=9 × 0.5 × ongoing=2 = 9.0
        self.assertAlmostEqual(
            event_priority(event, NOW, half_life_days=HALF_LIFE), 9.0, places=6
        )

    def test_resolved_event_is_worth_a_quarter_of_an_ongoing_one(self) -> None:
        ongoing = _event(days_ago=21.0, lifecycle="ongoing")
        resolved = _event(days_ago=21.0, lifecycle="resolved")
        self.assertAlmostEqual(
            event_priority(ongoing, NOW, half_life_days=HALF_LIFE)
            / event_priority(resolved, NOW, half_life_days=HALF_LIFE),
            4.0,
            places=6,
        )

    def test_event_without_timestamp_is_not_punished_for_unknown_age(self) -> None:
        # 「不知道多老」≠「很老」（同 recency_weight 的口径）：权重 1.0，不许凭空沉底。
        event = _event(risk_level="low", lifecycle="")
        event.event_time = None
        self.assertAlmostEqual(event_priority(event, NOW, half_life_days=HALF_LIFE), 1.0)


class EventSignalEntersCandidatePoolTest(unittest.TestCase):
    def test_event_tag_keyword_enters_the_pool_and_scores(self) -> None:
        suggestions = plan_keywords(
            [], [], {}, now=NOW, events=[_event(keywords=["学术"])],
            event_half_life_days=HALF_LIFE,
        )
        by_kw = _by_kw(suggestions)
        self.assertIn("学术", by_kw)
        # 唯一事件 -> event_norm=1；从未爬过 -> penalty=1 => W_EVENT × 1 × 10
        self.assertAlmostEqual(by_kw["学术"].score, W_EVENT * 10.0, places=6)
        self.assertIn("event", by_kw["学术"].signals)

    def test_llm_generated_keyword_that_appears_nowhere_else_is_proposed(self) -> None:
        """「学术不端」不在任何标题、任何标签、任何用户提问里——现行 planner 结构上排不出它。"""

        event = _event(keywords=["学术"], generated=["学术不端", "杰青 举报"])
        suggestions = plan_keywords(
            [], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE
        )
        by_kw = _by_kw(suggestions)
        self.assertIn("学术不端", by_kw)
        self.assertIn("杰青 举报", by_kw)
        self.assertIn("event_llm", by_kw["学术不端"].signals)

    def test_provenance_carries_event_id_and_title_and_origin(self) -> None:
        # 只有 LLM 生成词（标签 "热点" 与它不构成包含关系，不会被合并）
        event = _event(keywords=["热点"], generated=["学术不端"])
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        refs = by_kw["学术不端"].event_refs
        self.assertEqual(len(refs), 1)
        self.assertEqual(
            refs[0],
            {
                "event_id": "20",
                "title": "中大杰青实名举报",
                "risk_level": "high",
                "lifecycle": "ongoing",
                "origin": "event_llm",
            },
        )
        # reason 必须让管理员一眼看见"凭什么推荐这个词"
        self.assertIn("中大杰青实名举报", by_kw["学术不端"].reason)
        self.assertIn("LLM 据该事件正文生成", by_kw["学术不端"].reason)
        self.assertEqual(by_kw["学术不端"].to_dict()["event_refs"], refs)

    def test_alias_merge_keeps_both_origins_on_the_merged_candidate(self) -> None:
        """标签「学术」被并入生成词「学术不端」（短词并入唯一包含它的长词）——两条出处都留着。"""

        event = _event(keywords=["学术"], generated=["学术不端"])
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertNotIn("学术", by_kw)
        origins = {ref["origin"] for ref in by_kw["学术不端"].event_refs}
        self.assertEqual(origins, {"event_tag", "event_llm"})
        self.assertEqual(by_kw["学术不端"].signals, ["event", "event_llm"])

    def test_top_event_gets_event_norm_one_and_lesser_events_scale_down(self) -> None:
        top = _event("20", "中大杰青实名举报", risk_level="high", lifecycle="ongoing",
                     days_ago=21.0, generated=["学术不端"])          # 9 × 0.5 × 2 = 9.0
        minor = _event("25", "中大火箭试验成功", risk_level="low", lifecycle="not_applicable",
                       days_ago=21.0, generated=["火箭试验"])        # 1 × 0.5 × 0.5 = 0.25
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[top, minor], event_half_life_days=HALF_LIFE)
        )
        self.assertAlmostEqual(by_kw["学术不端"].score, W_EVENT * 1.0 * 10.0, places=6)
        # 0.25 / 9.0 = 0.02777…
        self.assertAlmostEqual(
            by_kw["火箭试验"].score, W_EVENT * (0.25 / 9.0) * 10.0, places=6
        )
        self.assertGreater(by_kw["学术不端"].score, by_kw["火箭试验"].score)

    def test_a_word_on_two_events_takes_the_most_urgent_one_not_the_sum(self) -> None:
        """求 max 不求和：三个瞌睡事件加起来也不许压过头号丑闻。"""

        top = _event("20", "举报", risk_level="high", lifecycle="ongoing", days_ago=21.0,
                     generated=["宿舍搬迁"])
        sleepy = [
            _event(str(i), f"闲聊{i}", risk_level="low", lifecycle="resolved",
                   days_ago=21.0, generated=["宿舍搬迁"])
            for i in range(3)
        ]
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[top, *sleepy],
                          event_half_life_days=HALF_LIFE)
        )
        self.assertAlmostEqual(by_kw["宿舍搬迁"].score, W_EVENT * 10.0, places=6)


class TagWeightTest(unittest.TestCase):
    """事件内部并非所有标签都同样"是这件事"。

    消融实测（2026-07-12）打脸的地方：头号事件「中大杰青实名举报」的 top_tags 是
    学术(3)/热点(1)/新闻(1)/社会新闻(1)/学术论文(1)/医学(1)/**上海(1)**/**广州(1)**…
    若整个事件的所有标签都吃同一个 event_norm=1.0，那么「上海」「广州」「新闻」会和
    「学术不端」**并列 3.00 分**——把一份垃圾推荐顶到首屏。

    修法是**算术，不是黑名单**：`top_tags_json` 里本来就存着 count（几条成员帖带这个标签）。
    3 条帖子都带「学术」，只有 1 条带「上海」——前者才是这件事的特征。权重 = count / max_count。
    LLM 生成词不吃这个折扣：它是被**当作检索词提出来的**，不是被顺手打上的标签。
    """

    def test_a_tag_on_one_post_is_worth_less_than_a_tag_on_three(self) -> None:
        event = _event(
            keywords=["学术", "上海"],
            generated=["学术不端"],
        )
        event.keyword_weights = {"学术": 1.0, "上海": 1.0 / 3.0}
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertAlmostEqual(by_kw["学术不端"].score, W_EVENT * 10.0, places=6)
        self.assertAlmostEqual(by_kw["上海"].score, W_EVENT * 10.0 / 3.0, places=6)
        self.assertGreater(by_kw["学术不端"].score, by_kw["上海"].score)

    def test_missing_weight_defaults_to_full(self) -> None:
        event = _event(keywords=["学术"])  # 没有 keyword_weights
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertAlmostEqual(by_kw["学术"].score, W_EVENT * 10.0, places=6)


class DegradationTest(unittest.TestCase):
    """没有事件 = 这一路信号什么都不说：分数**逐位**回到改造前。"""

    def test_no_events_leaves_every_score_bit_for_bit_identical(self) -> None:
        queries = [QueryRecord("宿舍空调", NOW - timedelta(days=1), hit_count=0)]
        contents = [ContentStat("食堂", 500, NOW - timedelta(days=3))]
        crawled = {"食堂": NOW - timedelta(days=3)}

        before = plan_keywords(queries, contents, crawled, now=NOW)
        after = plan_keywords(queries, contents, crawled, now=NOW, events=[])

        self.assertEqual(
            [(s.keyword, s.score, s.signals) for s in before],
            [(s.keyword, s.score, s.signals) for s in after],
        )
        # 且与改造前的手算值一致：宿舍空调 (0.5+0.3)×1×10 = 8.0；食堂 0.2×1×0.3×10 = 0.6
        by_kw = _by_kw(after)
        self.assertAlmostEqual(by_kw["宿舍空调"].score, 8.0, places=6)
        self.assertAlmostEqual(by_kw["食堂"].score, 0.6, places=6)
        self.assertEqual(by_kw["宿舍空调"].event_refs, [])

    def test_event_arm_never_deflates_the_existing_three_signals(self) -> None:
        """新增的是**第四个加项**，不是把老三路重新归一化——否则没有事件的部署会凭空掉 30% 分。"""

        queries = [QueryRecord("宿舍空调", NOW - timedelta(days=1), hit_count=0)]
        with_event = plan_keywords(
            queries, [], {}, now=NOW, events=[_event(generated=["学术不端"])],
            event_half_life_days=HALF_LIFE,
        )
        by_kw = _by_kw(with_event)
        self.assertAlmostEqual(by_kw["宿舍空调"].score, 8.0, places=6)  # 一分不少


class CrawlPenaltyTensionTest(unittest.TestCase):
    """「昨天刚爬过」 vs 「这是头号未决丑闻」——爬取降权到底该不该压住事件信号。"""

    def test_live_event_is_not_suppressed_by_a_recent_crawl(self) -> None:
        """悬而未决 / 持续发酵：新帖**还在来**，「我们昨天爬过」是关于**存量**的陈述，不是关于新证据的。"""

        event = _event(lifecycle="ongoing", generated=["学术不端"])
        by_kw = _by_kw(
            plan_keywords(
                [], [], {"学术不端": NOW - timedelta(days=1)},
                now=NOW, events=[event], event_half_life_days=HALF_LIFE,
            )
        )
        # 事件项不吃 ×0.3：3.0 而不是 0.9
        self.assertAlmostEqual(by_kw["学术不端"].score, W_EVENT * 10.0, places=6)
        self.assertIn("仍在发酵", by_kw["学术不端"].reason)

    def test_resolved_event_inherits_the_ordinary_crawl_penalty(self) -> None:
        """已了结：不会再有新帖，「昨天刚爬过」就是真的"我们已经有数据了"——照常降权。"""

        event = _event(lifecycle="resolved", generated=["宿舍火情"])
        by_kw = _by_kw(
            plan_keywords(
                [], [], {"宿舍火情": NOW - timedelta(days=1)},
                now=NOW, events=[event], event_half_life_days=HALF_LIFE,
            )
        )
        self.assertAlmostEqual(by_kw["宿舍火情"].score, W_EVENT * 10.0 * 0.3, places=6)

    def test_barren_keyword_stays_barren_even_for_the_top_event(self) -> None:
        """贫瘠是关于**这个词**的证据（搜了它、什么都没捞到），事件再急也改不了这一点。"""

        event = _event(lifecycle="escalating", generated=["学术不端"])
        by_kw = _by_kw(
            plan_keywords(
                [], [], {"学术不端": NOW - timedelta(days=1)},
                now=NOW, events=[event], event_half_life_days=HALF_LIFE,
                barren_keywords={"学术不端"},
            )
        )
        self.assertAlmostEqual(by_kw["学术不端"].score, W_EVENT * 10.0 * 0.1, places=6)
        self.assertIn("无相关内容", by_kw["学术不端"].reason)


class HygieneTest(unittest.TestCase):
    """事件送来的词走**同一套**卫生规则：LLM 说「校园生活」，和用户说「校园生活」一样被拒。"""

    def test_generic_llm_keyword_is_rejected_by_the_same_blacklist(self) -> None:
        event = _event(generated=["校园生活", "中山大学", "学术不端"])
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertNotIn("校园生活", by_kw)
        self.assertNotIn("中山大学", by_kw)
        self.assertIn("学术不端", by_kw)

    def test_school_prefix_is_stripped_not_wasted(self) -> None:
        """爬虫会自己拼「中山大学」（CRAWL_TOPIC_QUALIFIER），关键词里再带一遍是浪费。"""

        event = _event(generated=["中山大学 学术不端", "中大 杰青 举报"])
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertIn("学术不端", by_kw)
        self.assertIn("杰青 举报", by_kw)

    def test_overlong_llm_keyword_is_rejected(self) -> None:
        event = _event(generated=["中大杰青被实名举报涉嫌论文数据造假一事", "学术不端"])
        by_kw = _by_kw(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE)
        )
        self.assertEqual(list(by_kw), ["学术不端"])

    def test_event_with_all_keywords_rejected_contributes_nothing(self) -> None:
        event = _event(keywords=["校园"], generated=["日常", "分享"])
        self.assertEqual(
            plan_keywords([], [], {}, now=NOW, events=[event], event_half_life_days=HALF_LIFE),
            [],
        )


if __name__ == "__main__":
    unittest.main()
