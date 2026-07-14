"""数据管理页要能看见「剔除」这件事。

## 一个容易出错的接缝

数据管理页读的是 **raw_posts**（原始采集帖），而剔除标记在 **processed_posts** 上
（下游——舆情分析页 / 事件聚类 / agent 检索——查的都是 processed_posts）。
两张表的主键**不是同一个**。

所以列表接口必须把两者关联起来，交出：

    processed_post_id   剔除按钮要用它（不能拿 raw_post.id 去 PATCH）
    excluded            当前是不是已剔除（按钮显示「剔除」还是「恢复」）
    excluded_reason     剔的理由

没有 processed_post 的 raw_post（还没跑清洗流水线）：`processed_post_id=None`，
前端把剔除按钮禁掉——**不能假装能剔一个还不存在于下游的东西**。
"""

from __future__ import annotations

from datetime import datetime
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import ProcessedPost, RawPost
from backend.services.auth_service import require_admin


NOW = datetime(2026, 7, 14, 12, 0, 0)


class AdminRawPostsExclusionTest(unittest.TestCase):
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

        admin = User(id=1, username="admin", role="admin")
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_admin] = lambda: admin
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        db = self.session_factory()
        # ① 已处理 + 已剔除（台湾国立中山大学，同名不同校）
        raw1 = RawPost(
            platform="zhihu", external_id="z1", title="台湾国立中山大学有什么课程推荐?",
            content="课程推荐。", author="乙", url="https://x/1", publish_time=NOW,
        )
        # ② 已处理 + 未剔除（真实中大帖）
        raw2 = RawPost(
            platform="xhs", external_id="x1", title="中山大学东校区宿舍搬迁",
            content="搬迁通知。", author="甲", url="https://x/2", publish_time=NOW,
        )
        # ③ 还没跑清洗流水线（没有 processed_post）
        raw3 = RawPost(
            platform="weibo", external_id="w1", title="尚未处理的帖子",
            content="…", author="丙", url="https://x/3", publish_time=NOW,
        )
        db.add_all([raw1, raw2, raw3])
        db.commit()

        p1 = ProcessedPost(
            raw_post_id=raw1.id, platform="zhihu", title=raw1.title, content=raw1.content,
            excluded=True, excluded_reason="同名的台湾国立中山大学，与本校无关",
        )
        p2 = ProcessedPost(
            raw_post_id=raw2.id, platform="xhs", title=raw2.title, content=raw2.content,
        )
        db.add_all([p1, p2])
        db.commit()
        self.p1_id, self.p2_id = p1.id, p2.id
        self.raw3_title = raw3.title
        db.close()

    def _items(self, **params) -> list[dict]:
        response = self.client.get("/api/admin/raw-posts", params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["items"]

    def test_each_row_carries_its_processed_post_id_and_exclusion_state(self):
        """剔除按钮要 PATCH 的是 processed_post_id——拿 raw_post.id 去 PATCH 会剔错帖子。"""

        by_title = {item["title"]: item for item in self._items()}

        excluded = by_title["台湾国立中山大学有什么课程推荐?"]
        self.assertEqual(excluded["processed_post_id"], self.p1_id)
        self.assertTrue(excluded["excluded"])
        self.assertEqual(excluded["excluded_reason"], "同名的台湾国立中山大学，与本校无关")

        kept = by_title["中山大学东校区宿舍搬迁"]
        self.assertEqual(kept["processed_post_id"], self.p2_id)
        self.assertFalse(kept["excluded"])

    def test_an_unprocessed_post_has_no_processed_id(self):
        """还没跑清洗流水线的帖子：剔除按钮该禁掉——不能假装能剔一个下游还没有的东西。"""

        row = next(item for item in self._items() if item["title"] == self.raw3_title)

        self.assertIsNone(row["processed_post_id"])
        self.assertFalse(row["excluded"])

    def test_the_excluded_filter_narrows_to_the_removed_posts(self):
        """「已剔除」筛选：管理员要能复核自己剔了什么（也才谈得上恢复）。"""

        items = self._items(excluded="true")

        self.assertEqual([item["title"] for item in items], ["台湾国立中山大学有什么课程推荐?"])

    def test_the_active_filter_hides_the_removed_posts(self):
        titles = [item["title"] for item in self._items(excluded="false")]

        self.assertNotIn("台湾国立中山大学有什么课程推荐?", titles)
        self.assertIn("中山大学东校区宿舍搬迁", titles)
        self.assertIn(self.raw3_title, titles, "还没处理的帖子不算被剔除")

    def test_no_filter_shows_everything(self):
        self.assertEqual(len(self._items()), 3)


if __name__ == "__main__":
    unittest.main()
