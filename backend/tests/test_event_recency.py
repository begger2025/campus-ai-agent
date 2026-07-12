"""事件时效性衰减：近期舆情优先，严重性不随时间打折。

线上缺陷（2026-07-12 实测）：整条流水线**时间盲**——热度、风险、排序没有一处看 `publish_time`。
已发布事件「中大学生诽谤被开除」拿到 high / 90.0、排进前三，而它的两条帖子都发于
2021-06-18（1849 天前）。用户点开看到的是一桩五年前的处分，却被当作"当前校园舆情"。

本模块钉死四件事：

1. **时效性是算术，不是判断**：`0.5 ** (age_days / half_life)`，可解释、可复现、零 LLM。
2. **时间必须外部注入**：纯函数里不许出现 `datetime.now()`，否则测试不可重复、消融不可复现。
3. **只改排序，不改严重性**：`risk_level` / `risk_score` / `heat_score` 一个字节都不许被时间改写。
   火灾不会因为过了三个月就"没那么严重"；热度是实测量。
4. **年龄要看得见**：事件载荷带上代表时间与年龄（天），前端能显示「5 年前」而不是默默沉底。

零网络、零数据库。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from backend.agent.public_opinion_core import PublicOpinionAgentService
from backend.agent.public_opinion_core.clustering import build_event_from_group, sort_events
from backend.agent.public_opinion_core.payload_builder import build_public_event_payloads
from backend.agent.public_opinion_core.recency import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_MIN_WEIGHT,
    HALF_LIFE_ENV,
    MIN_WEIGHT_ENV,
    STRATEGY_ENV,
    age_in_days,
    annotate_events_with_recency,
    event_reference_time,
    priority_score,
    recency_config,
    recency_weight,
    severity_weight,
)
from backend.agent.public_opinion_core.schemas import AnalyzeRequest, OpinionEvent, OpinionNote


NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def note(note_id: str, publish_time: str, **kwargs) -> OpinionNote:
    payload = {
        "note_id": note_id,
        "title": f"帖子 {note_id}",
        "content": f"帖子 {note_id} 正文",
        "platform": "xhs",
        "publish_time": publish_time,
        "heat_rank": 50.0,
        "heat_score": 100.0,
    }
    payload.update(kwargs)
    return OpinionNote(**payload)


def event(key: str, risk_level: str, *, recency: float = 1.0, ranking: float = 10.0) -> OpinionEvent:
    return OpinionEvent(
        event_key=key,
        title=key,
        summary="",
        category="semantic",
        risk_level=risk_level,
        sentiment="neutral",
        heat_score=100.0,
        source_count=2,
        heat_rank=50.0,
        ranking_score=ranking,
        risk_score=50.0,
        recency_weight=recency,
    )


class ReferenceTimeTest(unittest.TestCase):
    """事件的代表时间：取成员帖的**中位数**，不取最新。

    最新（max）会被一条掉队的新帖劫持——只要有人今天转发一句五年前的旧事，整个事件就"变新"了。
    中位数需要**过半**成员是新的才会前移：它要的是"这件事现在正在被讨论"，而不是"有人刚提过一嘴"。
    离群剔除（b62abaa）落地后成员表已经干净（火灾事件跨度 938 天 → 42 天），中位数因此稳定。
    """

    def test_median_is_the_default(self) -> None:
        notes = [
            note("a", "2026-07-10 10:00:00"),
            note("b", "2021-06-18 10:00:00"),
            note("c", "2021-06-18 12:00:00"),
        ]
        self.assertEqual(event_reference_time(notes), "2021-06-18T12:00:00")

    def test_latest_strategy_is_hijacked_by_one_straggler(self) -> None:
        notes = [
            note("a", "2026-07-10 10:00:00"),
            note("b", "2021-06-18 10:00:00"),
            note("c", "2021-06-18 12:00:00"),
        ]
        self.assertEqual(
            event_reference_time(notes, strategy="latest"), "2026-07-10T10:00:00"
        )

    def test_even_member_count_takes_the_older_middle(self) -> None:
        """偶数个成员：取偏旧的那个中位——宁可低估新鲜度，不可高估。"""

        notes = [
            note("a", "2026-01-01 00:00:00"),
            note("b", "2026-01-03 00:00:00"),
            note("c", "2026-01-05 00:00:00"),
            note("d", "2026-01-07 00:00:00"),
        ]
        self.assertEqual(event_reference_time(notes), "2026-01-03T00:00:00")

    def test_falls_back_to_publish_date_when_time_missing(self) -> None:
        notes = [note("a", "", publish_date="2026-03-24")]
        self.assertEqual(event_reference_time(notes), "2026-03-24T00:00:00")

    def test_no_timestamp_at_all_returns_empty(self) -> None:
        self.assertEqual(event_reference_time([note("a", "")]), "")
        self.assertEqual(event_reference_time([]), "")


class DecayArithmeticTest(unittest.TestCase):
    """衰减是纯算术：0.5 ** (age / half_life)。答辩要答得出"为什么是 0.084"。"""

    def test_age_in_days_uses_injected_now(self) -> None:
        self.assertAlmostEqual(age_in_days("2026-07-05T12:00:00", NOW), 7.0, places=6)

    def test_age_of_unknown_timestamp_is_none(self) -> None:
        self.assertIsNone(age_in_days("", NOW))

    def test_fresh_event_keeps_full_weight(self) -> None:
        self.assertEqual(recency_weight(0.0, half_life_days=21.0), 1.0)

    def test_one_half_life_halves_the_weight(self) -> None:
        self.assertAlmostEqual(recency_weight(21.0, half_life_days=21.0), 0.5, places=9)

    def test_two_half_lives_quarter_the_weight(self) -> None:
        self.assertAlmostEqual(recency_weight(42.0, half_life_days=21.0), 0.25, places=9)

    def test_future_timestamp_is_clamped_to_full_weight(self) -> None:
        """爬虫/平台偶尔给出未来时间戳，不许让它拿到 > 1 的权重。"""

        self.assertEqual(recency_weight(-30.0, half_life_days=21.0), 1.0)

    def test_unknown_age_keeps_full_weight(self) -> None:
        """没有时间戳 ≠ 很旧：不知道就不打折（同 platform_weights 的口径：不凭空沉底）。"""

        self.assertEqual(recency_weight(None, half_life_days=21.0), 1.0)

    def test_ancient_event_hits_the_underflow_floor_but_never_zero(self) -> None:
        """1849 天（中大诽谤事件）：权重塌到地板价，但**不是 0**——否则排序在陈旧事件之间全平。"""

        weight = recency_weight(1849.0, half_life_days=21.0, min_weight=DEFAULT_MIN_WEIGHT)
        self.assertEqual(weight, DEFAULT_MIN_WEIGHT)
        self.assertGreater(weight, 0.0)

    def test_stale_events_below_the_floor_still_order_by_severity(self) -> None:
        """地板之下（> 20 个半衰期）不再按年龄区分：都一样古老，按严重性/热度排。"""

        ancient_high = priority_score("high", DEFAULT_MIN_WEIGHT)
        ancient_low = priority_score("low", DEFAULT_MIN_WEIGHT)
        self.assertGreater(ancient_high, ancient_low)

    def test_half_life_zero_disables_decay(self) -> None:
        """半衰期 <= 0 = 关掉时效性（消融实验的对照臂 / 答辩现场的开关）。"""

        self.assertEqual(recency_weight(1849.0, half_life_days=0.0), 1.0)

    def test_documented_example_is_reproducible(self) -> None:
        """设计文档里写死的那个例子：107 天、半衰期 30 天 -> 0.5 ** (107/30) = 0.084。"""

        self.assertAlmostEqual(recency_weight(107.0, half_life_days=30.0), 0.0844, places=4)


class SeverityIsNotDecayedTest(unittest.TestCase):
    """严重性与时效性是**两根轴**：宿舍火灾不会因为过了三个月就不严重了。"""

    def test_annotation_never_touches_risk_or_heat(self) -> None:
        stale = event("stale", "high")
        stale.event_time = "2021-06-18T12:00:00"
        before = (stale.risk_level, stale.risk_score, stale.heat_score, stale.heat_rank, stale.ranking_score)

        annotate_events_with_recency([stale], now=NOW, half_life_days=21.0)

        after = (stale.risk_level, stale.risk_score, stale.heat_score, stale.heat_rank, stale.ranking_score)
        self.assertEqual(before, after)
        # 时效性以**独立字段**出现，不是任何既有字段的修改。
        self.assertLess(stale.recency_weight, 0.01)
        self.assertGreater(stale.age_days, 1800)

    def test_annotation_is_pure_in_time(self) -> None:
        """同一个 now 跑两次拿到同一份结果；换个 now 才变——纯函数，可复现。"""

        one = event("e", "medium")
        one.event_time = "2026-06-12T12:00:00"
        annotate_events_with_recency([one], now=NOW, half_life_days=21.0)
        first = one.recency_weight

        two = event("e", "medium")
        two.event_time = "2026-06-12T12:00:00"
        annotate_events_with_recency([two], now=NOW, half_life_days=21.0)
        self.assertEqual(first, two.recency_weight)

        three = event("e", "medium")
        three.event_time = "2026-06-12T12:00:00"
        annotate_events_with_recency([three], now=NOW + timedelta(days=30), half_life_days=21.0)
        self.assertLess(three.recency_weight, first)


class PriorityRankingTest(unittest.TestCase):
    """排序（且**只有**排序）吃时效性。"""

    def test_severity_weight_is_monotone_in_level(self) -> None:
        self.assertGreater(severity_weight("high"), severity_weight("medium"))
        self.assertGreater(severity_weight("medium"), severity_weight("low"))

    def test_five_year_old_high_risk_event_loses_to_a_fresh_medium(self) -> None:
        """线上缺陷的回归钉子：「中大学生诽谤被开除」（2021-06-18，high/90）不许再压住本周的事件。"""

        stale = event("中大学生诽谤被开除", "high", ranking=80.0)
        stale.event_time = "2021-06-18T12:00:00"
        fresh = event("本周食堂涨价争议", "medium", ranking=20.0)
        fresh.event_time = "2026-07-09T12:00:00"

        annotate_events_with_recency([stale, fresh], now=NOW, half_life_days=21.0)
        ordered = sort_events([stale, fresh])

        self.assertEqual(ordered[0].event_key, "本周食堂涨价争议")
        self.assertEqual(ordered[1].event_key, "中大学生诽谤被开除")
        # 但它的严重性一个字节没变：它依然是 high。
        self.assertEqual(stale.risk_level, "high")

    def test_same_age_keeps_severity_first_ordering(self) -> None:
        """同龄事件之间，排序退化回原口径：风险等级优先，同风险按 ranking_score。"""

        high = event("high", "high", ranking=1.0)
        medium = event("medium", "medium", ranking=99.0)
        for item in (high, medium):
            item.event_time = "2026-07-01T12:00:00"

        annotate_events_with_recency([high, medium], now=NOW, half_life_days=21.0)
        ordered = sort_events([high, medium])

        self.assertEqual([item.event_key for item in ordered], ["high", "medium"])

    def test_unannotated_events_sort_exactly_as_before(self) -> None:
        """未标注时效性的事件（recency_weight 默认 1.0）：排序与改造前逐位相同。"""

        events = [
            event("low-hot", "low", ranking=99.0),
            event("high-cold", "high", ranking=1.0),
            event("medium-hot", "medium", ranking=50.0),
        ]
        ordered = sort_events(events)
        self.assertEqual(
            [item.event_key for item in ordered], ["high-cold", "medium-hot", "low-hot"]
        )

    def test_priority_score_is_the_materialized_sort_key(self) -> None:
        fresh = event("fresh", "low")
        fresh.event_time = "2026-07-12T12:00:00"
        annotate_events_with_recency([fresh], now=NOW, half_life_days=21.0)
        self.assertAlmostEqual(
            fresh.priority_score, severity_weight("low") * fresh.recency_weight, places=9
        )


class EventTimeFromMembersTest(unittest.TestCase):
    """事件的代表时间在**造事件时**就算好（规则/语义两条路径共用 build_event_from_group）。"""

    def test_build_event_from_group_sets_event_time(self) -> None:
        notes = [
            note("a", "2021-06-18 10:00:00"),
            note("b", "2021-06-18 12:00:00"),
        ]
        built = build_event_from_group("k", "中大学生诽谤被开除", "semantic", notes)

        # 两条成员帖（偶数）：中位取偏旧的那个——宁可低估新鲜度，不可高估。
        self.assertEqual(built.event_time, "2021-06-18T10:00:00")
        # first/last 仍然是全跨度（前端要能画出"从哪天到哪天"）。
        self.assertEqual(built.first_seen_at, "2021-06-18 10:00:00")
        self.assertEqual(built.last_seen_at, "2021-06-18 12:00:00")
        # 未标注前不打折。
        self.assertEqual(built.recency_weight, 1.0)


class ServiceRecencyTest(unittest.TestCase):
    """服务层：now 可注入；事件按时效性重排；降级信息进 run_log。"""

    ROWS = [
        {
            "id": 1, "processed_post_id": 1, "note_id": "xhs:old1", "platform": "xhs",
            "title": "中大学生诽谤同学被开除学籍", "content": "中大学生诽谤同学被开除学籍，校方通报处分决定",
            "publish_time": "2021-06-18 10:00:00", "like_count": 900, "heat_rank": 90.0,
        },
        {
            "id": 2, "processed_post_id": 2, "note_id": "xhs:old2", "platform": "xhs",
            "title": "中大诽谤开除处分通报", "content": "中大学生诽谤同学 被开除学籍 处分通报",
            "publish_time": "2021-06-18 12:00:00", "like_count": 800, "heat_rank": 88.0,
        },
        {
            "id": 3, "processed_post_id": 3, "note_id": "xhs:new1", "platform": "xhs",
            "title": "食堂涨价了", "content": "食堂价格又涨了 窗口套餐贵了两块",
            "publish_time": "2026-07-09 10:00:00", "like_count": 10, "heat_rank": 20.0,
        },
        {
            "id": 4, "processed_post_id": 4, "note_id": "xhs:new2", "platform": "xhs",
            "title": "食堂价格反馈", "content": "食堂价格上涨 希望公开定价说明",
            "publish_time": "2026-07-10 10:00:00", "like_count": 8, "heat_rank": 18.0,
        },
    ]

    def test_service_accepts_injected_now_and_annotates_events(self) -> None:
        result = PublicOpinionAgentService().analyze_from_rows(
            self.ROWS,
            AnalyzeRequest(limit=10),
            now=NOW,
            recency_half_life_days=21.0,
        )

        self.assertTrue(result.events)
        for item in result.events:
            self.assertTrue(item.event_time, f"{item.title} 没有代表时间")
            self.assertIsNotNone(item.age_days)
        ages = {item.title: item.age_days for item in result.events}
        self.assertTrue(any(age > 1800 for age in ages.values()), ages)

        # 排序：近期事件在前（五年前的事件不许再排第一）。
        self.assertLess(result.events[0].age_days, 30, [(e.title, e.age_days) for e in result.events])
        extra = result.run_log.extra
        self.assertEqual(extra["recency_half_life_days"], 21.0)

    def test_service_recency_can_be_disabled(self) -> None:
        """半衰期 0 = 关掉衰减：权重全 1.0，排序回到"风险优先"的老口径。"""

        result = PublicOpinionAgentService().analyze_from_rows(
            self.ROWS,
            AnalyzeRequest(limit=10),
            now=NOW,
            recency_half_life_days=0.0,
        )
        for item in result.events:
            self.assertEqual(item.recency_weight, 1.0)


class PayloadCarriesAgeTest(unittest.TestCase):
    """UI 诚实：载荷必须带得动"这件事有多老"，否则前端只能默默把旧事件展示成新闻。"""

    def test_public_event_payload_carries_event_time(self) -> None:
        stale = event("stale", "high")
        stale.event_time = "2021-06-18T12:00:00"
        stale.first_seen_at = "2021-06-18 10:00:00"
        stale.last_seen_at = "2021-06-18 12:00:00"
        annotate_events_with_recency([stale], now=NOW, half_life_days=21.0)

        from backend.agent.public_opinion_core.schemas import AgentRunLogPayload, AnalyzeResult

        result = AnalyzeResult(
            request=AnalyzeRequest(), events=[stale], run_log=AgentRunLogPayload()
        )
        payload = build_public_event_payloads(result)[0]
        date_range = json.loads(payload["date_range_json"])

        self.assertEqual(date_range["event_time"], "2021-06-18T12:00:00")
        self.assertEqual(date_range["first_seen_at"], "2021-06-18 10:00:00")
        self.assertEqual(date_range["last_seen_at"], "2021-06-18 12:00:00")
        # 热度是实测量：不许被时效性改写。
        self.assertEqual(payload["heat_score"], 100.0)
        self.assertEqual(payload["risk_level"], "high")

    def test_age_and_weight_are_not_frozen_into_the_database(self) -> None:
        """age_days / recency_weight 是 now 的函数，落库就会腐坏——只存 event_time，读时现算。"""

        stale = event("stale", "high")
        stale.event_time = "2021-06-18T12:00:00"
        annotate_events_with_recency([stale], now=NOW, half_life_days=21.0)

        from backend.agent.public_opinion_core.schemas import AgentRunLogPayload, AnalyzeResult

        result = AnalyzeResult(
            request=AnalyzeRequest(), events=[stale], run_log=AgentRunLogPayload()
        )
        payload = build_public_event_payloads(result)[0]
        date_range = json.loads(payload["date_range_json"])
        self.assertNotIn("age_days", date_range)
        self.assertNotIn("recency_weight", date_range)


class RecencyConfigTest(unittest.TestCase):
    """半衰期必须能从 .env 调（campus 舆情衰减很快，14–30 天是可辩护的区间）。"""

    def test_defaults(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False) as _env:
            for key in (HALF_LIFE_ENV, MIN_WEIGHT_ENV, STRATEGY_ENV):
                _env.pop(key, None)
            config = recency_config()
        self.assertEqual(config["half_life_days"], DEFAULT_HALF_LIFE_DAYS)
        self.assertEqual(config["min_weight"], DEFAULT_MIN_WEIGHT)
        self.assertEqual(config["strategy"], "median")

    def test_env_override(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {HALF_LIFE_ENV: "14", MIN_WEIGHT_ENV: "0.001", STRATEGY_ENV: "latest"},
        ):
            config = recency_config()
        self.assertEqual(config["half_life_days"], 14.0)
        self.assertEqual(config["min_weight"], 0.001)
        self.assertEqual(config["strategy"], "latest")

    def test_broken_config_falls_back_to_defaults(self) -> None:
        """配置写坏不许把流水线炸掉（同 HEAT_PLATFORM_WEIGHTS 的降级口径）。"""

        with mock.patch.dict(
            "os.environ",
            {HALF_LIFE_ENV: "abc", MIN_WEIGHT_ENV: "-1", STRATEGY_ENV: "newest"},
        ):
            config = recency_config()
        self.assertEqual(config["half_life_days"], DEFAULT_HALF_LIFE_DAYS)
        self.assertEqual(config["min_weight"], DEFAULT_MIN_WEIGHT)
        self.assertEqual(config["strategy"], "median")


if __name__ == "__main__":
    unittest.main()
