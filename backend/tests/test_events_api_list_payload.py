"""事件**列表**接口要带上解析好的 concerns / risk_reasons。

## 为什么（2026-07-14，舆情关注页改成处置台）

处置台要把所有中高风险事件的 `concerns`（LLM 从成员帖里提炼的诉求）聚合起来，回答
「学生最集中的诉求是什么」。而列表接口此前只给 `concerns_json`——**一个生的 JSON 字符串**，
解析好的版本只在**详情**接口里。前端要聚合 8 个事件的诉求，就得打 8 次详情请求。

后端已经有 `_json_value` 了，解析责任本来就该在这一侧：一个接口不该把"自己存的是
JSON 字符串"这个实现细节漏给每一个调用方。

生串 `concerns_json` / `risk_reasons_json` 保留（老调用方还在用），新增解析好的字段。
"""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models import PublicEvent


class EventListPayloadTest(unittest.TestCase):
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
        db.add(PublicEvent(status="published", risk_score=1.0, heat_score=1.0, source_count=1, **kwargs))
        db.commit()
        db.close()

    def _items(self) -> list[dict]:
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["items"]

    def test_the_list_carries_parsed_concerns(self):
        """处置台要聚合诉求——不能让它为了拿到一个数组去逐个打详情接口。"""

        self._add(
            event_key="k1",
            title="中大康某论文调查",
            summary="s",
            risk_level="high",
            concerns_json=json.dumps(["学术诚信", "学校声誉风险"], ensure_ascii=False),
        )

        item = self._items()[0]

        self.assertEqual(item["concerns"], ["学术诚信", "学校声誉风险"])

    def test_the_list_carries_parsed_risk_reasons(self):
        self._add(
            event_key="k2",
            title="t",
            summary="s",
            risk_level="high",
            risk_reasons_json=json.dumps(["涉及实名举报", "校方已启动调查"], ensure_ascii=False),
        )

        item = self._items()[0]

        self.assertEqual(item["risk_reasons"], ["涉及实名举报", "校方已启动调查"])

    def test_missing_or_broken_json_degrades_to_an_empty_list(self):
        """老数据没有这些字段、或者存了坏 JSON —— 给空数组，绝不让整个列表接口挂掉。"""

        self._add(event_key="k3", title="t", summary="s", risk_level="low", concerns_json="{坏的")

        item = self._items()[0]

        self.assertEqual(item["concerns"], [])
        self.assertEqual(item["risk_reasons"], [])

    def test_the_raw_json_strings_are_still_there(self):
        """老调用方还在读生串，不能悄悄把它们摘掉。"""

        self._add(
            event_key="k4",
            title="t",
            summary="s",
            risk_level="high",
            concerns_json=json.dumps(["甲"], ensure_ascii=False),
        )

        item = self._items()[0]

        self.assertIn("concerns_json", item)
        self.assertIn("risk_reasons_json", item)


if __name__ == "__main__":
    unittest.main()
