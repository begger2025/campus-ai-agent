"""检索的第三层：**LLM 裁决**——只判算术拿不准的那条模糊带。

## 为什么需要它（实测，不是假设）

语义匹配（余弦）在真实事件标题上标定的结果里，藏着一个无解的重叠：

    该命中的最低分 : 0.54   （论文造假 → 中大康某论文调查）
    该拒绝的最高分 : 0.56   （宿舍热水 → 中大宿舍火情通报）

**该命中的比该拒绝的分还低。** 没有任何一个阈值能分开它们——这不是阈值没调好，
而是**这件事本身不是"可测量"的**：

  - 余弦只回答「这两段文本有多像」——一个标量。
  - 用户真正的问题是「**我问的是不是这件事**」——那是**判断**。

「宿舍热水」和「宿舍火情」字面和语义都很像（都是宿舍后勤问题），但**不是同一件事**；
「论文造假」和「康某论文调查」字面毫不沾边，但**就是同一件事**。余弦分不开这个，
因为它没有"是不是"的概念，只有"像不像"。

这正是项目那条论断的递归应用：

    **可测量的用算术** —— 「这两段文本有多像」→ 余弦，12 毫秒，免费
    **需要判断的用 AI** —— 「用户问的是不是这件事」→ LLM，0.8 秒

## 级联：AI 只判它拿不准的

    余弦 ≥ HIGH(0.65)   → 直接采纳      （8/8 全对，不花钱）
    余弦 <  LOW (0.45)  → 直接拒绝      （3/3 全对，不花钱）
    LOW ≤ 余弦 < HIGH   → **LLM 裁决**  （3/14 落在这里，正是算术束手无策的）

## 模型选型（14 条评测集实测）

    glm-4-plus    14/14   0.8s   ← 选它（.env 里已配）
    glm-4-air     14/14   1.1s
    glm-4-flashx  13/14   0.6s   ← 便宜的 flash 在「论文造假」上和 embedding 犯同一个错
    glm-4-flash   13/14   1.3s   ← 同上
    gpt-5.4       14/14   3.6s
    gpt-4o-mini   不可用（InternalServerError）

**省钱省不出判断力**：flash 系列快、便宜，但它们也分不开"像"和"是"。
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


# 打桩的余弦：直接给定每个提问对每个事件的分数，把测试focus在**级联的决策逻辑**上，
# 而不是 embedding 模型本身（那个已经在 test_chat_semantic_match 里测过了）。
# 分数取自真实标定。
_SCORES = {
    "论文造假": {"中大康某论文调查": 0.54, "东校区宿舍搬迁": 0.30},  # 模糊带，该命中
    "宿舍热水": {"中大康某论文调查": 0.20, "东校区宿舍搬迁": 0.56},  # 模糊带，该拒绝
    "东校宿舍搬迁": {"中大康某论文调查": 0.36, "东校区宿舍搬迁": 0.98},  # 高分，直接采纳
    "天气": {"中大康某论文调查": 0.30, "东校区宿舍搬迁": 0.32},  # 低分，直接拒绝
}


def _fake_embed_factory(question: str):
    """造一组向量，让 cos(提问, 事件标题) 正好等于 _SCORES 里给定的分数。

    做法：提问 = e0；每个标题 = s·e0 + sqrt(1-s²)·e_i（各自一根正交轴）。
    """

    import math

    titles = sorted(_SCORES[question])
    dim = 1 + len(titles)

    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if text == question:
                vec = [0.0] * dim
                vec[0] = 1.0
            elif text in _SCORES[question]:
                score = _SCORES[question][text]
                vec = [0.0] * dim
                vec[0] = score
                vec[1 + titles.index(text)] = math.sqrt(max(1.0 - score * score, 0.0))
            else:
                vec = [0.0] * dim
                vec[0] = 0.0
            vectors.append(vec)
        return vectors

    return embed


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()
        event_read_model.reset_title_embeddings()

        for key, title, risk in [
            ("sem:paper", "中大康某论文调查", "high"),
            ("sem:relo", "东校区宿舍搬迁", "medium"),
        ]:
            self.db.add(
                PublicEvent(
                    event_key=key,
                    title=title,
                    summary=f"{title}共聚合若干条内容。",
                    status="published",
                    risk_level=risk,
                    risk_score=70.0,
                    heat_score=1000.0,
                    source_count=3,
                    date_range_json=json.dumps(
                        {"event_time": _iso(5), "member_times": [_iso(5), _iso(6)]}
                    ),
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        event_read_model.reset_title_embeddings()
        self.db.close()

    def _query(self, question: str, judge=None):
        with mock.patch.object(
            event_read_model, "get_embedder", return_value=_fake_embed_factory(question)
        ), mock.patch.object(event_read_model, "judge_event_match", side_effect=judge or (lambda *_a, **_k: None)):
            return query_published_events(self.db, keyword=question, now=NOW)


class CascadeTests(_Fixture):
    def test_the_llm_rescues_a_hit_the_cosine_gives_up_on(self):
        """「论文造假」余弦只有 0.54（低于 0.65 的采纳线）—— 算术放弃，AI 捞回来。"""

        judge = mock.Mock(return_value="中大康某论文调查")
        titles = [e.title for e in self._query("论文造假", judge=judge)]

        judge.assert_called_once()
        self.assertEqual(
            titles,
            ["中大康某论文调查"],
            "余弦 0.54 判不出「论文造假 = 康某论文调查」，LLM 裁决必须把它捞回来",
        )

    def test_the_llm_rejects_a_near_miss_the_cosine_would_have_accepted(self):
        """「宿舍热水」余弦 0.56——比「论文造假」还高。阈值一旦调低到能捞回论文造假，
        它就会把热水问题答成一份宿舍火灾/搬迁简报。LLM 必须把它挡回去。
        """

        judge = mock.Mock(return_value=None)  # LLM 判定：都不是
        events = self._query("宿舍热水", judge=judge)

        judge.assert_called_once()
        self.assertEqual(
            events,
            [],
            "LLM 判了「都不是」，事件层就必须返回空、让调用方回落帖子层——"
            "而不是硬塞一个 0.56 分的最像的给用户",
        )

    def test_a_confident_cosine_hit_does_not_pay_for_the_llm(self):
        """余弦 0.98 已经很确定了——再花 0.8 秒问 LLM 是纯浪费。"""

        judge = mock.Mock(return_value="东校区宿舍搬迁")
        titles = [e.title for e in self._query("东校宿舍搬迁", judge=judge)]

        self.assertEqual(titles, ["东校区宿舍搬迁"])
        judge.assert_not_called()

    def test_a_confident_cosine_reject_does_not_pay_for_the_llm(self):
        """「天气」最高才 0.32——明显不是任何事件，不必惊动 LLM。"""

        judge = mock.Mock(return_value=None)
        events = self._query("天气", judge=judge)

        self.assertEqual(events, [])
        judge.assert_not_called()


class DegradationTests(_Fixture):
    """裁决层挂了，聊天不能跟着挂——退回纯余弦的行为。"""

    def test_a_failing_judge_falls_back_to_the_cosine_verdict(self):
        def exploding(*_args, **_kwargs):
            raise RuntimeError("GLM 挂了")

        # 论文造假 0.54 < 0.65 -> 裁决失败 -> 按余弦的原判（拒绝）-> 回落帖子层
        self.assertEqual(self._query("论文造假", judge=exploding), [])

    def test_a_judge_that_names_an_unknown_event_is_ignored(self):
        """模型编了个不存在的事件标题（幻觉）—— 必须当作「都不是」，不能凭空造事件。"""

        judge = mock.Mock(return_value="中大食堂涨价争议")  # 库里没有这个事件
        self.assertEqual(self._query("论文造假", judge=judge), [])

    def test_the_judge_can_be_switched_off(self):
        """关掉即回到纯余弦（消融基线 / 答辩现场开关）。"""

        judge = mock.Mock(return_value="中大康某论文调查")
        with mock.patch.object(event_read_model, "EVENT_JUDGE_ENABLED", False):
            events = self._query("论文造假", judge=judge)

        judge.assert_not_called()
        self.assertEqual(events, [], "关掉裁决后，0.54 分的论文造假应该照旧被余弦拒绝")


class BandCalibrationTests(unittest.TestCase):
    """模糊带的两条边是标定出来的，钉死它们。"""

    def test_the_band_brackets_the_cases_arithmetic_cannot_resolve(self):
        from backend.services.llm_config import (
            EVENT_SEMANTIC_LOW_THRESHOLD,
            EVENT_SEMANTIC_MATCH_THRESHOLD,
        )

        # 实测：论文造假 0.54（该命中）、宿舍热水 0.56（该拒绝）—— 两个都必须落进带里，
        # 否则算术会自作主张，而它在这两个上恰好是错的。
        for score in (0.54, 0.56):
            self.assertGreaterEqual(
                score,
                EVENT_SEMANTIC_LOW_THRESHOLD,
                f"{score} 落在下界之外 —— 算术会直接拒绝，「论文造假」再也捞不回来",
            )
            self.assertLess(
                score,
                EVENT_SEMANTIC_MATCH_THRESHOLD,
                f"{score} 落在上界之外 —— 算术会直接采纳，「宿舍热水」会被答成火情简报",
            )

        # 明显的两头必须落在带外，别为了它们白付 0.8 秒。
        self.assertLess(0.43, EVENT_SEMANTIC_LOW_THRESHOLD, "食堂 0.43 该被余弦直接拒绝")
        self.assertGreaterEqual(0.67, EVENT_SEMANTIC_MATCH_THRESHOLD, "宿舍着火 0.67 该被余弦直接采纳")


if __name__ == "__main__":
    unittest.main()
