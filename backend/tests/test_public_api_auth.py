"""公开 API 的闸门：原始帖子要登录，已发布事件可公开。

## 两层数据，两种门（2026-07-14 审核）

用户问："普通用户为什么能看到所有的帖子，不是需要管理员审核完才能放出来吗"

**事件**确实有人工闸门——后端强制 `status == 'published'`，库里 105 个事件只有 10 个
可见（62 archived + 33 draft 一个都出不来）。**帖子没有任何闸门**，395 条全部可见，
两条蹭校名的广告/同名不同校帖子就是这么直接漏到用户眼前的。

但**帖子和事件需要的不是同一种门**：

  - 事件是 **AI 的结论**（LLM 研判的风险等级、生命周期）——AI 会错，所以必须人审。
    审过之后它就是**对外公开的舆情结论**，任何人可以看（事件列表/详情是公开页）。
  - 帖子是 **公开网络内容的搬运**（微博/知乎/小红书上本来就人人可见）——不需要"审核
    才能公开"，但它是平台的**内部原始数据**，不该让未登录的人随手 curl 走全库。

所以：**帖子接口要登录，事件接口保持公开。**

## 这条测试挡的是什么

改造前 `/api/posts`、`/api/sentiment/posts` **完全没有认证依赖**——前端 router 里标的
`roles: ['user','admin']` 只是前端的门，后端根本不设防，不登录直接 curl 就能拿到全库。
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app


class PublicApiAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        # 不 override get_current_user：真实的依赖会因为没有 Bearer token 而 401
        self.client = TestClient(app)

    def test_raw_posts_require_a_login(self):
        response = self.client.get("/api/posts")

        self.assertEqual(
            response.status_code,
            401,
            "未登录就能拿到全库原始帖子——前端的角色门是纸糊的，后端必须自己设防",
        )

    def test_analyzed_posts_require_a_login(self):
        response = self.client.get("/api/sentiment/posts")

        self.assertEqual(response.status_code, 401)

    def test_post_stats_require_a_login(self):
        response = self.client.get("/api/sentiment/stats")

        self.assertEqual(response.status_code, 401)

    def test_published_events_stay_public(self):
        """已发布事件是**人工审核过的对外结论**——它就该是公开的（事件列表/详情是公开页）。

        闸门在别处：后端只返回 status='published' 的行（draft/archived 一个都出不来）。
        """

        response = self.client.get("/api/events")

        self.assertEqual(
            response.status_code,
            200,
            "已发布事件是审核过的公开结论，不该被登录门挡住——它的闸门是 status='published'",
        )

    def test_the_health_check_stays_public(self):
        self.assertEqual(self.client.get("/api/ping").status_code, 200)


if __name__ == "__main__":
    unittest.main()
