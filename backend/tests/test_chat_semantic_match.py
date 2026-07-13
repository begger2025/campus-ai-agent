"""事件层的第二道检索：**语义匹配**——用户怎么说，系统都得认得出是哪件事。

## 线上事故

用户问「东校宿舍搬迁」，Agent 回答"未检索到相关事件数据，events 为空"。

而库里躺着的事件叫「东校**区**宿舍搬迁」。**差一个「区」字**，`LIKE '%东校宿舍搬迁%'`
就整个匹配不上——事件标题、摘要、5 条代表帖，没有一个含这个连续子串（它们全都是
"东校区宿舍搬迁"）。事件层返回 0，兜底层用同样的 LIKE 查帖子也是 0。

这不是某一处写错了，是**字面检索的天花板**：中文的同一件事有无数种说法，而
`LIKE` 只认连续子串。代表帖上浮能救「搬宿舍」（因为帖子里真的有这三个字），
救不了「提问时的用词和数据差一个字」。

## 实测的语义信号（BAAI/bge-small-zh，余弦）

    提问              最佳匹配事件        余弦    次高
    东校宿舍搬迁       东校区宿舍搬迁      0.98    0.50
    宿舍搬迁          东校区宿舍搬迁      0.88    0.53
    搬宿舍            东校区宿舍搬迁      0.81    0.52
    东校区换宿舍       东校区宿舍搬迁      0.88    0.49   ← 完全不同的说法
    学术不端          ~~课间缩短争议~~    0.52    论文调查 0.49   ← 语义排错了！
    食堂             （无食堂事件）       0.43    —

三条结论决定了这个设计：

1. **改写类查询的语义信号极强**（0.81~0.98，次高才 0.50）——阈值 0.70 稳稳分开。
2. **语义不能盖过字面**：「学术不端」的语义最高分是**错的事件**（课间缩短 0.52 >
   论文调查 0.49），而字面通过代表帖上浮能正确命中论文调查。所以**字面优先，语义补位**。
3. **没有对应事件时语义分很低**（食堂 0.43）——阈值能正确拒绝，老实回落帖子层。

## 三层顺序

    ① 字面命中（LIKE 标题/摘要/代表帖）  精确，「学术不端」靠它
    ② 语义命中（余弦 ≥ 阈值）           认改写，「东校宿舍搬迁」靠它
    ③ 帖子层兜底                       都不中时，「食堂」靠它
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
from backend.services import event_read_model
from backend.services.event_read_model import query_published_events


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# 打桩的"embedding"：不装 sentence-transformers 也能跑，且余弦值可控。
# 每个词映射到一个方向，句子向量 = 词向量之和再归一化。
_AXES = {
    "宿舍": [1.0, 0.0, 0.0, 0.0],
    "搬迁": [0.0, 1.0, 0.0, 0.0],
    "东校": [0.0, 0.0, 0.3, 0.0],  # 弱轴：加不加「区」都只微调方向
    "论文": [0.0, 0.0, 0.0, 1.0],
    "食堂": [0.0, 0.0, 0.0, -1.0],
}


def _fake_embed(texts: list[str]) -> list[list[float]]:
    import math

    vectors = []
    for text in texts:
        vec = [0.0, 0.0, 0.0, 0.0]
        for word, axis in _AXES.items():
            if word in text:
                for i, value in enumerate(axis):
                    vec[i] += value
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


class SemanticEventMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()
        event_read_model.reset_title_embeddings()

        # 事件标题带「区」；用户会打成「东校宿舍搬迁」（不带区）
        self.relocation = PublicEvent(
            event_key="sem:relocation",
            title="东校区宿舍搬迁",
            summary="东校区宿舍搬迁共聚合 5 条内容。",
            status="published",
            risk_level="medium",
            risk_score=63.0,
            heat_score=1142.0,
            source_count=5,
            date_range_json=json.dumps({"event_time": _iso(5), "member_times": [_iso(5), _iso(6)]}),
        )
        self.paper = PublicEvent(
            event_key="sem:paper",
            title="中大康某论文调查",
            summary="中大康某论文调查共聚合 3 条内容。",
            status="published",
            risk_level="high",
            risk_score=80.0,
            heat_score=11300.0,
            source_count=3,
            date_range_json=json.dumps({"event_time": _iso(60), "member_times": [_iso(60), _iso(1)]}),
        )
        self.db.add_all([self.relocation, self.paper])
        self.db.commit()

        post = ProcessedPost(
            note_id="xhs:relo",
            raw_post_id=1,
            platform="xhs",
            title="关于中山大学东校区宿舍搬迁的看法意见",
            content="搬迁通知太仓促。",
            source_keyword="中山大学 东校宿舍搬迁",
            heat_score=588.0,
            heat_rank=18.5,
            sentiment="negative",
            risk_level="medium",
            publish_time=NOW - timedelta(days=5),
        )
        self.db.add(post)
        self.db.commit()
        self.db.add(
            EventPostLink(
                event_id=self.relocation.id,
                processed_post_id=post.id,
                raw_post_id=post.raw_post_id,
                rank=1,
                role="representative",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        event_read_model.reset_title_embeddings()
        self.db.close()

    def _query(self, keyword: str):
        with mock.patch.object(event_read_model, "get_embedder", return_value=_fake_embed):
            return query_published_events(self.db, keyword=keyword, now=NOW)

    def test_a_one_character_paraphrase_still_finds_the_event(self):
        """线上事故的最小复现：用户少打一个「区」字。"""

        titles = [event.title for event in self._query("东校宿舍搬迁")]

        self.assertIn(
            "东校区宿舍搬迁",
            titles,
            "用户少打一个「区」字，整个事件就检索不到了 —— LIKE 只认连续子串",
        )

    def test_a_topic_with_no_matching_event_is_still_rejected(self):
        """食堂没有对应事件，语义分不够，必须返回空 —— 让调用方回落到帖子层。

        这一条比"能找到"更要紧：语义匹配一旦滥召回，用户问食堂会拿到一份论文调查简报。
        """

        self.assertEqual(
            self._query("食堂"),
            [],
            "没有对应事件时语义层必须承认找不到，而不是硬塞一个最像的给用户",
        )

    def test_the_literal_match_wins_when_both_could_fire(self):
        """字面命中时**不跑**语义——实测「学术不端」的语义最高分是错的事件。

        真实数据（BAAI/bge-small-zh）：
            学术不端 → 中大课间缩短争议 0.52   ← 语义排第一，但它是错的
                     → 中大康某论文调查 0.49   ← 正确答案排第二
        而字面通过代表帖上浮能正确命中论文调查。所以语义只在字面**颗粒无收**时才补位。
        """

        embed_calls = []

        def counting_embed(texts):
            embed_calls.append(texts)
            return _fake_embed(texts)

        with mock.patch.object(event_read_model, "get_embedder", return_value=counting_embed):
            events = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)

        self.assertEqual([e.title for e in events], ["东校区宿舍搬迁"])
        self.assertEqual(
            embed_calls,
            [],
            "字面已经命中了还去跑语义 —— 白付一次 embedding，还可能被错误的语义结果污染",
        )

    def test_no_embedder_degrades_to_literal_only(self):
        """没装 sentence-transformers / 关掉语义时，行为退回改造前，绝不报错。"""

        with mock.patch.object(event_read_model, "get_embedder", return_value=None):
            self.assertEqual(query_published_events(self.db, keyword="东校宿舍搬迁", now=NOW), [])
            hit = query_published_events(self.db, keyword="宿舍搬迁", now=NOW)

        self.assertEqual([e.title for e in hit], ["东校区宿舍搬迁"], "字面路径必须照常工作")

    def test_a_broken_embedder_does_not_break_the_chat(self):
        """embedding 抛异常时降级，不能让整个对话失败。"""

        def exploding(_texts):
            raise RuntimeError("模型没加载起来")

        with mock.patch.object(event_read_model, "get_embedder", return_value=exploding):
            self.assertEqual(query_published_events(self.db, keyword="东校宿舍搬迁", now=NOW), [])

    def test_event_titles_are_embedded_once_not_per_query(self):
        """标题向量要缓存：每次提问都把 7 个标题重新 embed 一遍是纯浪费。"""

        calls = []

        def counting_embed(texts):
            calls.append(list(texts))
            return _fake_embed(texts)

        with mock.patch.object(event_read_model, "get_embedder", return_value=counting_embed):
            self._q = query_published_events(self.db, keyword="东校宿舍搬迁", now=NOW)
            query_published_events(self.db, keyword="东校宿舍搬迁", now=NOW)

        # 每次提问必须 embed 提问本身；标题只该 embed 一次。
        title_batches = [batch for batch in calls if "东校区宿舍搬迁" in batch]
        self.assertEqual(len(title_batches), 1, f"事件标题被反复 embed 了：{calls}")


if __name__ == "__main__":
    unittest.main()


class ThresholdCalibrationTests(unittest.TestCase):
    """阈值不是拍脑袋定的，是在真实事件标题上标定出来的——把标定结果钉进测试。

    在**当前 10 个已发布事件**上实测（BAAI/bge-small-zh，余弦）：

        该命中的（改写）                       该拒绝的（库里没有对应事件）
          东校宿舍搬迁 → 东校区宿舍搬迁  0.98      宿舍热水 → 宿舍火情通报  0.56  ← 拒绝里最高
          东校区换宿舍 → 东校区宿舍搬迁  0.88      考研    → 康某论文调查  0.45
          举报副院长   → 耿同学举报副院长 0.84      食堂    → 东校区宿舍搬迁 0.43
          搬宿舍      → 东校区宿舍搬迁  0.81      图书馆   → 东校区宿舍搬迁 0.39
          课间时间缩短 → 中大课间缩短争议 0.76      天气    → 宿舍火情通报  0.32
          宿舍火灾    → 中大宿舍火情通报  0.70
          宿舍着火/起火 → 中大宿舍火情通报 0.67
          论文造假    → 中大康某论文调查  0.54  ← 漏网

    **没有干净的阈值**：该命中的最低分（0.54）比该拒绝的最高分（0.56）还低。
    0.65 是权衡出来的最优点（命中 8/9、正确拒绝 5/5），失败方向选的是"宁可返回空"。

    这个类锁住两件事：
      1. 阈值必须落在 [0.57, 0.67] —— 低于 0.57 会把「宿舍热水」误答成火情简报，
         高于 0.67 会把「宿舍着火」挡在门外（库里明明有火情事件）。
      2. 阈值可以被 .env 覆盖（答辩现场调参 / 消融实验）。
    """

    def test_the_threshold_sits_in_the_calibrated_band(self):
        from backend.services.llm_config import EVENT_SEMANTIC_MATCH_THRESHOLD

        self.assertGreater(
            EVENT_SEMANTIC_MATCH_THRESHOLD,
            0.56,
            "阈值 ≤ 0.56 会让「宿舍热水」（实测 0.56，库里没有热水事件）命中火情事件——"
            "用户问热水，Agent 答一份宿舍火灾简报",
        )
        self.assertLessEqual(
            EVENT_SEMANTIC_MATCH_THRESHOLD,
            0.67,
            "阈值 > 0.67 会把「宿舍着火」（实测 0.67）挡在门外——库里明明有「中大宿舍火情通报」",
        )

    def test_the_threshold_is_configurable(self):
        """答辩现场调参 / 消融实验要能改它。"""

        import os
        from backend.services.llm_config import _read_float

        os.environ["_TEST_THRESHOLD"] = "0.9"
        try:
            self.assertEqual(_read_float("_TEST_THRESHOLD", 0.65), 0.9)
        finally:
            os.environ.pop("_TEST_THRESHOLD", None)
