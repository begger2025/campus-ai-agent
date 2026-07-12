"""质心合并 pass：同一个话题不许裂成多个事件。

单趟贪心（`_greedy_cluster`）给每条帖子找"当前最像的簇"，找不到就新开一簇——**没有回头**。
于是同一个话题会按输入顺序裂成若干簇，而且永远不会被重新缝合：真实数据上 297 条帖子
产出了 4 个「宿舍相关讨论」、3 个「食堂相关讨论」、3 个「中山大学相关讨论」。
调阈值治不了：调高裂得更碎，调低直接塌成一个吞掉 64% 语料的巨簇。缺的是一步——

  贪心之后，反复把**质心之间**足够像的簇合并，重算质心，直到没有可合的一对（凝聚式后合并）。

这一步顺带要求聚类**与输入顺序无关**：既然是"同一批帖子"，换个顺序喂进来必须得到同一批簇，
否则"重复事件"随时会以另一种形式回来（见 OrderIndependenceTest）。

另：合并之后仍然同名的两个事件，对答辩列表来说和没修一样——标题必须能区分（见 TitleTest）。
"""

from __future__ import annotations

import importlib
import math
import random
import unittest
from unittest import mock

from backend.agent.public_opinion_core.schemas import AnalyzeRequest, OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import (
    DEFAULT_MERGE_THRESHOLD,
    MERGE_THRESHOLD_ENV,
    assign_clusters,
    cluster_notes_semantic,
)
from backend.agent.public_opinion_core.service import PublicOpinionAgentService


# 这些用例断言的是**代码里的默认阈值**。backend/database.py 在 import 时 load_dotenv(override=True)，
# 会把部署 .env 里的 EMBEDDING_MERGE_THRESHOLD 灌进 os.environ（全量 discover 时必然发生），
# 默认值用例会因此单跑绿、全量红。这里显式与部署配置隔离（同 test_platform_weights.py）。
_ENV_ISOLATION = mock.patch.dict("os.environ", {MERGE_THRESHOLD_ENV: ""})


def setUpModule() -> None:
    _ENV_ISOLATION.start()


def tearDownModule() -> None:
    _ENV_ISOLATION.stop()


def unit(degrees: float) -> list[float]:
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians)]


def note(note_id: str, title: str, **kwargs) -> OpinionNote:
    return OpinionNote(note_id=note_id, title=title, content=kwargs.pop("content", title), **kwargs)


def grouping(
    notes: list[OpinionNote], vectors: list[list[float]], **kwargs
) -> frozenset[frozenset[str]]:
    """{{note_id}}：与输入顺序、簇编号、事件命名都无关的聚类结果指纹。

    走 assign_clusters（逐条标签）而不是 event.representative_notes——后者截断到 5 条，
    大簇的成员会被截掉，指纹会假性相等。
    """

    labels = assign_clusters(notes, vectors, **kwargs)
    groups: dict[int, set[str]] = {}
    for note_obj, label in zip(notes, labels):
        groups.setdefault(label, set()).add(note_obj.note_id)
    return frozenset(frozenset(group) for group in groups.values())


class MergePassTest(unittest.TestCase):
    """贪心之后的质心合并：同话题的碎片必须被缝回一个事件。"""

    def setUp(self) -> None:
        # 0° / 25° / 50°：一条"话题内部有角度跨度"的链。
        self.notes = [note("a", "宿舍热水"), note("b", "宿舍搬迁"), note("c", "宿舍空调")]
        self.vectors = [unit(0), unit(50), unit(25)]
        # cos30° = 0.866：a 与 c(25°) 同簇，b(50°) 离 a 太远只能自己开一簇。
        self.cluster_threshold = math.cos(math.radians(30))

    def test_greedy_alone_fragments_one_topic_into_two_clusters(self) -> None:
        """先把缺陷本身钉死：不合并时，这三条同话题帖子裂成 2 个事件。"""

        result = cluster_notes_semantic(
            self.notes,
            self.vectors,
            cluster_threshold=self.cluster_threshold,
            merge_threshold=1.0,  # 1.0 = 只有完全相同的质心才合并，等价于关掉合并
            min_cluster_size=1,
        )

        self.assertEqual(len(result.events), 2)

    def test_merge_pass_rejoins_the_fragments(self) -> None:
        # 合并后 a+c 的质心在 12.5°，与 b(50°) 夹角 37.5°，cos = 0.793。
        result = cluster_notes_semantic(
            self.notes,
            self.vectors,
            cluster_threshold=self.cluster_threshold,
            merge_threshold=0.75,
            min_cluster_size=1,
        )

        self.assertEqual(len(result.events), 1, "同话题的三条帖子仍然裂成多个事件")
        self.assertEqual(result.events[0].source_count, 3)
        # 簇中心必须是合并后的那一个，否则写进快照会把已合并的事件在下一轮复活。
        self.assertEqual(len(result.centroids), 1)

    def test_merge_keeps_genuinely_different_topics_apart(self) -> None:
        """合并不能变成"什么都合"——巨簇是另一个缺陷，不是修复。"""

        notes = [note("a", "食堂排队"), note("b", "食堂窗口"), note("c", "考研自习室"), note("d", "考研占座")]
        vectors = [unit(0), unit(10), unit(80), unit(90)]

        result = cluster_notes_semantic(
            notes,
            vectors,
            cluster_threshold=math.cos(math.radians(30)),
            merge_threshold=0.75,
            min_cluster_size=1,
        )

        self.assertEqual(len(result.events), 2)
        self.assertEqual(sorted(event.source_count for event in result.events), [2, 2])

    def test_merge_repeats_until_no_pair_qualifies(self) -> None:
        """合并要做到不动点，且每次合并后**重算质心**——一趟是合不完的。

        三条帖子在 0° / 8° / 16°，merge_threshold = 0.97（≈ 14°）：
          - a~b、b~c 都是 cos8° = 0.990，够合；
          - 但 a~c 是 cos16° = 0.961，**不够合**——它俩永远不会被直接配上对。
        只有先合出 {a,b}（质心 4°），重算后的质心与 c 才相距 12°（cos = 0.978 ≥ 0.97），
        第二轮才轮得到 c。所以这个用例只有"反复合并 + 每轮重算质心"才过得去：
        少了任何一半，结果都是 2 个事件。
        """

        notes = [note("a", "宿舍热水"), note("b", "宿舍空调"), note("c", "宿舍搬迁")]
        vectors = [unit(0), unit(8), unit(16)]

        result = cluster_notes_semantic(
            notes,
            vectors,
            cluster_threshold=0.999,  # 贪心阶段每条自成一簇，把活全留给合并
            merge_threshold=0.97,
            min_cluster_size=1,
        )

        self.assertEqual(len(result.events), 1, "合并没有做到不动点：只合了一轮就收工")
        self.assertEqual(result.events[0].source_count, 3)


class OrderIndependenceTest(unittest.TestCase):
    """同一批帖子换个顺序喂进来，必须得到同一批簇。"""

    def build(self) -> tuple[list[OpinionNote], dict[str, list[float]]]:
        specs = [
            ("d1", "宿舍热水停了", 0), ("d2", "宿舍热水又停", 12), ("d3", "宿舍空调坏了", 24),
            ("d4", "宿舍搬迁通知", 36), ("d5", "宿舍晚上太吵", 15),
            ("c1", "食堂排队太长", 100), ("c2", "食堂窗口排队", 112), ("c3", "饭堂涨价了", 124),
            ("c4", "食堂阿姨手抖", 108),
            ("l1", "图书馆占座", 200), ("l2", "图书馆自习室满了", 212), ("l3", "图书馆闭馆太早", 224),
        ]
        # heat 全为默认 0：note_rank_key 全是 (0,0,0)，排序完全并列——
        # 此时"谁先当种子"只由输入顺序决定，顺序依赖会毫无遮挡地暴露出来。
        notes = [note(note_id, title) for note_id, title, _deg in specs]
        vectors = {note_id: unit(deg) for note_id, _title, deg in specs}
        return notes, vectors

    def cluster(self, notes: list[OpinionNote]) -> frozenset[frozenset[str]]:
        _all_notes, vectors = self.build()
        return grouping(
            notes,
            [vectors[n.note_id] for n in notes],
            cluster_threshold=math.cos(math.radians(20)),
            merge_threshold=DEFAULT_MERGE_THRESHOLD,
        )

    def test_shuffled_input_produces_identical_clusters(self) -> None:
        notes, _vectors = self.build()
        baseline = self.cluster(list(notes))

        for seed in range(8):
            shuffled = list(notes)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(
                self.cluster(shuffled),
                baseline,
                f"打乱输入顺序（seed={seed}）后聚类结果变了：聚类依赖输入顺序",
            )

    def test_shuffled_input_produces_identical_titles(self) -> None:
        notes, _vectors = self.build()
        _all_notes, vectors = self.build()

        def titles(ordered: list[OpinionNote]) -> set[str]:
            result = cluster_notes_semantic(
                ordered,
                [vectors[n.note_id] for n in ordered],
                cluster_threshold=math.cos(math.radians(20)),
                merge_threshold=DEFAULT_MERGE_THRESHOLD,
                min_cluster_size=1,
            )
            return {event.title for event in result.events}

        baseline = titles(list(notes))
        shuffled = list(notes)
        random.Random(99).shuffle(shuffled)
        self.assertEqual(titles(shuffled), baseline)


class TitleTest(unittest.TestCase):
    """两个不同的事件不许同名——同名事件正是要消灭的那个缺陷。"""

    def test_distinct_events_never_share_a_title(self) -> None:
        notes = [
            note("a", "宿舍热水停了", keywords=["宿舍", "热水"]),
            note("b", "宿舍热水又停", keywords=["宿舍", "热水"]),
            note("c", "宿舍搬迁通知", keywords=["宿舍", "搬迁"]),
            note("d", "宿舍搬迁安排", keywords=["宿舍", "搬迁"]),
        ]
        # 两个真正不同的簇（正交），但主关键词都是"宿舍"。
        vectors = [unit(0), unit(5), unit(85), unit(90)]

        result = cluster_notes_semantic(
            notes,
            vectors,
            cluster_threshold=math.cos(math.radians(20)),
            merge_threshold=0.9,
            min_cluster_size=1,
        )

        titles = [event.title for event in result.events]
        self.assertEqual(len(result.events), 2)
        self.assertEqual(len(set(titles)), 2, f"两个不同事件同名：{titles}")
        # 消歧不能把主关键词丢了。
        self.assertTrue(all("宿舍" in title for title in titles), titles)

    def test_collision_without_secondary_keyword_falls_back_to_post_title(self) -> None:
        """没有次要关键词可用时，用代表帖标题命名——而不是给标题编号。

        真实数据上撞见过：两个簇的关键词都只有「宿舍」（关键词抽取本身就噪声很大，
        一条"学生被开除"的帖子也被标了「宿舍」）。此时退化成「宿舍（2）相关讨论」，
        在公开列表里读起来就是个 bug——序号只能是最后兜底，不能是常规结果。
        """

        notes = [
            note("a", "宿舍热水停了", keywords=["宿舍"]),
            note("b", "宿舍热水又停", keywords=["宿舍"]),
            note("c", "学生被开除引争议", keywords=["宿舍"]),
            note("d", "学生被开除后续", keywords=["宿舍"]),
        ]
        vectors = [unit(0), unit(5), unit(85), unit(90)]

        result = cluster_notes_semantic(
            notes,
            vectors,
            cluster_threshold=math.cos(math.radians(20)),
            merge_threshold=0.9,
            min_cluster_size=1,
        )

        titles = [event.title for event in result.events]
        self.assertEqual(len(set(titles)), 2, f"两个不同事件同名：{titles}")
        self.assertFalse(
            [title for title in titles if "（2）" in title],
            f"没到山穷水尽就用序号命名事件：{titles}",
        )
        # 第二个事件应当由它自己的代表帖标题命名，让人看得出这是"另一件事"。
        self.assertTrue(
            any("学生被开除" in title for title in titles),
            f"重名事件没有退回代表帖标题：{titles}",
        )


class ServiceWiringTest(unittest.TestCase):
    """merge_threshold 要从服务层一路传到核心聚类。"""

    def test_service_passes_merge_threshold_to_semantic_clustering(self) -> None:
        rows = [
            {"id": 1, "note_id": "a", "title": "宿舍热水", "content": "宿舍热水", "platform": "xhs"},
            {"id": 2, "note_id": "b", "title": "宿舍搬迁", "content": "宿舍搬迁", "platform": "xhs"},
            {"id": 3, "note_id": "c", "title": "宿舍空调", "content": "宿舍空调", "platform": "xhs"},
        ]
        # embedder 拿到的是 note_text（title+content+keywords…拼起来），不是 title 本身：
        # 按 title 精确查表会 KeyError，而 service 会把异常吞掉退回规则聚类——
        # 那样这个用例就变成在测 fallback，而不是在测 merge_threshold。所以按子串匹配，
        # 并在下面断言 clustering_mode == "semantic"，堵死"静默退回"这条假绿路径。
        vectors = {"宿舍热水": unit(0), "宿舍搬迁": unit(50), "宿舍空调": unit(25)}

        def embedder(texts: list[str]) -> list[list[float]]:
            return [next(v for k, v in vectors.items() if k in text) for text in texts]

        def run(merge_threshold: float) -> int:
            result = PublicOpinionAgentService().analyze_from_rows(
                rows,
                AnalyzeRequest(limit=10),
                embedder=embedder,
                cluster_threshold=math.cos(math.radians(30)),
                merge_threshold=merge_threshold,
                min_cluster_size=1,
            )
            self.assertEqual(
                result.run_log.extra.get("clustering_mode"),
                "semantic",
                f"没有走语义聚类（静默退回规则路径）：{result.warnings}",
            )
            return len(result.events)

        self.assertEqual(run(1.0), 2, "关掉合并时应保留贪心的碎片（说明参数确实生效）")
        self.assertEqual(run(0.75), 1, "merge_threshold 没有传到核心聚类")


class ConfigTest(unittest.TestCase):
    """阈值必须可经 .env 调，不改代码。"""

    def reload_config(self):
        from backend.services import llm_config

        return importlib.reload(llm_config)

    def tearDown(self) -> None:
        self.reload_config()

    def test_default_merge_threshold_matches_core_default(self) -> None:
        with mock.patch.dict("os.environ", {MERGE_THRESHOLD_ENV: ""}):
            config = self.reload_config()
        self.assertEqual(config.EMBEDDING_MERGE_THRESHOLD, DEFAULT_MERGE_THRESHOLD)

    def test_env_overrides_merge_threshold(self) -> None:
        with mock.patch.dict("os.environ", {MERGE_THRESHOLD_ENV: "0.83"}):
            config = self.reload_config()
        self.assertAlmostEqual(config.EMBEDDING_MERGE_THRESHOLD, 0.83)


if __name__ == "__main__":
    unittest.main()
