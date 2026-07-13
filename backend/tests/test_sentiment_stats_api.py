"""舆情分析页的统计聚合：帖子层的洞察，取代那张重复的事件列表。

## 页面职责（2026-07-14 重新划分）

五个公开页原本每一页都在展示"帖子 + 事件"——事件列表出现了 4 次，统计卡出现了 3 次。
重新分工后，每页 = 唯一的（数据层 × 动词）：

    首页       概览层 × 看        全局数字 + 趋势 + 最新动态
    舆情分析   **帖子层 × 统计**   情绪分布 / 平台分布 / 发帖趋势   ← 本文件服务的页
    事件列表   事件层 × 检索      多维筛选 / 排序 / 分页
    舆情工作台 单事件 × 研判      AI 研判的全部"凭什么"
    舆情关注   中高风险 × 处置    影响评估
    舆情助手   全部 × 对话        ReAct 多步推理

舆情分析页此前一半的版面是事件列表——那是事件层的东西，属于另外三个页。它自己该做的
是**帖子层的统计**：395 条帖子在说什么情绪、来自哪些平台、什么时候发的。

## 聚合必须在服务端做

前端只能统计"已经加载进来的那一页"（8 条）。要算全库 395 条的分布，只能服务端 GROUP BY。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ProcessedPost
from backend.services.auth_service import get_current_user


NOW = datetime(2026, 7, 14, 12, 0, 0)


class SentimentStatsApiTest(unittest.TestCase):
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
        app.dependency_overrides[get_current_user] = lambda: User(id=1, username="u", role="user")
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

    def _stats(self):
        response = self.client.get("/api/sentiment/stats")
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_the_sentiment_breakdown_covers_all_four_values(self):
        """四种情绪，一种都不能漏——`controversial`（争议）是核心的第四种取值。"""

        self._add(raw_post_id=1, sentiment="positive")
        self._add(raw_post_id=2, sentiment="positive")
        self._add(raw_post_id=3, sentiment="negative")
        self._add(raw_post_id=4, sentiment="controversial")

        data = self._stats()

        self.assertEqual(data["total"], 4)
        self.assertEqual(data["sentiment"]["positive"], 2)
        self.assertEqual(data["sentiment"]["negative"], 1)
        self.assertEqual(data["sentiment"]["controversial"], 1)
        self.assertEqual(data["sentiment"]["neutral"], 0, "一条都没有的档位也要出现，否则图会缺一块")

    def test_the_platform_breakdown_is_sorted_by_volume(self):
        for i in range(3):
            self._add(raw_post_id=i + 1, platform="xhs")
        self._add(raw_post_id=10, platform="weibo")
        self._add(raw_post_id=11, platform="weibo")
        self._add(raw_post_id=20, platform="zhihu")

        platforms = self._stats()["platforms"]

        self.assertEqual([p["platform"] for p in platforms], ["xhs", "weibo", "zhihu"])
        self.assertEqual([p["count"] for p in platforms], [3, 2, 1])

    def test_the_daily_trend_covers_the_requested_window(self):
        """发帖量趋势：按天聚合。空白的那天要补 0，否则折线图会把两周连成一条直线。"""

        self._add(raw_post_id=1, publish_time=NOW)
        self._add(raw_post_id=2, publish_time=NOW)
        self._add(raw_post_id=3, publish_time=NOW - timedelta(days=2))

        trend = self._stats()["daily_trend"]

        self.assertGreaterEqual(len(trend), 3, "窗口内每一天都要有一个点（没帖子的那天补 0）")
        by_date = {point["date"]: point["count"] for point in trend}
        self.assertEqual(by_date[NOW.strftime("%Y-%m-%d")], 2)
        self.assertEqual(by_date[(NOW - timedelta(days=1)).strftime("%Y-%m-%d")], 0, "空白天必须补 0")
        self.assertEqual(by_date[(NOW - timedelta(days=2)).strftime("%Y-%m-%d")], 1)

    def test_the_hottest_posts_come_back_ranked(self):
        self._add(raw_post_id=1, title="冷帖", heat_score=10.0)
        self._add(raw_post_id=2, title="爆帖", heat_score=9999.0)
        self._add(raw_post_id=3, title="温帖", heat_score=500.0)

        top = self._stats()["top_posts"]

        self.assertEqual([p["title"] for p in top][:3], ["爆帖", "温帖", "冷帖"])
        self.assertEqual(top[0]["heat_score"], 9999.0)

    def test_an_empty_library_does_not_explode(self):
        data = self._stats()

        self.assertEqual(data["total"], 0)
        self.assertEqual(sum(data["sentiment"].values()), 0)
        self.assertEqual(data["platforms"], [])
        self.assertEqual(data["top_posts"], [])


if __name__ == "__main__":
    unittest.main()
