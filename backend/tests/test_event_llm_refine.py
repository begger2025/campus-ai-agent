"""LLM 聚类精修：拆开被 embedding 误合并的大桶，给事件一个具体的标题。

缺陷（297 条真实语料实测）：embedding 把 91 条帖子塞进同一个簇，标题取「簇内词频最高的词」
——抽到的是噪声词「饭堂」，于是这个桶叫「饭堂相关讨论」，里面**一条食堂的帖子都没有**：

    中山大学三大校区 哪个更好？ #升学规划
    中山大学拟调整作息引争议！校方回应：已关注此事，会回应师生关切
    吃饭，睡觉，骂校长，这都快成了中山学子的日常了！

两个结构性成因：(1) 每条帖子都含「中山大学」，embedding 空间被压平，子话题分不开；
(2) 标题 = 词频 top-1，词频不理解语义。调阈值治不了（已试：要么塌成 191 条的巨桶，
要么碎成 33 个重名事件）。真正缺的是**对内容的理解**——「中山大学作息调整」是这批语料里
一个 20 帖的真实争议，却从来没有作为一个事件出现过，它被埋在那个错标的桶里。

这一层做的事：把够大的簇交给 LLM，让它判断"这里面其实有几个话题"并各起一个具体标题。

**LLM 会失败，失败不许拖垮流水线**：超时、返回垃圾、编造出不存在的帖子编号、把同一条帖子
塞进两个话题——每一种都必须退回 embedding 的原结果并留下 warning，而不是把真实数据
按模型的幻觉重排。本文件的一半用例在断言这些失败路径。
"""

from __future__ import annotations

import unittest
from typing import Any

from backend.agent.public_opinion_core.llm_refine import (
    DEFAULT_REFINE_MIN_SIZE,
    EJECT_MAX_RATIO,
    refiner_input_texts,
)
from backend.agent.public_opinion_core.schemas import AnalyzeRequest, OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import cluster_notes_semantic
from backend.agent.public_opinion_core.service import PublicOpinionAgentService


# 全部帖子共用一个向量：模拟"embedding 把它们压成一个簇"（真实语料里由「中山大学」造成）。
SAME_VECTOR = [1.0, 0.0]


def make_notes(titles: list[str]) -> list[OpinionNote]:
    return [
        OpinionNote(note_id=f"n{index:02d}", title=title, content=title, heat_score=float(len(titles) - index))
        for index, title in enumerate(titles)
    ]


MIXED_TITLES = [
    "中山大学三大校区 哪个更好？",
    "中大南校区宿舍条件如何",
    "中山大学珠海校区值得报吗",
    "中山大学拟调整作息引争议！校方回应",
    "中大作息调整，早八提前了",
    "作息调整意见征集帖",
    "项飙讲座现场人山人海",
    "项飙来中大做讲座了",
]


class Recorder:
    """记录每次调用收到的文本，便于断言"哪些簇被送去精修"。"""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.response = response
        self.error = error

    def __call__(self, texts: list[str]) -> Any:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return self.response


def topics_by_prefix(texts: list[str]) -> list[dict[str, Any]]:
    """真实 LLM 的替身：按标题内容把 8 条帖子分成 3 个话题（含一个"零散杂项"）。"""

    campus, schedule, talk = [], [], []
    for index, text in enumerate(texts, start=1):
        if "作息" in text:
            schedule.append(index)
        elif "讲座" in text:
            talk.append(index)
        else:
            campus.append(index)
    return [
        {"title": "校区与报考信息", "members": campus},
        {"title": "作息调整争议", "members": schedule},
        {"title": "项飙讲座现场", "members": talk, "miscellaneous": True},
    ]


def cluster(notes: list[OpinionNote], refiner=None, **kwargs):
    return cluster_notes_semantic(
        notes,
        [list(SAME_VECTOR) for _ in notes],
        cluster_threshold=0.5,
        min_cluster_size=kwargs.pop("min_cluster_size", 1),
        refiner=refiner,
        refine_min_size=kwargs.pop("refine_min_size", 4),
        **kwargs,
    )


def titles(result) -> list[str]:
    return [event.title for event in result.events]


def note_ids(result) -> set[str]:
    ids: set[str] = set()
    for event in result.events:
        ids.update(event.extra.get("note_ids", []))
    return ids


class RefineSplitTest(unittest.TestCase):
    """embedding 合成一个桶的 8 条帖子，LLM 认出里面是 3 件事。"""

    def test_embedding_only_produces_one_mislabeled_bucket(self) -> None:
        result = cluster(make_notes(MIXED_TITLES))
        self.assertEqual(len(result.events), 1)
        self.assertTrue(result.events[0].title.endswith("相关讨论"))
        self.assertEqual(result.events[0].source_count, 8)

    def test_refiner_splits_the_bucket_into_specific_events(self) -> None:
        result = cluster(make_notes(MIXED_TITLES), refiner=topics_by_prefix)

        self.assertEqual(len(result.events), 3)
        self.assertEqual(set(titles(result)), {"校区与报考信息", "作息调整争议", "项飙讲座现场"})
        # 埋在错标桶里的真实事件必须自己浮出来。
        schedule = next(event for event in result.events if event.title == "作息调整争议")
        self.assertEqual(schedule.source_count, 3)
        # 标题不许再出现「…相关讨论」这种废话。
        for title in titles(result):
            self.assertNotIn("相关讨论", title)
        self.assertEqual(result.refined_clusters, 1)

    def test_every_note_survives_the_split(self) -> None:
        """守恒律：精修只能重新分组，不能凭空多出或丢掉帖子。"""

        result = cluster(make_notes(MIXED_TITLES), refiner=topics_by_prefix)
        self.assertEqual(sum(event.source_count for event in result.events), len(MIXED_TITLES))
        self.assertEqual(note_ids(result), {f"n{index:02d}" for index in range(len(MIXED_TITLES))})

    def test_event_keys_are_distinct_after_split(self) -> None:
        result = cluster(make_notes(MIXED_TITLES), refiner=topics_by_prefix)
        keys = [event.event_key for event in result.events]
        self.assertEqual(len(set(keys)), len(keys))

    def test_refiner_receives_note_texts_in_canonical_order(self) -> None:
        recorder = Recorder(response=topics_by_prefix(refiner_input_texts(make_notes(MIXED_TITLES))))
        cluster(make_notes(MIXED_TITLES), refiner=recorder)
        self.assertEqual(len(recorder.calls), 1)
        # 规范顺序 = 簇成员的 note_id 序，编号才有稳定含义。
        self.assertEqual(recorder.calls[0], MIXED_TITLES)


class RefineThresholdTest(unittest.TestCase):
    """只精修值得精修的簇：给一个 2 帖的簇打一次 LLM 调用是纯浪费。"""

    def test_small_clusters_are_not_sent_to_the_llm(self) -> None:
        recorder = Recorder(response=[])
        result = cluster(make_notes(MIXED_TITLES[:3]), refiner=recorder, refine_min_size=4)
        self.assertEqual(recorder.calls, [])
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.refined_clusters, 0)

    def test_default_threshold_is_documented_and_above_min_cluster_size(self) -> None:
        # 一个簇要能拆成两个"公共事件"，至少得有 2 × min_cluster_size 条帖子。
        self.assertGreaterEqual(DEFAULT_REFINE_MIN_SIZE, 4)

    def test_min_cluster_size_still_suppresses_tiny_llm_topics(self) -> None:
        """LLM 拆出的 1 帖话题不是公共事件——EVENT_MIN_CLUSTER_SIZE 语义不变。"""

        def one_note_topic(texts: list[str]) -> list[dict[str, Any]]:
            return [
                {"title": "作息调整争议", "members": [1]},
                {"title": "校区与报考信息", "members": list(range(2, len(texts) + 1))},
            ]

        result = cluster(make_notes(MIXED_TITLES), refiner=one_note_topic, min_cluster_size=2)
        self.assertEqual(titles(result), ["校区与报考信息"])
        self.assertEqual(result.suppressed_clusters, 1)


class RefineFailureTest(unittest.TestCase):
    """LLM 失败时退回 embedding 结果，并留下 warning——绝不让幻觉重排真实数据。"""

    def baseline_titles(self) -> list[str]:
        return titles(cluster(make_notes(MIXED_TITLES)))

    def assert_fell_back(self, refiner) -> None:
        result = cluster(make_notes(MIXED_TITLES), refiner=refiner)
        self.assertEqual(titles(result), self.baseline_titles())
        self.assertEqual(result.events[0].source_count, 8)
        self.assertEqual(result.refined_clusters, 0)
        self.assertTrue(result.refine_warnings, "失败必须留下 warning")

    def test_refiner_raises(self) -> None:
        self.assert_fell_back(Recorder(error=TimeoutError("read timed out")))

    def test_refiner_returns_none(self) -> None:
        self.assert_fell_back(Recorder(response=None))

    def test_refiner_returns_garbage(self) -> None:
        self.assert_fell_back(Recorder(response="话题一：食堂"))

    def test_refiner_returns_empty_topics(self) -> None:
        self.assert_fell_back(Recorder(response=[]))

    def test_refiner_invents_a_post_number(self) -> None:
        """模型编了一条第 99 号帖子——整簇精修作废。"""

        self.assert_fell_back(
            Recorder(response=[{"title": "作息调整争议", "members": [1, 2, 99]}, {"title": "校区", "members": [3]}])
        )

    def test_refiner_assigns_one_post_to_two_topics(self) -> None:
        self.assert_fell_back(
            Recorder(
                response=[
                    {"title": "作息调整争议", "members": [1, 2]},
                    {"title": "校区与报考信息", "members": [2, 3]},
                ]
            )
        )

    def test_refiner_returns_empty_title(self) -> None:
        self.assert_fell_back(Recorder(response=[{"title": "  ", "members": [1, 2, 3]}]))

    def test_refiner_returns_non_integer_members(self) -> None:
        self.assert_fell_back(Recorder(response=[{"title": "作息调整争议", "members": ["第一条"]}]))

    def test_unassigned_notes_are_kept_not_dropped(self) -> None:
        """模型漏掉了几条帖子：漏掉的必须原样留在一个残余簇里，一条都不能少。"""

        def partial(texts: list[str]) -> list[dict[str, Any]]:
            return [{"title": "作息调整争议", "members": [4, 5, 6]}]

        result = cluster(make_notes(MIXED_TITLES), refiner=partial)
        self.assertIn("作息调整争议", titles(result))
        self.assertEqual(sum(event.source_count for event in result.events), 8)
        self.assertEqual(note_ids(result), {f"n{index:02d}" for index in range(8)})
        self.assertTrue(any("未分配" in warning or "unassigned" in warning for warning in result.refine_warnings))


class RefineEjectionTest(unittest.TestCase):
    """离群剔除：模型可以说"这条帖子哪个话题都不属于"，它就不再冒充这个事件的证据。

    真实缺陷（已发布的事件「东校区宿舍火灾」）：4 条代表内容里有 3 条是 2026-03-24~26 的
    真实火情，第 4 条是

        快手 · #中大宿舍实拍 · @安好 · 2023-08-31 · 赞146

    一张 2023 年的宿舍照片，和火灾毫无关系——embedding 把它和火灾聚在一起，只因为两边
    都写着「宿舍」。精修层却**无法表达"它哪个话题都不属于"**：模型要么把它塞进某个话题，
    要么漏掉它（漏掉的按契约"不丢，留作残余簇"），于是它稳稳地留在事件里。

    这一层加的能力：模型可以把一条帖子标成 unrelated → 它被**从事件里剔除**。
    剔除 ≠ 删除：帖子仍在 processed_posts、仍计入情感统计与热度，只是不再作为事件证据。
    一条孤零零的无关照片本来就不是"公共事件"，它自然被 EVENT_MIN_CLUSTER_SIZE 压制掉。
    """

    # 事件「东校区宿舍火灾」的真实成员构成：3 条火情 + 1 条 2023 年的宿舍照片。
    FIRE_TITLES = [
        "中山大学东校区宿舍发生火情，现场楼道浓烟滚滚",
        "中山大学广州校区宿舍发生火灾，消防及时到场处置",
        "中山大学宿舍起火 校方通报：现场无人员伤亡",
        "#中大宿舍实拍",  # 2023-08-31，与火灾无关
    ]

    @staticmethod
    def fire_refiner(texts: list[str]) -> list[dict[str, Any]]:
        """模型的替身：认出 3 条火情是一件事，第 4 条哪件事都不是。"""

        return [
            {"title": "东校区宿舍火灾", "members": [1, 2, 3]},
            {"members": [4], "unrelated": True},
        ]

    def fire(self, **kwargs):
        return cluster(make_notes(self.FIRE_TITLES), refiner=self.fire_refiner, **kwargs)

    def test_unrelated_post_is_ejected_from_the_event(self) -> None:
        """缺陷本体：火灾事件里不许再站着那张 2023 年的照片。"""

        result = self.fire(min_cluster_size=2)

        self.assertEqual(titles(result), ["东校区宿舍火灾"])
        fire_event = result.events[0]
        self.assertEqual(fire_event.source_count, 3)  # 4 -> 3
        self.assertNotIn("n03", fire_event.extra["note_ids"])  # 那张照片
        self.assertEqual(result.refined_clusters, 1)

    def test_ejected_post_is_counted_and_surfaced_never_silently_dropped(self) -> None:
        """剔除必须留痕：计数 + warning。悄悄消失的真实数据是不可接受的。"""

        result = self.fire(min_cluster_size=2)

        self.assertEqual(result.ejected_notes, 1)
        self.assertTrue(
            any("eject" in warning or "剔除" in warning for warning in result.refine_warnings),
            f"剔除必须留下 warning，实际：{result.refine_warnings}",
        )
        # 剔除出来的单帖簇走的是既有的 min_cluster_size 压制通道（它已经在报数了）。
        self.assertEqual(result.suppressed_clusters, 1)

    def test_ejected_post_is_not_deleted_from_the_corpus(self) -> None:
        """剔除 ≠ 删除：min_cluster_size=1（库默认，"每个簇都是事件"）时它仍是一条独立的帖子。

        它只是不再**属于火灾事件**——这正是"剔除"与"删除"的分界线。
        """

        result = self.fire(min_cluster_size=1)

        fire_event = next(event for event in result.events if event.title == "东校区宿舍火灾")
        self.assertEqual(fire_event.source_count, 3)
        self.assertNotIn("n03", fire_event.extra["note_ids"])
        # 守恒：帖子没有蒸发，它自己单独成簇（而不是消失）。
        self.assertEqual(sum(event.source_count for event in result.events), 4)
        self.assertIn("n03", note_ids(result))

    def test_ejection_is_capped_a_model_that_ejects_most_of_a_cluster_is_malfunctioning(self) -> None:
        """模型要剔掉一个簇的大半 → 整份结果作废，退回 embedding，并留 warning。

        剔错一条真实成员比留下一条边缘成员更糟（事件会丢掉真实证据）。剔除 6/8 = 75%
        不是"洞察"，是模型坏了。
        """

        def over_ejector(texts: list[str]) -> list[dict[str, Any]]:
            return [
                {"title": "作息调整争议", "members": [1, 2]},
                {"members": [3, 4, 5, 6, 7, 8], "unrelated": True},
            ]

        result = cluster(make_notes(MIXED_TITLES), refiner=over_ejector)

        # 退回 embedding 的原簇：8 条帖子一条不少，标题还是词频标题。
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].source_count, 8)
        self.assertTrue(result.events[0].title.endswith("相关讨论"))
        self.assertEqual(result.refined_clusters, 0)
        self.assertEqual(result.ejected_notes, 0)
        self.assertTrue(
            any("cap" in warning or "过多" in warning for warning in result.refine_warnings),
            f"越过上限必须留下 warning，实际：{result.refine_warnings}",
        )

    def test_ejection_within_the_cap_is_honored(self) -> None:
        """8 帖的簇剔 2 条（25%）在上限内 —— 正常工作，不作废。"""

        def two_ejector(texts: list[str]) -> list[dict[str, Any]]:
            return [
                {"title": "作息调整争议", "members": [1, 2, 3, 4, 5, 6]},
                {"members": [7, 8], "unrelated": True},
            ]

        result = cluster(make_notes(MIXED_TITLES), refiner=two_ejector, min_cluster_size=2)

        self.assertEqual(titles(result), ["作息调整争议"])
        self.assertEqual(result.events[0].source_count, 6)
        self.assertEqual(result.ejected_notes, 2)
        self.assertEqual(result.refined_clusters, 1)

    def test_cap_is_a_minority_of_the_cluster(self) -> None:
        """上限的语义：剔除的只能是少数派。多数派"不属于本簇"意味着聚类本身错了，
        那时该退回的是 embedding 结果，而不是让模型拆掉一个真实事件。"""

        self.assertGreater(EJECT_MAX_RATIO, 0.0)
        self.assertLessEqual(EJECT_MAX_RATIO, 1 / 3 + 1e-9)


class RefineEjectionValidationTest(unittest.TestCase):
    """剔除名单和话题分配一样，必须对着**真实成员**核对；对不上就整簇作废。

    绝不能让一个编造出来的编号去删掉一条真实帖子。
    """

    def assert_fell_back(self, refiner) -> None:
        result = cluster(make_notes(MIXED_TITLES), refiner=refiner)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].source_count, 8)  # 一条都没动
        self.assertEqual(result.refined_clusters, 0)
        self.assertEqual(result.ejected_notes, 0)
        self.assertTrue(result.refine_warnings, "失败必须留下 warning")

    def test_ejecting_an_invented_post_number(self) -> None:
        self.assert_fell_back(
            Recorder(
                response=[
                    {"title": "作息调整争议", "members": [1, 2, 3]},
                    {"members": [99], "unrelated": True},  # 这个簇只有 8 条
                ]
            )
        )

    def test_a_post_cannot_be_both_ejected_and_assigned_to_a_topic(self) -> None:
        self.assert_fell_back(
            Recorder(
                response=[
                    {"title": "作息调整争议", "members": [1, 2, 3]},
                    {"members": [3], "unrelated": True},  # 3 号既在话题里又被剔除
                ]
            )
        )

    def test_ejecting_a_non_integer_post_number(self) -> None:
        self.assert_fell_back(
            Recorder(
                response=[
                    {"title": "作息调整争议", "members": [1, 2, 3]},
                    {"members": ["第四条"], "unrelated": True},
                ]
            )
        )

    def test_ejection_without_any_topic_is_discarded(self) -> None:
        """模型只剔除、一个话题都不给：这不是"洞察"，是没干活——整簇作废。"""

        self.assert_fell_back(Recorder(response=[{"members": [1], "unrelated": True}]))

    def test_ejection_plus_topics_must_reconcile_against_the_real_member_list(self) -> None:
        """剔除 + 话题分配 + 残余簇 = 全体成员，一条不多一条不少。"""

        def refiner(texts: list[str]) -> list[dict[str, Any]]:
            return [
                {"title": "作息调整争议", "members": [4, 5, 6]},
                {"members": [1], "unrelated": True},
                # 2、3、7、8 号模型没提 -> 残余簇（既有契约：漏掉的不丢）
            ]

        result = cluster(make_notes(MIXED_TITLES), refiner=refiner, min_cluster_size=1)
        self.assertEqual(sum(event.source_count for event in result.events), 8)
        self.assertEqual(note_ids(result), {f"n{index:02d}" for index in range(8)})
        self.assertEqual(result.ejected_notes, 1)
        schedule = next(event for event in result.events if event.title == "作息调整争议")
        self.assertNotIn("n00", schedule.extra["note_ids"])


class RefinedTitleTest(unittest.TestCase):
    """精修出来的标题必须干净：不许重名，也不许在消歧时把「…相关讨论」的套话粘回来。

    实测（297 条语料）：两个 embedding 簇各自被 LLM 认出「中大作息调整争议」——同一件事被
    切在两个簇里。不处理的话事件列表里就并排站着两个同名事件，消歧再给它们各加一条尾巴，
    变成「中大作息调整争议·中山大学相关讨论」——正是这次要消灭的那种标题。
    """

    def test_same_topic_from_two_clusters_becomes_one_event(self) -> None:
        # 两个簇（向量正交，embedding 分得开），但 LLM 在两边都认出「作息调整争议」。
        notes = make_notes(MIXED_TITLES) + make_notes(["作息调整第二簇 A", "作息调整第二簇 B"] * 3)
        for index, note in enumerate(notes[8:], start=8):
            note.note_id = f"m{index:02d}"
        vectors = [[1.0, 0.0]] * 8 + [[0.0, 1.0]] * 6

        def refiner(texts: list[str]) -> list[dict[str, Any]]:
            if any("讲座" in text for text in texts):
                return topics_by_prefix(texts)
            return [{"title": "作息调整争议", "members": list(range(1, len(texts) + 1))}]

        result = cluster_notes_semantic(
            notes, vectors, cluster_threshold=0.5, min_cluster_size=1,
            refiner=refiner, refine_min_size=4,
        )
        schedule = [event for event in result.events if event.title == "作息调整争议"]
        self.assertEqual(len(schedule), 1, "同名话题必须合成一个事件")
        self.assertEqual(schedule[0].source_count, 3 + 6)
        self.assertEqual(sum(event.source_count for event in result.events), len(notes))

    def test_disambiguation_never_appends_boilerplate_to_an_llm_title(self) -> None:
        from backend.agent.public_opinion_core.semantic_clustering import _disambiguate_title

        notes = make_notes(MIXED_TITLES)
        # 词频标题撞车：保持老行为（尾巴是「相关讨论」）。
        keyword_title = _disambiguate_title("食堂相关讨论", notes, {"食堂相关讨论"})
        self.assertTrue(keyword_title.endswith("相关讨论"))
        # LLM 标题撞车：绝不许粘上「相关讨论」——那正是这次要修掉的东西。
        llm_title = _disambiguate_title("作息调整争议", notes, {"作息调整争议"})
        self.assertNotEqual(llm_title, "作息调整争议")
        self.assertNotIn("相关讨论", llm_title)


class ServiceWiringTest(unittest.TestCase):
    """service 层：refiner 是注入的能力，None = 跳过精修（和 embedder/sentiment 一个模式）。"""

    def rows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": index + 1,
                "note_id": f"n{index:02d}",
                "title": title,
                "content": title,
                "platform": "xhs",
            }
            for index, title in enumerate(MIXED_TITLES)
        ]

    def analyze(self, **kwargs):
        return PublicOpinionAgentService().analyze_from_rows(
            self.rows(),
            AnalyzeRequest(limit=50),
            embedder=lambda texts: [list(SAME_VECTOR) for _ in texts],
            cluster_threshold=0.5,
            refine_min_size=4,
            **kwargs,
        )

    def test_no_refiner_keeps_embedding_result(self) -> None:
        result = self.analyze()
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.run_log.extra["clustering_mode"], "semantic")

    def test_refine_max_members_threads_through_to_the_core(self) -> None:
        """上限全链路透传：巨桶最需要精修，不该被写死的默认上限一票否决。

        第 6 轮微博 224 条入库后聚出 182 帖巨簇，默认 max_members=150 让精修被跳过
        （巨桶病复发）——部署侧必须能经 EVENT_REFINE_MAX_MEMBERS 放宽。
        """

        # 上限收紧到 5：8 帖的簇不送 LLM，refiner 一次都不该被调用，且大声留痕。
        recorder = Recorder(response=[])
        result = self.analyze(cluster_refiner=recorder, refine_max_members=5)
        self.assertEqual(recorder.calls, [])
        self.assertEqual(len(result.events), 1)
        self.assertTrue(any("max_members=5" in w for w in result.warnings))

        # 上限放宽到恰好容纳：同一个簇被正常精修拆开。
        result = self.analyze(cluster_refiner=topics_by_prefix, refine_max_members=8)
        self.assertEqual(len(result.events), 3)
        self.assertEqual(result.run_log.extra["refined_clusters"], 1)

    def test_refiner_is_reported_in_the_run_log(self) -> None:
        result = self.analyze(cluster_refiner=topics_by_prefix)
        self.assertEqual(len(result.events), 3)
        self.assertEqual(result.run_log.extra["clustering_mode"], "semantic+llm")
        self.assertEqual(result.run_log.extra["refined_clusters"], 1)

    def test_ejected_notes_are_reported_in_the_run_log(self) -> None:
        """被剔除的帖子数进 run_log（-> agent_run_logs）：答辩时看得见"这次剔了几条"。"""

        def ejector(texts: list[str]) -> list[dict[str, Any]]:
            return [
                {"title": "作息调整争议", "members": list(range(1, len(texts))),},
                {"members": [len(texts)], "unrelated": True},
            ]

        result = self.analyze(cluster_refiner=ejector, min_cluster_size=2)
        self.assertEqual(result.run_log.extra["ejected_notes"], 1)
        self.assertTrue(any("eject" in w or "剔除" in w for w in result.warnings))

    def test_no_refiner_reports_zero_ejected(self) -> None:
        self.assertEqual(self.analyze().run_log.extra["ejected_notes"], 0)

    def test_failed_refiner_degrades_to_semantic_and_warns(self) -> None:
        result = self.analyze(cluster_refiner=Recorder(error=RuntimeError("502 bad gateway")))
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.run_log.extra["clustering_mode"], "semantic")
        self.assertEqual(result.run_log.extra["refined_clusters"], 0)
        self.assertTrue(any("refine" in warning for warning in result.warnings))
        # warning 进 agent_run_logs，答辩时能看见"这次 LLM 没上"。
        self.assertTrue(any("refine" in warning for warning in result.run_log.warnings))


if __name__ == "__main__":
    unittest.main()
