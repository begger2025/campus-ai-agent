"""/api/events 的 SQL 查询数必须是**常数**——不许随 link 数增长。

## 缺陷（2026-07-16 用户反馈：首页几张卡"要等好一会才弹出来"）

实测 `/api/events?status=published&page_size=100` 热状态耗时 ~4 秒。接口主体
是三次批量查询，没问题；但 `_event_item` 组装来源平台时逐条访问
`link.raw_post`——SQLAlchemy 懒加载关系，**每条 link 单独发一条 SELECT**。
线上 32 个已发布事件挂着 117 条 link，数据库是远程共享 RDS（单次往返
~30ms）：117 × 30ms ≈ 4 秒，与实测吻合。而这 117 次往返每次搬回一整行
帖子，实际只用了 platform 一个字段。

修法：link 查询上加 selectinload 预加载，懒加载合并成两条批量 IN 查询。
本测试用查询计数器钉住"常数"这个性质——将来有人改回懒加载，这里会红。
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import EventPostLink, PublicEvent, RawPost
from backend.routers.api import get_event_detail, list_events

LINK_COUNT = 12  # 远大于允许的查询数上限，懒加载一旦回归立刻越线


class EventsApiQueryCountTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

        db = self.session_factory()
        event = PublicEvent(
            event_key="sem:k", title="事件", summary="s", status="published",
            risk_level="high", risk_score=1.0, heat_score=1.0,
        )
        db.add(event)
        db.flush()
        self.event_id = event.id
        for i in range(LINK_COUNT):
            raw = RawPost(platform="xhs", external_id=f"n{i}", title=f"帖{i}", content="c")
            db.add(raw)
            db.flush()
            db.add(EventPostLink(event_id=event.id, raw_post_id=raw.id, rank=i))
        db.commit()
        db.close()

    def _count_selects(self, fn) -> int:
        counted = []

        def hook(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                counted.append(statement)

        sa_event.listen(self.engine, "before_cursor_execute", hook)
        # 每次调用用全新 Session：身份映射是空的，和真实请求一致——
        # 复用建数据的会话会让懒加载命中缓存，测试就测不到往返了
        db = self.session_factory()
        try:
            fn(db)
        finally:
            db.close()
            sa_event.remove(self.engine, "before_cursor_execute", hook)
        return len(counted)

    def test_list_events_query_count_is_constant(self) -> None:
        count = self._count_selects(
            lambda db: list_events(db=db, status="published", page=1, page_size=100)
        )

        self.assertLessEqual(
            count, 6,
            f"list_events 发了 {count} 条 SELECT（{LINK_COUNT} 条 link）——"
            "查询数跟着 link 数走，说明懒加载 N+1 回来了",
        )

    def test_event_detail_query_count_is_constant(self) -> None:
        count = self._count_selects(lambda db: get_event_detail(self.event_id, db=db))

        self.assertLessEqual(
            count, 6,
            f"get_event_detail 发了 {count} 条 SELECT（{LINK_COUNT} 条 link）",
        )


if __name__ == "__main__":
    unittest.main()
