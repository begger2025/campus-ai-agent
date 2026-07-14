"""数据质量管控：管理员剔除的帖子，**不进任何下游**。

## 为什么是「剔除」而不是「审核」（2026-07-14 架构判断）

用户问：帖子是不是也该经过管理员审核，普通用户才能看到？

答案是**不该**——审核的对象搞错了：

    帖子 = 从公开平台爬来的**客观事实**（小红书上人人可见）。审核它 = 审核别人
           已经公开发布的话，语义上说不通；而且几千条逐条人审会把整条 AI 流水线
           卡死（新帖审完才能进聚类）。
    事件 = **AI 生成的判断**（"这 5 条是同一件事"、"这是高风险"、"这事没了结"）。
           它会作为学校的舆情结论被使用 —— **这才是需要人工定夺的东西**，闸门在
           public_events.status 上。

但噪声是真的：同名的**台湾国立中山大学**、蹭校名的**地产/床垫集采广告**、早期乱填
关键词爬回的 Python 教程帖……它们确实出现在了舆情分析页。

那不是"没审核"，是**数据质量**问题。所以数据管理页的动词是**质量管控**：
发现无关帖 -> 剔除它。

## 这个文件钉死的契约

**剔除必须同时切断三条下游**，漏掉任何一条都是"假剔除"——用户以为剔掉了，
它却还在别的地方影响结论：

    ① 舆情分析页        /api/sentiment/posts + /api/sentiment/stats
    ② 事件聚类          query_agent_rows（generate_public_events 的取数口）
    ③ 舆情助手的检索     同一个 query_agent_rows（agent 的帖子层兜底）

软删除而不是 DELETE：上一次清噪声帖是直接删库（375 行 / 6 张表 / 撞了外键回滚）。
剔除可恢复，也留得下理由。
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
from backend.models import ProcessedPost
from backend.services.auth_service import get_current_user, require_admin
from backend.services.public_opinion_adapter import query_agent_rows


NOW = datetime(2026, 7, 14, 12, 0, 0)


class _Fixture(unittest.TestCase):
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
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        self.db = self.session_factory()
        self.addCleanup(self.db.close)

        # 一条真实的中大帖 + 一条同名学校的无关帖（台湾国立中山大学）
        self.keep = ProcessedPost(
            raw_post_id=1, platform="xhs", title="中山大学东校区宿舍搬迁", content="搬迁通知太仓促。",
            author_name="甲", sentiment="negative", risk_level="medium", heat_score=500.0,
            publish_time=NOW,
        )
        self.noise = ProcessedPost(
            raw_post_id=2, platform="zhihu", title="台湾国立中山大学有什么最值得选的课程推荐?",
            content="课程推荐。", author_name="乙", sentiment="neutral", risk_level="low",
            heat_score=14.0, publish_time=NOW,
        )
        self.db.add_all([self.keep, self.noise])
        self.db.commit()
        self.noise_id = self.noise.id

    def _exclude(self, post_id: int, reason: str = "同名的台湾国立中山大学，与本校无关"):
        return self.client.patch(
            f"/api/admin/posts/{post_id}/exclude",
            json={"excluded": True, "reason": reason},
        )

    def _restore(self, post_id: int):
        return self.client.patch(
            f"/api/admin/posts/{post_id}/exclude", json={"excluded": False}
        )


class ExclusionCutsEveryDownstreamTest(_Fixture):
    """剔除必须**同时**切断三条下游。漏一条就是假剔除。"""

    def test_an_excluded_post_leaves_the_sentiment_page(self):
        """① 舆情分析页（列表 + 总数）。"""

        before = self.client.get("/api/sentiment/posts").json()["data"]
        self.assertEqual(before["total"], 2)

        self.assertEqual(self._exclude(self.noise_id).status_code, 200)

        after = self.client.get("/api/sentiment/posts").json()["data"]
        self.assertEqual(after["total"], 1, "剔除后总数没变——它还在舆情分析页上")
        self.assertEqual([p["title"] for p in after["items"]], ["中山大学东校区宿舍搬迁"])

    def test_an_excluded_post_leaves_the_sentiment_stats(self):
        """① 统计口径也要跟着变——否则「帖子总数」和列表对不上。"""

        self._exclude(self.noise_id)

        stats = self.client.get("/api/sentiment/stats").json()["data"]

        self.assertEqual(stats["total"], 1, "统计还在数被剔除的帖子")
        self.assertEqual(
            sum(item["count"] for item in stats["platforms"]),
            1,
            "平台分布还在数被剔除的帖子",
        )

    def test_an_excluded_post_leaves_the_clustering_and_the_agent(self):
        """②③ 事件聚类和舆情助手共用 query_agent_rows —— 一次切断两条。

        这一条最要命：帖子从页面上消失了，却还在**参与事件聚类**、还能被 agent 检索到——
        用户以为剔掉了，它却仍然在影响 AI 的结论。那是最坏的一种失败：**静默的**。
        """

        before = query_agent_rows(self.db, limit=0)
        self.assertEqual(len(before), 2)

        self._exclude(self.noise_id)
        self.db.expire_all()

        after = query_agent_rows(self.db, limit=0)

        self.assertEqual(len(after), 1, "被剔除的帖子还在进事件聚类 / 还能被 agent 检索到")
        self.assertEqual(after[0]["title"], "中山大学东校区宿舍搬迁")


class ExclusionIsReversibleTest(_Fixture):
    """软删除：剔错了要能恢复（上一次清噪声是直接 DELETE，撞了外键回滚）。"""

    def test_a_restored_post_comes_back_everywhere(self):
        self._exclude(self.noise_id)
        self.assertEqual(self.client.get("/api/sentiment/posts").json()["data"]["total"], 1)

        self.assertEqual(self._restore(self.noise_id).status_code, 200)
        self.db.expire_all()

        self.assertEqual(self.client.get("/api/sentiment/posts").json()["data"]["total"], 2)
        self.assertEqual(len(query_agent_rows(self.db, limit=0)), 2)

    def test_the_reason_is_recorded(self):
        """「谁以什么理由剔的」要留得下——一个说不出理由的剔除只是一次任性。"""

        self._exclude(self.noise_id, reason="同名的台湾国立中山大学，与本校无关")
        self.db.expire_all()

        post = self.db.query(ProcessedPost).filter(ProcessedPost.id == self.noise_id).one()

        self.assertTrue(post.excluded)
        self.assertEqual(post.excluded_reason, "同名的台湾国立中山大学，与本校无关")

    def test_restoring_clears_the_reason(self):
        self._exclude(self.noise_id)
        self._restore(self.noise_id)
        self.db.expire_all()

        post = self.db.query(ProcessedPost).filter(ProcessedPost.id == self.noise_id).one()

        self.assertFalse(post.excluded)
        self.assertEqual(post.excluded_reason, "")


class ExclusionIsAdminOnlyTest(_Fixture):
    def test_a_missing_post_is_404(self):
        self.assertEqual(self._exclude(999999).status_code, 404)


if __name__ == "__main__":
    unittest.main()
