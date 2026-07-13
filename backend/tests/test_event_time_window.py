"""聚类的时间约束：一个事件是**某个时候发生的一件事**，不是"所有像这件事的帖子"。

## 线上事故

EVT-49「东校区宿舍搬迁」聚了 6 条帖，时间跨度 **1782 天（4.9 年）**：

    2021-08-14  热度 9839 (89.9%)  中山大学东校区封闭管理        ← 疫情封校
    2026-05-23  热度  461 ( 4.2%)  中大东校区搬宿舍的原因找到了
    2026-05-26  热度  588 ( 5.4%)  关于东校区宿舍搬迁的看法意见
    2026-07-02  热度    0 ( 0.0%)  强制万逾名学生互相搬迁宿舍

那条 2021 年的**疫情封校**帖，语义上跟 2026 年的**宿舍搬迁**确实接近（都是"东校区 + 管理
措施 + 影响学生"），于是 embedding 把它们聚成了一件事。而它热度 9839、平台百分位 89.8，
按热度降序挑种子时**第一个开簇**——2026 年的搬迁帖是挂到它身上的。

后果：
  - 事件对外宣称的热度 10982，其中 **90% 来自一条 5 年前的疫情帖**（真实搬迁讨论只有约 1100）
  - 它排 rank 1，占掉代表帖的头位
  - EVT-57「中大作息调整争议」同病：跨度 1666 天

而全库 **23% 的帖子是 2024 年以前的**（93/397），2021 年那批里还有一条热度 16 万的——
这不是孤例，是随时会复发的结构性缺陷。

## 为什么用算术而不是 LLM

项目的原则是「**可测量的用算术，需要判断的用 AI**」。

"这两条帖子是不是在讲同一个话题" —— 需要判断 → embedding / LLM。
"这两条帖子差了 5 年吗" —— **可测量** → 算术，而且该**硬卡死**。

LLM 精修（llm_refine）拆不掉它：送进模型的只有标题，模型根本不知道那条是 2021 年的。
与其教模型读日期，不如用一行减法把不可能的事排除掉。

## 约束

一个簇的成员时间跨度（max - min）不得超过 ``max_span_days``。
**没有时间戳的帖子不受约束**——"不知道多老" ≠ "很老"，不许凭空排除
（与 recency.age_in_days 的 None 语义一致）。
"""

from __future__ import annotations

import unittest

from backend.agent.public_opinion_core.schemas import OpinionNote
from backend.agent.public_opinion_core.semantic_clustering import (
    DEFAULT_MAX_SPAN_DAYS,
    cluster_notes_semantic,
)


def _note(note_id: str, title: str, publish_time: str, heat: float = 10.0) -> OpinionNote:
    return OpinionNote(
        note_id=note_id,
        platform="xhs",
        title=title,
        content=title,
        publish_time=publish_time,
        heat_score=heat,
        heat_rank=heat / 100.0,
    )


# 同一个方向的向量 = 语义上"完全一样"。这样测的就纯粹是时间约束，
# 排除掉 embedding 相似度的干扰。
_SAME = [1.0, 0.0]
_ALSO_SAME = [0.999, 0.0447]  # 余弦 ≈ 0.999，远超 cluster_threshold


class TimeWindowTests(unittest.TestCase):
    def test_posts_five_years_apart_are_not_one_event(self):
        """线上事故的最小复现：语义几乎相同，但差 5 年。"""

        notes = [
            _note("ks:1", "中山大学东校区封闭管理", "2021-08-14T19:41:50", heat=9839),
            _note("xhs:2", "关于中山大学东校区宿舍搬迁的看法意见", "2026-05-26T00:06:31", heat=588),
            _note("xhs:3", "中大东校区搬宿舍的原因找到了", "2026-05-23T12:40:32", heat=461),
        ]
        vectors = [_SAME, _SAME, _ALSO_SAME]

        result = cluster_notes_semantic(notes, vectors, min_cluster_size=1, max_span_days=90)

        keys_by_note = {}
        for event in result.events:
            for note_id in event.extra["note_ids"]:
                keys_by_note[note_id] = event.event_key

        self.assertNotEqual(
            keys_by_note["ks:1"],
            keys_by_note["xhs:2"],
            "2021 年的疫情封校帖和 2026 年的宿舍搬迁帖被聚成了一件事——"
            "它贡献了该事件 90% 的热度，而那个热度是假的",
        )
        self.assertEqual(
            keys_by_note["xhs:2"],
            keys_by_note["xhs:3"],
            "同期的两条搬迁帖必须还在一起——时间约束不能把真事件也拆散",
        )

    def test_posts_within_the_window_still_cluster_together(self):
        """线上 5 个健康事件跨度是 0/2/2/5/42 天，默认窗口必须一个都不误伤。"""

        notes = [
            _note("a", "中大缩短课间争议", "2026-04-27T10:00:00"),
            _note("b", "中山大学回应缩短课间", "2026-04-29T10:00:00"),
            _note("c", "缩短课间学生反对", "2026-04-30T10:00:00"),
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _SAME, _ALSO_SAME], min_cluster_size=1, max_span_days=90
        )
        self.assertEqual(len(result.events), 1, "跨度 3 天的同一事件被时间约束拆散了")

    def test_the_widest_healthy_event_survives_the_default_window(self):
        """EVT-77「东校区宿舍火情」跨度 42 天，是线上最宽的健康事件。默认值必须容得下。"""

        notes = [
            _note("a", "东校区宿舍起火", "2026-03-24T10:00:00"),
            _note("b", "宿舍火情后续处理", "2026-05-05T10:00:00"),  # 42 天后
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _ALSO_SAME], min_cluster_size=1, max_span_days=DEFAULT_MAX_SPAN_DAYS
        )
        self.assertEqual(
            len(result.events),
            1,
            f"默认窗口 {DEFAULT_MAX_SPAN_DAYS} 天容不下跨度 42 天的真实事件（EVT-77 宿舍火情）",
        )

    def test_a_post_without_a_timestamp_is_never_excluded(self):
        """"不知道多老" ≠ "很老"。没有时间戳的帖子不许被凭空排除。

        与 recency.age_in_days 的 None 语义一致：未知不该被当成"过期"来惩罚。
        """

        notes = [
            _note("a", "宿舍搬迁通知", "2026-05-26T00:00:00"),
            _note("b", "宿舍搬迁讨论", ""),  # 没有时间戳
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _ALSO_SAME], min_cluster_size=1, max_span_days=90
        )
        self.assertEqual(len(result.events), 1, "没有时间戳的帖子被时间约束误伤了")

    def test_chaining_cannot_smuggle_an_old_post_in(self):
        """A(第0天) B(第80天) C(第160天)：B 离两头都在窗口内，但 A 和 C 差 160 天。

        约束的是**整簇的跨度**，不是"离某个成员的距离"——否则一串帖子可以接力
        把一个 5 年前的帖子拖进来。
        """

        notes = [
            _note("a", "话题第一波", "2026-01-01T00:00:00"),
            _note("b", "话题第二波", "2026-03-22T00:00:00"),  # +80 天
            _note("c", "话题第三波", "2026-06-10T00:00:00"),  # +160 天
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _SAME, _SAME], min_cluster_size=1, max_span_days=90
        )

        spans = []
        for event in result.events:
            ids = set(event.extra["note_ids"])
            spans.append(ids)
        self.assertFalse(
            any({"a", "c"} <= ids for ids in spans),
            "第 0 天和第 160 天的帖子通过中间那条接力进了同一个簇——约束的必须是整簇跨度",
        )

    def test_the_guard_can_be_switched_off(self):
        """关掉即回到改造前的行为（消融实验的基线，也是答辩现场的开关）。"""

        notes = [
            _note("old", "中山大学东校区封闭管理", "2021-08-14T19:41:50", heat=9839),
            _note("new", "东校区宿舍搬迁", "2026-05-26T00:06:31", heat=588),
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _ALSO_SAME], min_cluster_size=1, max_span_days=0
        )
        self.assertEqual(len(result.events), 1, "max_span_days=0 应该完全关闭时间约束")


class MergePassTimeWindowTests(unittest.TestCase):
    """质心合并那一趟也要守时间窗——否则贪心拆开的，合并又给缝回去。"""

    def test_the_merge_pass_does_not_reunite_clusters_from_different_years(self):
        notes = [
            _note("old1", "东校区封闭管理", "2021-08-14T00:00:00", heat=9839),
            _note("old2", "东校区封闭管理通知", "2021-08-16T00:00:00", heat=9000),
            _note("new1", "东校区宿舍搬迁", "2026-05-26T00:00:00", heat=588),
            _note("new2", "东校区搬宿舍", "2026-05-23T00:00:00", heat=461),
        ]
        # 四条向量几乎重合：贪心会按时间窗拆成两簇，合并趟必须不能把它们缝回去。
        vectors = [_SAME, _SAME, _SAME, _SAME]

        result = cluster_notes_semantic(
            notes,
            vectors,
            min_cluster_size=1,
            merge_threshold=0.5,  # 故意调低，逼合并趟去尝试合并
            max_span_days=90,
        )

        for event in result.events:
            ids = set(event.extra["note_ids"])
            self.assertFalse(
                ids & {"old1", "old2"} and ids & {"new1", "new2"},
                "合并趟把贪心按时间拆开的两个簇又缝回去了",
            )


if __name__ == "__main__":
    unittest.main()


class RefineMergeTimeWindowTests(unittest.TestCase):
    """LLM 精修的**跨簇同名合并**也要守时间窗——它是时间约束的最后一个洞。

    `llm_refine._merge_by_title` 会把不同 embedding 父簇里"LLM 起了同一个标题"的子簇
    合并回一个事件。这个功能本身是对的（它修的是"同一件校园争议被切成两个同名事件"），
    但它原本**没有时间检查**：

        2024 年的簇 → LLM 起子话题「中大招生宣传」
        2025 年的簇 → LLM 又起子话题「中大招生宣传」
        _merge_by_title 把它俩合了 → 跨度 384 天

    干跑实测：贪心和合并趟都守住了窗，唯独这条路漏了 2 个事件出去
    （「中大招生宣传」384 天、「零散杂项帖」94 天）。子簇是父簇的子集、跨度只会缩小，
    所以能跨年的只可能是**跨父簇拼起来的**——这条路必须补上同一道闸门。
    """

    def test_same_titled_subclusters_from_different_years_do_not_merge(self):
        from backend.agent.public_opinion_core.llm_refine import refine_clusters
        from backend.agent.public_opinion_core.semantic_clustering import _make_cluster

        def note(nid, title, when):
            return OpinionNote(
                note_id=nid, platform="xhs", title=title, content=title,
                publish_time=when, heat_score=10.0, heat_rank=10.0,
            )

        # 两个 embedding 父簇，各自 2 帖，相隔一年多
        old_members = [
            (note("a1", "欢迎报考中山大学", "2024-06-04T00:00:00"), 0, [1.0, 0.0]),
            (note("a2", "中大招生简章", "2024-06-05T00:00:00"), 1, [1.0, 0.0]),
        ]
        new_members = [
            (note("b1", "快来报中大鸭", "2025-06-14T00:00:00"), 2, [0.0, 1.0]),
            (note("b2", "中大校长拍了拍你", "2025-06-20T00:00:00"), 3, [0.0, 1.0]),
        ]
        clusters = [_make_cluster(old_members), _make_cluster(new_members)]

        # 精修器给两个父簇起了**同一个标题** —— 这正是 _merge_by_title 会去合并的情形
        def refiner(_texts):
            return [{"title": "中大招生宣传", "members": [1, 2]}]

        refined, _n, _ejected = refine_clusters(
            clusters,
            refiner=refiner,
            make_cluster=_make_cluster,
            min_size=2,
            warnings=[],
            max_span_days=90,
        )

        for cluster in refined:
            ids = {note.note_id for note, _i, _v in cluster["members"]}
            self.assertFalse(
                ids & {"a1", "a2"} and ids & {"b1", "b2"},
                "跨簇同名合并把 2024 年和 2025 年的帖子拼成了一个事件（干跑里就是这么漏出 384 天的）",
            )

    def test_same_titled_subclusters_within_the_window_still_merge(self):
        """不能因噎废食：同期的同名子簇必须还能合并（这个功能本来是对的）。"""

        from backend.agent.public_opinion_core.llm_refine import refine_clusters
        from backend.agent.public_opinion_core.semantic_clustering import _make_cluster

        def note(nid, title, when):
            return OpinionNote(
                note_id=nid, platform="xhs", title=title, content=title,
                publish_time=when, heat_score=10.0, heat_rank=10.0,
            )

        left = [
            (note("a1", "作息调整争议", "2026-04-27T00:00:00"), 0, [1.0, 0.0]),
            (note("a2", "作息调整反对", "2026-04-28T00:00:00"), 1, [1.0, 0.0]),
        ]
        right = [
            (note("b1", "新作息时间", "2026-04-29T00:00:00"), 2, [0.0, 1.0]),
            (note("b2", "校方回应作息", "2026-04-30T00:00:00"), 3, [0.0, 1.0]),
        ]
        clusters = [_make_cluster(left), _make_cluster(right)]

        def refiner(_texts):
            return [{"title": "中大作息调整争议", "members": [1, 2]}]

        refined, _n, _e = refine_clusters(
            clusters, refiner=refiner, make_cluster=_make_cluster,
            min_size=2, warnings=[], max_span_days=90,
        )

        merged = [
            c for c in refined
            if {n.note_id for n, _i, _v in c["members"]} >= {"a1", "b1"}
        ]
        self.assertEqual(
            len(merged), 1,
            "同一周内的两个同名子簇被时间窗误拆了——那正是 _merge_by_title 本来要修的毛病",
        )


class EventKeyCollisionTests(unittest.TestCase):
    """event_key 必须在一轮里唯一——两个簇撞一个 key，数据库就会串味。

    ## 线上事故（本次时间窗改造直接放大出来的）

    `_new_key_and_title` 只哈希**热度最高那条成员帖的标题**：

        digest = sha1(top_note.title)[:8]   ->   event_key = f"sem:{digest}"

    两个不同的簇完全可能有同名的头帖（同一篇文章在不同年份被转发）。改造前它俩本来
    在一个簇里，不会撞；**时间窗把它们按年份拆开之后，两个簇各自拿同一个标题去算 key
    —— 撞了。**

    后果（真实数据，重跑后）：65 个事件只有 60 个不同的 key，5 对撞车。
    `persist_public_events` 用 event_key 做 upsert 主键：

        事件行  ->  后写的覆盖先写的（source_count 只剩一个）
        链接    ->  两个簇的 link **都**写进去（3 + 2 = 5 条）

    于是 EVT-72 声称 3 个成员，链接表里挂着 5 条——其中 2 条是**另一个簇**的帖子。
    真实表现：已发布的「项飙中大对谈」里混进了「广州雨天好去处」和「我好像拍到了他们
    的人生照片」。

    ## 为什么不干脆改成按成员集合哈希

    那会让**每一个** event_key 都变，跨轮次记忆对齐全部失效，7 个已发布事件一夜之间
    变成孤儿。所以：**保留按标题的 key（稳定性），只在真撞车时消歧**。
    """

    def test_two_clusters_with_the_same_top_title_get_different_keys(self):
        # 同一篇文章在 2021 和 2026 各被转发一次：标题一模一样，但时间窗会把它们拆成两簇。
        notes = [
            _note("old:1", "中山大学东校区封闭管理", "2021-08-14T00:00:00", heat=9839),
            _note("old:2", "东校区管理通知", "2021-08-15T00:00:00", heat=100),
            _note("new:1", "中山大学东校区封闭管理", "2026-05-26T00:00:00", heat=9838),  # 同名转发
            _note("new:2", "东校区管理新规", "2026-05-27T00:00:00", heat=100),
        ]
        result = cluster_notes_semantic(
            notes,
            [_SAME, _SAME, _SAME, _SAME],
            min_cluster_size=1,
            max_span_days=90,
        )

        keys = [e.event_key for e in result.events]
        self.assertEqual(
            len(keys),
            len(set(keys)),
            f"两个簇撞了同一个 event_key：{keys}。"
            f"落库时事件行会互相覆盖、链接会互相叠加——已发布事件里会混进别的簇的帖子",
        )

    def test_a_single_cluster_keeps_its_title_derived_key(self):
        """没撞车时，key 必须还是"按头帖标题哈希"的老样子——跨轮次记忆对齐依赖它的稳定性。"""

        import hashlib

        notes = [
            _note("a", "东校区宿舍搬迁", "2026-05-26T00:00:00", heat=588),
            _note("b", "搬宿舍讨论", "2026-05-27T00:00:00", heat=100),
        ]
        result = cluster_notes_semantic(
            notes, [_SAME, _SAME], min_cluster_size=1, max_span_days=90
        )

        expected = "sem:" + hashlib.sha1("东校区宿舍搬迁".encode("utf-8")).hexdigest()[:8]
        self.assertEqual(
            result.events[0].event_key,
            expected,
            "没撞车的簇 key 变了 —— 跨轮次对齐会失效，已发布事件会变成孤儿",
        )
