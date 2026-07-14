"""帖子层语义检索：离线向量 + 在线余弦 top-k，字面命中优先、语义补集。

## 为什么

帖子层检索只有 LIKE：「饭堂涨价」搜不到「食堂调价」，「宿舍太吵」搜不到
「半夜宿舍楼道有噪音」。事件层早有语义兜底（标题匹配），帖子层一直是裸的——
而帖子层恰恰是没有已发布事件的话题的唯一出路。

## 边界（防语义假阳性——本方案唯一的发散风险）

- 阈值之下一律不取：宁可漏，不能把不相关的帖捞进 prompt（静默错误答案）；
- 字面命中永远优先入集，语义只**补**字面漏掉的；
- 向量文件缺失 / 模型不可用 / 任何异常 → 空列表，检索退回纯字面（降级不报错）。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import ProcessedPost
from backend.services import semantic_posts
from backend.services.public_opinion_adapter import query_agent_rows
from backend.services.semantic_posts import semantic_post_ids, top_ids_by_cosine


def _vec(x: float, y: float) -> list[float]:
    norm = (x * x + y * y) ** 0.5
    return [x / norm, y / norm]


class TopIdsByCosineTests(unittest.TestCase):
    """纯函数：矩阵 × 查询向量 → 阈值之上按相似度排序的 id。"""

    def setUp(self) -> None:
        self.ids = np.array([11, 22, 33], dtype=np.int64)
        self.matrix = np.array([_vec(1, 0), _vec(1, 1), _vec(0, 1)], dtype=np.float32)

    def test_orders_by_similarity_and_cuts_at_threshold(self) -> None:
        got = top_ids_by_cosine(self.matrix, self.ids, np.array(_vec(1, 0.2)), top_k=3, threshold=0.5)

        self.assertEqual(got[0], 11, "最相似的排最前")
        self.assertNotIn(33, got, "阈值之下的绝不能进——语义假阳性是静默错误答案")

    def test_top_k_caps_the_result(self) -> None:
        got = top_ids_by_cosine(self.matrix, self.ids, np.array(_vec(1, 1)), top_k=1, threshold=0.0)

        self.assertEqual(len(got), 1)


class SemanticPostIdsTests(unittest.TestCase):
    """服务层：加载 npz + 查询 embed + 降级语义。"""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "post_vectors.npz"
        np.savez(
            self.path,
            ids=np.array([11, 22, 33], dtype=np.int64),
            vectors=np.array([_vec(1, 0), _vec(1, 1), _vec(0, 1)], dtype=np.float32),
        )
        semantic_posts.reset_vector_cache()
        self.addCleanup(semantic_posts.reset_vector_cache)

    def _fake_embedder(self, vec):
        return lambda texts: [list(vec) for _ in texts]

    def test_returns_ids_above_threshold(self) -> None:
        with (
            mock.patch.object(semantic_posts, "get_embedder", return_value=self._fake_embedder(_vec(1, 0.1))),
            mock.patch.object(semantic_posts, "_vectors_path", return_value=self.path),
        ):
            got = semantic_post_ids("饭堂涨价", top_k=2, threshold=0.6)

        self.assertEqual(got[0], 11)
        self.assertNotIn(33, got)

    def test_missing_file_degrades_to_empty(self) -> None:
        with (
            mock.patch.object(semantic_posts, "get_embedder", return_value=self._fake_embedder(_vec(1, 0))),
            mock.patch.object(semantic_posts, "_vectors_path", return_value=Path(self.tmp.name) / "nope.npz"),
        ):
            self.assertEqual(semantic_post_ids("任何话题"), [])

    def test_no_embedder_degrades_to_empty(self) -> None:
        with mock.patch.object(semantic_posts, "get_embedder", return_value=None):
            self.assertEqual(semantic_post_ids("任何话题"), [])

    def test_blank_query_returns_empty(self) -> None:
        with mock.patch.object(semantic_posts, "get_embedder", return_value=self._fake_embedder(_vec(1, 0))):
            self.assertEqual(semantic_post_ids("  "), [])

    def test_embedder_exception_degrades_to_empty(self) -> None:
        def boom(_texts):
            raise RuntimeError("model exploded")

        with (
            mock.patch.object(semantic_posts, "get_embedder", return_value=boom),
            mock.patch.object(semantic_posts, "_vectors_path", return_value=self.path),
        ):
            self.assertEqual(semantic_post_ids("任何话题"), [])


class QueryAgentRowsByIdsTests(unittest.TestCase):
    """适配器按 id 取数：语义候选也必须过同一道剔除过滤。"""

    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[ProcessedPost.__table__])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        for note_id, title, excluded in [
            ("a", "食堂调价通知", False),
            ("b", "被剔除的广告", True),
            ("c", "宿舍噪音", False),
        ]:
            self.db.add(
                ProcessedPost(
                    note_id=note_id,
                    raw_post_id=ord(note_id),
                    platform="xhs",
                    title=title,
                    content="内容",
                    excluded=excluded,
                )
            )
        self.db.commit()
        self.id_by_note = {
            row.note_id: row.id for row in self.db.query(ProcessedPost).all()
        }

    def test_fetches_by_ids_in_given_order(self) -> None:
        wanted = [self.id_by_note["c"], self.id_by_note["a"]]

        rows = query_agent_rows(self.db, ids=wanted)

        self.assertEqual([row["title"] for row in rows], ["宿舍噪音", "食堂调价通知"], "保持语义相似度的顺序")

    def test_excluded_posts_never_come_back_even_by_id(self) -> None:
        rows = query_agent_rows(self.db, ids=[self.id_by_note["b"]])

        self.assertEqual(rows, [], "剔除切断所有下游——语义检索也不例外，否则又是静默错误答案")


if __name__ == "__main__":
    unittest.main()
