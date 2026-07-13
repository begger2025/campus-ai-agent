"""舆情分析页的帖子接口：查**已分析**的帖子，统计和检索都在服务端做。

## 这个接口为什么必须新开一个（2026-07-14 审核）

舆情分析页原本读 `/api/posts`，而那个接口查的是 **raw_posts**——爬虫抓回来的原始帖，
**没有 sentiment、没有 risk_level**（那是 processed_posts 才有的东西）。于是：

  - 页面上每条帖子的风险徽章永远显示「—」（读一个不存在的字段）；
  - 右上角的风险筛选器对帖子完全不起作用；
  - 一个叫「舆情**分析**」的页面，展示的却是**没有经过任何分析**的数据。

顺带修掉两个**静默**谎言：

  1. **「帖子总数 100」是假的**（真实 403）。前端拿 `posts.length` 当总数，而它请求的
     page_size 上限恰好是 100——这个数字永远是 100，库里有 403 条还是 4000 条都一样。
     后端其实一直在返回真实 total，前端把它扔了。
  2. **搜索只在已加载的那 100 条里搜**（库里 397 条已分析帖）。用户搜「食堂」，
     第 101 条之后的食堂帖一条都搜不到——而页面看起来像是搜了全库。
     检索必须在服务端做，覆盖全集。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models import ProcessedPost


NOW = datetime(2026, 7, 14, 12, 0, 0)


class SentimentPostsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _add(self, **kwargs) -> None:
        db = self.session_factory()
        defaults = dict(
            raw_post_id=kwargs.pop("raw_post_id"),
            platform="xhs",
            title="标题",
            content="正文",
            author_name="作者",
            sentiment="neutral",
            risk_level="low",
            heat_score=100.0,
            publish_time=NOW,
        )
        defaults.update(kwargs)
        db.add(ProcessedPost(**defaults))
        db.commit()
        db.close()

    def _get(self, **params):
        response = self.client.get("/api/sentiment/posts", params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_the_total_is_the_db_count_not_the_page_size(self):
        """「帖子总数」必须是库里的真实条数，不是"这一页装了多少条"。"""

        for i in range(5):
            self._add(raw_post_id=i + 1)

        data = self._get(page=1, page_size=2)

        self.assertEqual(len(data["items"]), 2, "一页就该只装 2 条")
        self.assertEqual(
            data["total"],
            5,
            "total 返回的是页大小而不是库存量——前端那张「帖子总数」卡片就是这么变成假数字的",
        )

    def test_every_item_carries_the_sentiment_and_risk_it_was_analyzed_with(self):
        """风险徽章要有东西可显示——raw_posts 里根本没有这两个字段，所以永远是「—」。"""

        self._add(raw_post_id=1, sentiment="negative", risk_level="high", heat_score=888.0)

        item = self._get()["items"][0]

        self.assertEqual(item["risk_level"], "high", "没有 risk_level，风险徽章只能显示「—」")
        self.assertEqual(item["sentiment"], "negative")
        self.assertEqual(item["heat_score"], 888.0)

    def test_the_risk_filter_narrows_the_result_and_the_total(self):
        """筛选在服务端做：命中的条目和总数都要跟着变（前端筛选器原本对帖子完全无效）。

        注：**当前 UI 不用这个参数**——帖子级 risk_level 的真实分布是
        low 385 / medium 12 / high 0（帖子级风险是规则算的，LLM 研判在事件级），
        这个徽章几乎不携带信息，已从页面移除。接口能力保留：帖子级风险模型
        若将来改进（例如接 LLM 分类），这个筛选立刻可用。
        """

        self._add(raw_post_id=1, risk_level="high", title="高风险帖")
        self._add(raw_post_id=2, risk_level="low", title="低风险帖")
        self._add(raw_post_id=3, risk_level="low", title="另一条低风险帖")

        data = self._get(risk="high")

        self.assertEqual([item["title"] for item in data["items"]], ["高风险帖"])
        self.assertEqual(data["total"], 1, "筛选后的 total 必须是筛选后的条数")

    def test_the_sentiment_filter_narrows_the_result_and_the_total(self):
        """情绪才是帖子身上有信息量的那根轴——真实分布
        positive 155 / neutral 128 / negative 84 / controversial 30。
        """

        self._add(raw_post_id=1, sentiment="negative", title="负面帖")
        self._add(raw_post_id=2, sentiment="positive", title="正面帖")
        self._add(raw_post_id=3, sentiment="neutral", title="中性帖")

        data = self._get(sentiment="negative")

        self.assertEqual([item["title"] for item in data["items"]], ["负面帖"])
        self.assertEqual(data["total"], 1)

    def test_controversial_is_a_first_class_sentiment(self):
        """`controversial`（争议）是核心的第四种情绪，不是拼写错误——库里有 30 条。

        标签函数漏掉它，这 30 条帖子的情绪徽章就会显示成「—」。
        """

        self._add(raw_post_id=1, sentiment="controversial", title="争议帖")
        self._add(raw_post_id=2, sentiment="neutral", title="中性帖")

        data = self._get(sentiment="controversial")

        self.assertEqual([item["title"] for item in data["items"]], ["争议帖"])
        self.assertEqual(data["items"][0]["sentiment"], "controversial")

    def test_the_keyword_searches_the_whole_table_not_just_the_loaded_page(self):
        """**这是最要命的一条**：搜索必须覆盖全库，而不是"已经加载进浏览器的那 100 条"。

        原实现在前端过滤已加载的 100 条——库里第 101 条之后的帖子，搜索永远找不到，
        而页面看起来像是搜了全库。这是一个**静默**的错误答案。
        """

        for i in range(120):
            self._add(raw_post_id=i + 1, title=f"普通帖{i}", publish_time=NOW - timedelta(days=i))
        # 藏在第 150 条位置（按时间排序会排到很后面）的食堂帖
        self._add(raw_post_id=999, title="中大食堂涨价了", publish_time=NOW - timedelta(days=300))

        data = self._get(keyword="食堂")

        self.assertEqual(data["total"], 1, "全库检索必须找到那条食堂帖")
        self.assertEqual(data["items"][0]["title"], "中大食堂涨价了")

    def test_the_keyword_also_matches_platform_and_author(self):
        """搜索框的 placeholder 承诺了「标题、平台、作者」——三样都要真的能搜到。"""

        self._add(raw_post_id=1, title="甲", author_name="张三", platform="zhihu")
        self._add(raw_post_id=2, title="乙", author_name="李四", platform="weibo")

        self.assertEqual(self._get(keyword="张三")["total"], 1)
        self.assertEqual(self._get(keyword="weibo")["total"], 1)

    def test_newest_first(self):
        self._add(raw_post_id=1, title="旧帖", publish_time=NOW - timedelta(days=10))
        self._add(raw_post_id=2, title="新帖", publish_time=NOW)

        titles = [item["title"] for item in self._get()["items"]]

        self.assertEqual(titles, ["新帖", "旧帖"])


if __name__ == "__main__":
    unittest.main()
