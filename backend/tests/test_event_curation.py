"""人工事件修正：重命名 / 创建 / 删除 / 合并 / 帖子加入 / 帖子移出。

## 为什么（2026-07-16 用户提出）

AI 提议（聚类/研判）、人工裁决（status 闸门）之后，闭环缺最后一块：**人工修正**。
LLM 精修和合并裁决都会犯错，管理员必须能直接改——而不是只能驳回重来。

## 核心契约：人工编辑 = 锁（curated=True）

延续「机器绝不覆盖人的决定」：任何人工修正把事件上锁，再生成管线对 curated
行只读、其成员帖退出聚类池（见 test_event_curation_regen.py）。

其余契约：
- 删除是硬删，但仅限 draft/rejected/archived——published 是对外结论，必须先归档；
  删除前快照进审计（admin_operations）；
- 合并保留审计轨迹：source 归档注明去向，不硬删；
- 聚合重算是纯算术（条数/热度/时间范围）；LLM 的风险/生命周期研判保留原值；
- 空壳禁止：移出最后一条成员会被拒绝（没有证据的事件不是事件）。
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.auth_service import get_current_user, require_admin


NOW = datetime(2026, 7, 16, 12, 0, 0)


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

        # 三条帖子（p3 被剔除）+ 两个事件（草稿 A 含 p1，草稿 B 含 p2）
        self.posts = []
        for index, (title, heat, excluded) in enumerate(
            [("搬迁看法", 100.0, False), ("搬迁原因", 60.0, False), ("床垫广告", 999.0, True)],
            start=1,
        ):
            post = ProcessedPost(
                note_id=f"xhs:{index}",
                raw_post_id=index,
                platform="xhs",
                title=title,
                content=title,
                heat_score=heat,
                excluded=excluded,
                publish_time=NOW - timedelta(days=index),
            )
            self.db.add(post)
            self.posts.append(post)
        self.db.commit()

        self.event_a = self._event("sem:aaa", "东校区宿舍搬迁", [self.posts[0]])
        self.event_b = self._event("sem:bbb", "搬宿舍讨论", [self.posts[1]])

    def _event(self, key: str, title: str, members: list[ProcessedPost], status: str = "draft"):
        event = PublicEvent(
            event_key=key, title=title, summary=f"{title}。", status=status,
            risk_level="medium", risk_score=50.0,
            heat_score=sum(p.heat_score for p in members), source_count=len(members),
            date_range_json=json.dumps(
                {"event_time": NOW.isoformat(), "member_times": [NOW.isoformat()],
                 "lifecycle_judgement": "ongoing", "lifecycle_reason": "尚无结论"},
                ensure_ascii=False,
            ),
        )
        self.db.add(event)
        self.db.commit()
        for rank, post in enumerate(members, start=1):
            self.db.add(EventPostLink(event_id=event.id, processed_post_id=post.id,
                                      raw_post_id=post.raw_post_id, rank=rank, role="representative"))
        self.db.commit()
        return event

    def _fresh(self, event_id: int) -> PublicEvent:
        db = self.session_factory()
        try:
            return db.query(PublicEvent).filter(PublicEvent.id == event_id).first()
        finally:
            db.close()

    def _links(self, event_id: int) -> list[EventPostLink]:
        db = self.session_factory()
        try:
            return db.query(EventPostLink).filter(EventPostLink.event_id == event_id).all()
        finally:
            db.close()


class RenameTests(_Fixture):
    def test_rename_updates_title_and_locks(self) -> None:
        r = self.client.patch(f"/api/admin/events/{self.event_a.id}", json={"title": "东校区强制搬迁风波"})

        self.assertEqual(r.status_code, 200)
        fresh = self._fresh(self.event_a.id)
        self.assertEqual(fresh.title, "东校区强制搬迁风波")
        self.assertTrue(fresh.curated, "人工改名必须上锁——否则下一轮再生成把名字改回去")

    def test_blank_title_is_rejected(self) -> None:
        r = self.client.patch(f"/api/admin/events/{self.event_a.id}", json={"title": "   "})

        self.assertEqual(r.status_code, 400)


class CreateTests(_Fixture):
    def test_create_event_from_posts(self) -> None:
        ids = [self.posts[0].id, self.posts[1].id]
        r = self.client.post("/api/admin/events", json={"title": "手工归并的搬迁事件", "post_ids": ids})

        self.assertEqual(r.status_code, 200)
        event_id = r.json()["data"]["id"]
        fresh = self._fresh(event_id)
        self.assertTrue(fresh.event_key.startswith("man:"), "人工事件用 man: 前缀，不参与快照对齐")
        self.assertTrue(fresh.curated)
        self.assertEqual(fresh.status, "draft", "人工创建也要走审核闸门才能对外")
        self.assertEqual(fresh.source_count, 2)
        self.assertEqual(fresh.heat_score, 160.0, "聚合是纯算术：成员热度之和")
        self.assertEqual(len(self._links(event_id)), 2)

    def test_excluded_posts_cannot_seed_an_event(self) -> None:
        r = self.client.post(
            "/api/admin/events", json={"title": "垃圾事件", "post_ids": [self.posts[2].id]}
        )

        self.assertEqual(r.status_code, 400, "被剔除的帖子不能作为事件证据")


class DeleteTests(_Fixture):
    def test_draft_can_be_hard_deleted_with_links(self) -> None:
        r = self.client.delete(f"/api/admin/events/{self.event_a.id}")

        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._fresh(self.event_a.id))
        self.assertEqual(self._links(self.event_a.id), [], "链接必须一起删，不留孤儿行")

    def test_published_cannot_be_deleted_directly(self) -> None:
        event = self._event("sem:pub", "已发布事件", [self.posts[0]], status="published")

        r = self.client.delete(f"/api/admin/events/{event.id}")

        self.assertEqual(r.status_code, 409, "对外结论不许静默蒸发——必须先归档")
        self.assertIsNotNone(self._fresh(event.id))


class MergeTests(_Fixture):
    def test_merge_moves_links_and_archives_source(self) -> None:
        r = self.client.post(
            f"/api/admin/events/{self.event_a.id}/merge", json={"source_id": self.event_b.id}
        )

        self.assertEqual(r.status_code, 200)
        target = self._fresh(self.event_a.id)
        source = self._fresh(self.event_b.id)
        self.assertEqual(target.source_count, 2, "成员并集")
        self.assertEqual(target.heat_score, 160.0)
        self.assertTrue(target.curated)
        self.assertEqual(source.status, "archived", "source 归档留轨迹，不硬删")
        self.assertIn(str(self.event_a.id), source.review_comment, "归档意见要注明并入了谁")
        self.assertEqual(len(self._links(self.event_b.id)), 0)

    def test_merge_with_itself_is_rejected(self) -> None:
        r = self.client.post(
            f"/api/admin/events/{self.event_a.id}/merge", json={"source_id": self.event_a.id}
        )

        self.assertEqual(r.status_code, 400)


class MembershipTests(_Fixture):
    def test_add_post_recomputes_aggregates(self) -> None:
        r = self.client.post(
            f"/api/admin/events/{self.event_a.id}/posts",
            json={"processed_post_id": self.posts[1].id},
        )

        self.assertEqual(r.status_code, 200)
        fresh = self._fresh(self.event_a.id)
        self.assertEqual(fresh.source_count, 2)
        self.assertEqual(fresh.heat_score, 160.0)
        self.assertTrue(fresh.curated)
        roles = {link.role for link in self._links(self.event_a.id)}
        self.assertIn("manual", roles, "人工加入的链接标 manual——审计和展示都要能区分")

    def test_adding_an_excluded_post_is_rejected(self) -> None:
        r = self.client.post(
            f"/api/admin/events/{self.event_a.id}/posts",
            json={"processed_post_id": self.posts[2].id},
        )

        self.assertEqual(r.status_code, 400)

    def test_adding_a_duplicate_is_rejected(self) -> None:
        r = self.client.post(
            f"/api/admin/events/{self.event_a.id}/posts",
            json={"processed_post_id": self.posts[0].id},
        )

        self.assertEqual(r.status_code, 400, "帖子已在事件里")

    def test_remove_post_updates_aggregates(self) -> None:
        self.client.post(
            f"/api/admin/events/{self.event_a.id}/posts",
            json={"processed_post_id": self.posts[1].id},
        )

        r = self.client.delete(f"/api/admin/events/{self.event_a.id}/posts/{self.posts[0].id}")

        self.assertEqual(r.status_code, 200)
        fresh = self._fresh(self.event_a.id)
        self.assertEqual(fresh.source_count, 1)
        self.assertEqual(fresh.heat_score, 60.0)

    def test_removing_the_last_member_is_rejected(self) -> None:
        r = self.client.delete(f"/api/admin/events/{self.event_a.id}/posts/{self.posts[0].id}")

        self.assertEqual(r.status_code, 400, "没有证据的事件不是事件——不留空壳")

    def test_event_time_is_recomputed_from_members(self) -> None:
        self.client.post(
            f"/api/admin/events/{self.event_a.id}/posts",
            json={"processed_post_id": self.posts[1].id},
        )

        fresh = self._fresh(self.event_a.id)
        data = json.loads(fresh.date_range_json)
        self.assertEqual(len(data["member_times"]), 2, "member_times 从成员帖发布时间现算")
        self.assertEqual(
            data["lifecycle_judgement"], "ongoing",
            "LLM 的生命周期研判必须保留——聚合重算只动算术字段",
        )


if __name__ == "__main__":
    unittest.main()
