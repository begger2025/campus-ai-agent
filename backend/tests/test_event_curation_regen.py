"""再生成保护：人工修正过的事件（curated），机器绝不覆盖。

三道闸，缺一道人工修正就会被下一轮 generate_public_events 悄悄冲掉：

  ① upsert 跳过 curated 行——改名/合并的结果不被同 key 的新聚类覆盖，
     链接也不被 replace_event_post_links 重写（跳过 = 不进 id 映射）；
  ② 自动归档跳过 curated 草稿——人碰过的草稿不算"幽灵草稿"；
  ③ curated 事件的成员帖退出聚类池——否则同一批帖下轮又聚出一个
     重复事件，人工合并等于白做。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services.public_opinion_adapter import (
    archive_stale_draft_events,
    exclude_curated_member_rows,
    upsert_public_events,
)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        self.post = ProcessedPost(
            note_id="xhs:1", raw_post_id=1, platform="xhs", title="搬迁看法", content="c",
            heat_score=10.0,
        )
        self.db.add(self.post)
        self.db.commit()

        self.curated = PublicEvent(
            event_key="sem:cur", title="人工改过的标题", status="draft", curated=True,
            risk_level="low", source_count=1, heat_score=10.0,
        )
        self.db.add(self.curated)
        self.db.commit()
        self.db.add(EventPostLink(event_id=self.curated.id, processed_post_id=self.post.id,
                                  raw_post_id=1, rank=1, role="manual"))
        self.db.commit()


class UpsertSkipsCuratedTests(_Fixture):
    def test_regenerated_payload_does_not_touch_a_curated_event(self) -> None:
        payload = {"event_key": "sem:cur", "title": "机器重新聚出来的标题", "status": "draft",
                   "risk_level": "high", "source_count": 5}

        id_map, _status_map = upsert_public_events(self.db, [payload])
        self.db.commit()

        fresh = self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:cur").first()
        self.assertEqual(fresh.title, "人工改过的标题", "机器不许覆盖人工改名")
        self.assertEqual(fresh.source_count, 1)
        self.assertNotIn("sem:cur", id_map,
                         "curated 事件不进 id 映射——replace_event_post_links 才不会重写它的链接")

    def test_uncurated_events_still_update_normally(self) -> None:
        plain = PublicEvent(event_key="sem:plain", title="旧标题", status="draft", risk_level="low")
        self.db.add(plain)
        self.db.commit()

        id_map, _ = upsert_public_events(
            self.db, [{"event_key": "sem:plain", "title": "新标题", "status": "draft"}]
        )
        self.db.commit()

        self.assertIn("sem:plain", id_map)
        self.assertEqual(
            self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:plain").first().title,
            "新标题",
        )


class StaleArchiveSkipsCuratedTests(_Fixture):
    def test_curated_draft_is_never_auto_archived(self) -> None:
        archived = archive_stale_draft_events(self.db, active_event_keys={"sem:other"})
        self.db.commit()

        fresh = self.db.query(PublicEvent).filter(PublicEvent.event_key == "sem:cur").first()
        self.assertEqual(fresh.status, "draft", "人碰过的草稿不算幽灵草稿，机器不许自动归档")
        self.assertEqual(archived, 0)


class ClusterPoolExclusionTests(_Fixture):
    def test_curated_members_leave_the_clustering_pool(self) -> None:
        rows = [
            {"processed_post_id": self.post.id, "title": "搬迁看法"},
            {"processed_post_id": 999, "title": "别的帖子"},
        ]

        kept, warning = exclude_curated_member_rows(self.db, rows)

        self.assertEqual([row["processed_post_id"] for row in kept], [999],
                         "curated 事件的成员帖必须退出聚类池——否则下轮又聚出重复事件")
        self.assertIn("1", warning, "排除了多少条要留痕")

    def test_no_curated_events_is_a_no_op(self) -> None:
        self.curated.curated = False
        self.db.commit()
        rows = [{"processed_post_id": self.post.id, "title": "搬迁看法"}]

        kept, warning = exclude_curated_member_rows(self.db, rows)

        self.assertEqual(len(kept), 1)
        self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
