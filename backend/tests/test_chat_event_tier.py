"""聊天的两层检索：事件层（LLM 研判过的）优先，帖子层兜底。

## 为什么要改

改造前，舆情助手**从来不读 public_events**。它每次提问都从 processed_posts 现场重来一遍：

    LIKE '%关键词%' 字面检索  →  规则聚类（4 个写死的桶）  →  规则情绪  →  LLM 写成中文

于是所有 AI 深度工作——embedding 语义聚类、LLM 簇精修、LLM 风险研判、LLM 生命周期研判、
四轴优先级——**在聊天窗口里一样都看不见**。它们只活在事件页那条线上。

真实后果（线上）：事件页展示「东校区宿舍搬迁」medium 风险 6 条帖；用户在聊天里问同一件事，
Agent 说"未检索到代表性内容"。**两条管线看到的不是同一个世界。**

根因是字面匹配认不出同义表达。同一个搬迁事件，帖子有三种说法：

    「宿舍搬迁」  「搬宿舍」  「封闭管理」

embedding 认得出它们是一件事（离线聚成 EVT-49），LIKE '%宿舍搬迁%' 只认得第一种。

## 两层设计

    ① 事件层：published 事件里找（标题/摘要/标签/**代表帖内容**）
              命中 → 用它的 LLM 结论 + embedding 聚好的成员
    ② 帖子层：一个事件都不命中 → 回落原来的 processed_posts 检索

第①层匹配"代表帖内容"是关键：它让字面检索**传递**到语义簇。问「搬宿舍」命中代表帖，
就上浮到整个 EVT-49，连带拿到「搬迁」「封闭管理」那些字面不匹配的成员。

## 这个文件最重要的测试不是新功能，是**兜底不退化**

published 事件只有 7 个，只覆盖 26/397 条帖子。若只读事件层，问「食堂」会直接查无此事
（没有 published 的食堂事件），而现在它能查到 32 条真实食堂帖。**那不是改进，是退化。**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.event_read_model import query_published_events
from backend.services.opinion_chat_service import OpinionChatService


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


class _Fixture(unittest.TestCase):
    """一个缩小版的真实库：一个 published 搬迁事件 + 若干未成事件的食堂帖。"""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()

        # —— 搬迁事件的成员帖：三种说法，字面毫无交集 ——
        self.relocation_posts = []
        for i, (title, body) in enumerate(
            [
                ("关于中山大学东校区宿舍搬迁的看法意见", "搬迁通知太仓促。"),
                ("中大东校区搬宿舍的原因找到了", "为了管理方便搬宿舍。"),  # 只有"搬宿舍"
                ("中山大学东校区封闭管理", "东校区封闭管理通知。"),  # 连"搬"字都没有
            ]
        ):
            post = ProcessedPost(
                note_id=f"xhs:relo{i}",
                raw_post_id=10 + i,
                platform="xhs",
                title=title,
                content=body,
                source_keyword="中山大学 东校宿舍搬迁",
                heat_score=500 - i * 100,
                heat_rank=50.0,
                sentiment="negative",
                risk_level="medium",
                publish_time=NOW - timedelta(days=5 + i),
            )
            self.db.add(post)
            self.relocation_posts.append(post)

        # —— 食堂帖：真实内容，但**没有**对应的 published 事件（兜底路径必须能答） ——
        for i in range(4):
            self.db.add(
                ProcessedPost(
                    note_id=f"xhs:canteen{i}",
                    raw_post_id=100 + i,
                    platform="xhs",
                    title=f"中大食堂新品试吃会 第{i}期",
                    content="食堂窗口排队情况。",
                    source_keyword="中山大学食堂",
                    heat_score=1000 + i,
                    heat_rank=60.0,
                    sentiment="neutral",
                    risk_level="low",
                    publish_time=NOW - timedelta(days=3),
                )
            )
        self.db.commit()

        # —— published 事件：LLM 研判过的（风险=medium，判断=ongoing） ——
        self.event = PublicEvent(
            event_key="sem:45e3a7f3",  # sem: = embedding 语义聚类产出
            title="东校区宿舍搬迁",
            summary="东校区宿舍搬迁共聚合 3 条内容。",
            topic="campus",
            sentiment="negative",
            status="published",
            risk_level="medium",  # ← LLM 研判，不是规则算的
            risk_score=63.0,
            heat_score=10982.0,
            source_count=3,
            risk_reasons_json=json.dumps(["搬迁通知仓促，学生诉求未被回应"], ensure_ascii=False),
            concerns_json=json.dumps(["行李安置", "时间表不明"], ensure_ascii=False),
            top_tags_json=json.dumps([{"tag": "宿舍", "count": 3}], ensure_ascii=False),
            source_keywords_json=json.dumps(["中山大学 东校宿舍搬迁"], ensure_ascii=False),
            date_range_json=json.dumps(
                {
                    "event_time": _iso(5),
                    "member_times": [_iso(5), _iso(6), _iso(7)],
                    "lifecycle_judgement": "ongoing",
                    "lifecycle_reason": "学校尚未给出明确时间表",
                },
                ensure_ascii=False,
            ),
        )
        self.db.add(self.event)
        self.db.commit()

        for rank, post in enumerate(self.relocation_posts, start=1):
            self.db.add(
                EventPostLink(
                    event_id=self.event.id,
                    processed_post_id=post.id,
                    raw_post_id=post.raw_post_id,
                    rank=rank,
                    role="representative",
                )
            )

        # —— 规则聚类的老古董：archived，绝不能被读到 ——
        self.db.add(
            PublicEvent(
                event_key="dorm_life",  # 没有 sem: 前缀 = 规则聚类的写死桶
                title="宿舍热水与后勤维修反馈",
                summary="老数据。",
                status="archived",
                risk_level="low",
                heat_score=1.0,
                source_count=1,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()


class EventTierTests(_Fixture):
    def test_a_topic_question_reaches_the_llm_judged_event(self):
        events = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.title, "东校区宿舍搬迁")
        self.assertEqual(event.risk_level, "medium", "风险必须是 LLM 研判的值，不是规则重算的")
        self.assertEqual(event.risk_reasons, ["搬迁通知仓促，学生诉求未被回应"], "LLM 的风险依据要带上")
        self.assertEqual(event.source_count, 3)

    def test_a_synonym_lifts_through_a_representative_post_to_the_whole_cluster(self):
        """问「搬宿舍」——事件标题里没有这三个字，但它的代表帖里有。

        这是整个改造的核心：用**离线算好的 embedding 语义聚类**，弥补**在线字面检索**
        认不出同义表达的短板。命中一条代表帖 → 上浮到整个簇 → 连「封闭管理」那条也拿到。
        """

        events = query_published_events(self.db, keyword="搬宿舍", now=NOW)

        self.assertEqual(len(events), 1, "「搬宿舍」应该通过代表帖上浮到「东校区宿舍搬迁」事件")
        titles = [note.title for note in events[0].representative_notes]
        self.assertIn(
            "中山大学东校区封闭管理",
            titles,
            "上浮之后必须拿到整个语义簇——包括字面上跟「搬宿舍」毫无关系的成员",
        )

    def test_the_llm_lifecycle_judgement_survives_the_trip(self):
        """生命周期是**判断 ∧ 测量**合成的，两半都要原样传到聊天。

            LLM 判断：ongoing（学校还没给时间表，有悬而未决的事）—— 落库
            算术测量：growing（3 条成员帖全在近 7 天内，还在发酵）—— 读时现算
            合成：     escalating

        聊天必须拿到合成后的 escalating（用户该看到"还在发酵"），也必须拿得到 LLM 那一半
        的原始判断和理由（管理员要问"凭什么"）。
        """

        events = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)
        event = events[0]

        self.assertEqual(event.lifecycle_judgement, "ongoing", "LLM 判的那一半要原样带上")
        self.assertEqual(event.lifecycle_reason, "学校尚未给出明确时间表")
        self.assertEqual(
            event.lifecycle,
            "escalating",
            "ongoing（判断）∧ growing（测量）必须合成 escalating —— 合成发生在读侧，不读陈年快照",
        )
        self.assertTrue(event.growth.get("growing"), "增长证据要带上（管理员要看'凭什么标持续发酵'）")
        self.assertGreater(event.priority_score, 0, "四轴优先级要算出来")

    def test_archived_rule_clustered_events_are_never_returned(self):
        """规则聚类的老桶（dorm_life）全是 archived，绝不能混进来。"""

        events = query_published_events(self.db, keyword="宿舍", now=NOW)
        keys = [event.event_key for event in events]

        self.assertNotIn("dorm_life", keys, "规则聚类的老古董不该出现在聊天里")
        for key in keys:
            self.assertTrue(key.startswith("sem:"), f"聊天只该看到语义聚类的产物，却拿到 {key}")

    def test_source_keywords_are_not_used_for_matching(self):
        """绝不能重蹈 source_keyword 污染的覆辙——照着线上真实的污染形态复现。

        线上实况：爬虫拿「中山大学 东校宿舍搬迁」去小红书搜，小红书搜不到精确匹配，就拿
        泛泛的中大帖（灵异事件 / 97岁生日快乐）来凑数。这些帖子被盖上
        `source_keyword = 中山大学 东校宿舍搬迁`，聚成了一个**跟搬迁毫无关系**的事件，
        而这个事件的 `source_keywords_json` 里也就带上了「东校宿舍搬迁」。

        若拿 source_keywords_json 做匹配，用户问「宿舍搬迁」就会同时捞回这个灵异事件——
        "爬虫搜过这个词" ≠ "事件在讲这个词"。
        """

        noise_post = ProcessedPost(
            note_id="xhs:ghost",
            raw_post_id=900,
            platform="xhs",
            title="中山大学灵异事件",
            content="半夜听到奇怪的声音。",
            source_keyword="中山大学 东校宿舍搬迁",  # ← 爬虫搜索时用的词，帖子跟搬迁毫无关系
            heat_score=18253.0,
            heat_rank=90.0,
            sentiment="neutral",
            risk_level="low",
            publish_time=NOW - timedelta(days=4),
        )
        self.db.add(noise_post)
        self.db.commit()

        noise_event = PublicEvent(
            event_key="sem:ghost0001",
            title="中大校园灵异传闻",
            summary="校园灵异话题讨论。",
            status="published",
            risk_level="low",
            risk_score=10.0,
            heat_score=18253.0,
            source_count=1,
            # 成员是被「东校宿舍搬迁」这个搜索词捞回来的，所以聚合出的 source_keywords 带上了它
            source_keywords_json=json.dumps(["中山大学 东校宿舍搬迁"], ensure_ascii=False),
            date_range_json=json.dumps({"event_time": _iso(4), "member_times": [_iso(4)]}),
        )
        self.db.add(noise_event)
        self.db.commit()
        self.db.add(
            EventPostLink(
                event_id=noise_event.id,
                processed_post_id=noise_post.id,
                raw_post_id=noise_post.raw_post_id,
                rank=1,
                role="representative",
            )
        )
        self.db.commit()

        titles = [event.title for event in query_published_events(self.db, keyword="宿舍搬迁", now=NOW)]

        self.assertIn("东校区宿舍搬迁", titles, "真正的搬迁事件必须还在")
        self.assertNotIn(
            "中大校园灵异传闻",
            titles,
            "灵异事件被当成搬迁舆情捞回来了 —— 说明匹配用上了 source_keywords_json，"
            "把「爬虫搜索时用的词」当成了「事件在讲什么」",
        )

    def test_an_empty_keyword_returns_every_published_event_by_priority(self):
        events = query_published_events(self.db, keyword="", now=NOW)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "东校区宿舍搬迁")


class FallbackTierTests(_Fixture):
    """兜底不退化——这是本次改造最重要的约束。"""

    def test_a_topic_without_a_published_event_still_gets_answered(self):
        """食堂有 4 条真帖但**没有** published 食堂事件。

        若聊天只读事件层，这里会直接查无此事——而改造前它能查到这 4 条。
        那不是改进，是退化。
        """

        service = OpinionChatService(self.db)
        events = service._events("食堂")

        self.assertTrue(events, "没有 published 食堂事件时必须回落到帖子层，不能让用户查无此事")
        total = sum(event.source_count for event in events)
        self.assertGreaterEqual(total, 4, f"帖子层应该带回 4 条食堂帖，实际 {total}")

    def test_a_matched_event_short_circuits_the_post_tier(self):
        service = OpinionChatService(self.db)
        events = service._events("宿舍搬迁")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_key, "sem:45e3a7f3", "命中事件时应该直接用它，不再走规则聚类")
        self.assertEqual(events[0].risk_level, "medium", "拿到的必须是 LLM 的研判")

    def test_a_broken_event_tier_degrades_instead_of_breaking_the_chat(self):
        """事件层查库炸了，聊天不能跟着挂——降级回帖子层照常回答。"""

        service = OpinionChatService(self.db)
        with mock.patch(
            "backend.services.opinion_chat_service.query_published_events",
            side_effect=RuntimeError("数据库连接断了"),
        ):
            events = service._events("食堂")

        self.assertTrue(events, "事件层故障必须自动降级到帖子层，而不是让整个对话失败")


if __name__ == "__main__":
    unittest.main()


class PromptTruncationTests(_Fixture):
    """存进 event_post_links 的代表帖，必须全都能进 prompt——不能在最后一步被静默砍掉。

    三处上限本该对齐，改造前却是错位的：

        event_post_links          每个事件存 5 条（role='representative'）
        event_read_model          取回 5 条（MAX_REPRESENTATIVE_NOTES）
        compact_events_for_llm    **只送 3 条进 prompt**   ← 静默丢掉 2 条

    真实后果：EVT-49 的 5 条代表帖按热度排序，第 4 条是知乎那条
    「如何看待中山大学强制东校区万逾名学生在同校区内互相搬迁宿舍？」——**最切题、
    最新（11 天前）、讲的正是事件本身**，但它 0 赞 0 评论、热度为 0，排在最后被砍掉；
    而占着第 1 个坑的是一条 **2021 年**的「东校区封闭管理」（热度 9839）。

    于是模型读到的是 5 年前的封闭管理，读不到 11 天前的强制搬迁。
    """

    def test_every_stored_representative_reaches_the_prompt(self):
        from backend.services.event_read_model import MAX_REPRESENTATIVE_NOTES
        from backend.services.opinion_report import compact_events_for_llm

        events = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)
        stored = len(events[0].representative_notes)
        self.assertEqual(stored, 3, "本用例的 fixture 存了 3 条代表帖")

        compact = compact_events_for_llm(events)
        sent = len(compact[0]["representative_notes"])

        self.assertEqual(
            sent,
            stored,
            f"取回了 {stored} 条代表帖，只有 {sent} 条进了 prompt —— 剩下的被静默丢掉了",
        )

    def test_the_prompt_cap_is_aligned_with_the_storage_cap(self):
        """三处上限必须是同一个数，否则迟早又有一处偷偷截断。"""

        from backend.services.event_read_model import MAX_REPRESENTATIVE_NOTES
        from backend.services import opinion_report

        self.assertEqual(
            opinion_report.PROMPT_MAX_REPRESENTATIVE_NOTES,
            MAX_REPRESENTATIVE_NOTES,
            "prompt 的代表帖上限和存储上限必须对齐，否则存进去的东西模型看不到",
        )

    def test_a_low_heat_but_on_topic_post_still_reaches_the_model(self):
        """热度为 0 的帖子不该因此被挡在 prompt 外——它可能正是最切题的那条。"""

        from backend.services.opinion_report import compact_events_for_llm

        zero_heat = ProcessedPost(
            note_id="zhihu:forced",
            raw_post_id=77,
            platform="zhihu",
            title="如何看待中山大学强制东校区万逾名学生在同校区内互相搬迁宿舍？",
            content="不就搬个宿舍，这话多的。",
            source_keyword="中山大学 宿舍搬迁",
            heat_score=0.0,  # 0 赞 0 评论 —— 但它讲的正是事件本身
            heat_rank=9.9,
            sentiment="negative",
            risk_level="medium",
            publish_time=NOW - timedelta(days=11),
        )
        self.db.add(zero_heat)
        self.db.commit()
        self.db.add(
            EventPostLink(
                event_id=self.event.id,
                processed_post_id=zero_heat.id,
                raw_post_id=zero_heat.raw_post_id,
                rank=4,  # 热度最低 -> 排最后
                role="representative",
            )
        )
        self.db.commit()

        events = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)
        compact = compact_events_for_llm(events)
        titles = [note["title"] for note in compact[0]["representative_notes"]]

        self.assertIn(
            "如何看待中山大学强制东校区万逾名学生在同校区内互相搬迁宿舍？",
            titles,
            "最切题的那条帖子因为热度为 0 被挡在 prompt 外了 —— 模型根本没机会读到它",
        )


class WeakTagMatchTests(_Fixture):
    """事件的 `top_tags` 是**词频聚合**，里面混着 count=1 的噪声标签——不能拿它做话题匹配。

    ## 线上事故（重跑事件后当场撞见）

    用户问「食堂」，事件层返回了：

        [high  ] 中大康某论文调查
        [medium] 中大课间缩短争议

    查下来：论文调查那个簇里有**一条**帖子随手打了个 #食堂 标签，于是事件的 top_tags 变成

        [{"tag":"学术论文","count":2}, {"tag":"食堂","count":1}, ...]

    而事件层匹配了 `top_tags_json LIKE '%食堂%'` —— 一条 count=1 的标签就把整个论文调查
    事件拽进了"食堂舆情"。代表帖里一条含「食堂」的都没有。

    这和 `source_keyword` 污染是同一个错误的两种写法：

        "爬虫搜过这个词"     ≠ "帖子在讲这个词"
        "一条帖子打过这个标签" ≠ "这个事件是关于它的"

    真正的话题证据是：事件标题 / 摘要，以及**代表帖在讲什么**（后者的 tags_json 照常匹配——
    那是"这条帖子自己打的标签"，不是聚合出来的词频尾巴）。
    """

    def test_a_count_one_tag_does_not_drag_an_unrelated_event_into_the_topic(self):
        unrelated = PublicEvent(
            event_key="sem:paper0001",
            title="中大康某论文调查",
            summary="中大康某论文调查共聚合 3 条内容。",
            status="published",
            risk_level="high",
            risk_score=80.0,
            heat_score=11300.0,
            source_count=3,
            # 簇里有一条帖子随手打了 #食堂 —— count=1，纯噪声
            top_tags_json=json.dumps(
                [{"tag": "学术论文", "count": 2}, {"tag": "食堂", "count": 1}],
                ensure_ascii=False,
            ),
            date_range_json=json.dumps({"event_time": _iso(60), "member_times": [_iso(60)]}),
        )
        self.db.add(unrelated)
        self.db.commit()

        paper_post = ProcessedPost(
            note_id="xhs:paper",
            raw_post_id=800,
            platform="xhs",
            title="Nature子刊+杰青+全网实名举报！中山大学康",
            content="论文数据造假举报。",  # 正文里没有「食堂」
            source_keyword="中山大学 学术不端",
            heat_score=10008.0,
            heat_rank=80.0,
            sentiment="negative",
            risk_level="high",
            publish_time=NOW - timedelta(days=60),
        )
        self.db.add(paper_post)
        self.db.commit()
        self.db.add(
            EventPostLink(
                event_id=unrelated.id,
                processed_post_id=paper_post.id,
                raw_post_id=paper_post.raw_post_id,
                rank=1,
                role="representative",
            )
        )
        self.db.commit()

        titles = [e.title for e in query_published_events(self.db, keyword="食堂", now=NOW)]

        self.assertNotIn(
            "中大康某论文调查",
            titles,
            "一条 count=1 的 #食堂 标签把整个论文调查事件拽成了「食堂舆情」——"
            "top_tags 是词频聚合，不是事件在讲什么",
        )

    def test_a_topic_with_no_event_still_falls_back_to_the_post_tier(self):
        """食堂没有对应的 published 事件时，必须老老实实回落帖子层拿到真实食堂帖。"""

        service = OpinionChatService(self.db)
        events = service._events("食堂")

        self.assertTrue(events, "回落层没兜住")
        for event in events:
            self.assertFalse(
                event.event_key.startswith("sem:"),
                f"食堂没有对应事件，却命中了事件层的「{event.title}」——那是误召回",
            )
