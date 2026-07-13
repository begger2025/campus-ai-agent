"""关键词检索的精确性：`source_keyword` 是"我们搜的时候用的词"，不是"帖子在讲什么"。

真实事故（线上数据，2026-07）：用户让 Agent「生成宿舍搬迁舆情简报」，Agent 回答
"未检索到可直接证明宿舍搬迁事件的代表性帖子"。查下来 Agent 是对的，**检索层在骗它**：

    爬虫拿「中山大学 东校宿舍搬迁」去小红书搜 → 小红书搜不到精确匹配，
    退而返回 34 条泛泛的中大帖子（97岁生日快乐 / 灵异事件 / 摆摊一条街 / 骂校长）
    → 这 34 条被盖上 source_keyword = "中山大学 东校宿舍搬迁"
    → 检索 `LIKE '%宿舍搬迁%'` 命中 source_keyword，34 条全被当成"宿舍搬迁舆情"
    → 其中正文真的提到「搬迁」的：**1 条**（97% 是噪声）
    → 而噪声的热度高达 16 万，真帖只有 588 —— 送进 prompt 的代表帖全是噪声

污染率随关键词的**具体程度**上升，而具体的话题恰恰是舆情最该关心的：
    宿舍搬迁 97% | 食堂 54% | 宿舍 52% | 学术不端 0% | 计算机 3%

`source_keyword` 记录的是采集来源（保留它有溯源价值），但它**不能参与内容检索**。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import ProcessedPost
from backend.services.public_opinion_adapter import count_agent_rows, query_agent_rows


class KeywordRetrievalPrecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=[ProcessedPost.__table__])
        self.db = sessionmaker(bind=self.engine)()

        # 真帖：正文真的在讲搬迁（热度很低——真实数据就是这样）
        self.db.add(
            ProcessedPost(
                note_id="xhs:real",
                raw_post_id=1,
                platform="xhs",
                title="关于中山大学东校区宿舍搬迁的看法",
                content="搬迁通知太仓促了，行李无处安置。",
                source_keyword="中山大学 东校宿舍搬迁",
                heat_score=588,
            )
        )
        # 噪声：小红书拿来凑数的泛泛中大帖，只有 source_keyword 沾边，热度却高 280 倍
        for i, title in enumerate(
            [
                "中山大学，97岁生日快乐！",
                "中山大学灵异事件",
                "深圳光明中山大学东园门口，免费摆摊一条街！",
                "吃饭，睡觉，骂校长，这都快成了中山学子的日常了！",
            ]
        ):
            self.db.add(
                ProcessedPost(
                    note_id=f"xhs:noise{i}",
                    raw_post_id=100 + i,
                    platform="xhs",
                    title=title,
                    content="和搬迁毫无关系的内容。",
                    source_keyword="中山大学 东校宿舍搬迁",
                    heat_score=164868 - i * 1000,
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_a_topic_search_returns_only_posts_that_actually_discuss_the_topic(self):
        rows = query_agent_rows(self.db, keyword="宿舍搬迁", limit=0)
        titles = [row["title"] for row in rows]

        self.assertEqual(
            len(rows),
            1,
            "检索把爬虫「搜索时用过的词」当成了「帖子在讲的词」——"
            f"97 岁生日快乐和灵异事件被当成了宿舍搬迁舆情。实际捞回：{titles}",
        )
        self.assertIn("宿舍搬迁", titles[0])

    def test_the_count_matches_what_the_search_returns(self):
        """计数和取数必须一致，否则界面会显示「34 条相关」却只拿得出 1 条。"""

        self.assertEqual(count_agent_rows(self.db, keyword="宿舍搬迁"), 1)

    def test_a_post_is_still_found_by_its_content_not_just_its_title(self):
        self.db.add(
            ProcessedPost(
                note_id="xhs:body",
                raw_post_id=200,
                platform="xhs",
                title="东校区的兄弟们看过来",
                content="宿舍搬迁的补偿方案出来了吗？",
                source_keyword="中山大学",
                heat_score=100,
            )
        )
        self.db.commit()
        rows = query_agent_rows(self.db, keyword="宿舍搬迁", limit=0)
        self.assertEqual(len(rows), 2, "正文里提到话题的帖子必须仍然能被检索到")

    def test_a_post_is_still_found_by_its_tags(self):
        """话题标签是用户自己打的，属于「帖子在讲什么」，必须保留。"""

        self.db.add(
            ProcessedPost(
                note_id="xhs:tagged",
                raw_post_id=300,
                platform="xhs",
                title="东校区的一天",
                content="随手拍。",
                tags_json='[{"tag": "宿舍搬迁"}]',
                source_keyword="中山大学",
                heat_score=100,
            )
        )
        self.db.commit()
        rows = query_agent_rows(self.db, keyword="宿舍搬迁", limit=0)
        self.assertEqual(len(rows), 2, "用户打的话题标签是内容的一部分，不能连它一起砍掉")

    def test_source_keyword_is_still_stored_for_provenance(self):
        """砍的是「拿它做内容检索」，不是「不再记录它」——溯源要靠它。"""

        rows = query_agent_rows(self.db, keyword="宿舍搬迁", limit=0)
        self.assertEqual(rows[0]["source_keyword"], "中山大学 东校宿舍搬迁")


if __name__ == "__main__":
    unittest.main()
