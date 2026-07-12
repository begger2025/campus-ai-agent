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

    def test_refiner_is_reported_in_the_run_log(self) -> None:
        result = self.analyze(cluster_refiner=topics_by_prefix)
        self.assertEqual(len(result.events), 3)
        self.assertEqual(result.run_log.extra["clustering_mode"], "semantic+llm")
        self.assertEqual(result.run_log.extra["refined_clusters"], 1)

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
