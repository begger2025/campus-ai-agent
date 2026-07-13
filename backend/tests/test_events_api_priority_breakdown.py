"""四轴优先级的**分解**：把「凭什么这个事件排第一」摆到台面上。

## 为什么要分解（2026-07-14）

事件的排序键是四根正交轴的乘积：

    priority_score = severity_weight(risk_level) × recency_weight(age) × lifecycle_weight(状态)
                   =        9 / 3 / 1           ×   0.5 ** (age/21)    ×   4 / 2 / 0.5 / 1

改造前 API 只返回**乘积**。管理员在工作台上看到「这条 3 个月前的事排第 1」，没有任何
办法追问"凭什么"——而这恰恰是本项目最核心的可解释性主张：**每根轴都能单独解释给人听**。

前端当然可以自己复制那两张权重表（9/3/1 和 4/2/0.5）算出来——但那就有了两份真相，
迟早漂移。**分解由后端给**，权重表在核心里只有一份。

## 降级契约

生命周期未研判（LLM 关掉 / 失败 / 老数据）时因子恒为 1.0，乘积逐位退化回改造前的
两轴版本 `severity × recency`。**AI 不可用时排序不变，而不是变成随机**——这条也钉死。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models import PublicEvent


NOW = datetime.now(UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


class PriorityBreakdownTest(unittest.TestCase):
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

    def _add(self, key: str, risk: str, *, age_days: float, lifecycle: str | None) -> None:
        payload: dict = {"event_time": _iso(age_days), "member_times": [_iso(age_days)]}
        if lifecycle:
            payload["lifecycle_judgement"] = lifecycle
            payload["lifecycle_reason"] = "测试理由"
        db = self.session_factory()
        db.add(
            PublicEvent(
                event_key=key,
                title=key,
                summary="摘要",
                status="published",
                risk_level=risk,
                risk_score=50.0,
                heat_score=100.0,
                source_count=2,
                date_range_json=json.dumps(payload, ensure_ascii=False),
            )
        )
        db.commit()
        db.close()

    def _events(self) -> list[dict]:
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["items"]

    def test_the_breakdown_multiplies_out_to_the_priority_score(self):
        """三个因子乘起来必须**正好**等于排序用的那个分数——否则展示的解释是假的。"""

        self._add("evt", "high", age_days=10, lifecycle="ongoing")

        event = self._events()[0]
        breakdown = event["priority_breakdown"]

        product = breakdown["severity"] * breakdown["recency"] * breakdown["lifecycle"]
        self.assertAlmostEqual(
            product,
            event["priority_score"],
            places=6,
            msg="分解出来的三个因子乘不出排序分——那这份「凭什么」是编的",
        )

    def test_the_severity_weight_comes_from_the_llm_risk_level(self):
        """严重性是 LLM 研判的 risk_level 的函数：high 9 / medium 3 / low 1。"""

        self._add("h", "high", age_days=1, lifecycle=None)
        self._add("m", "medium", age_days=1, lifecycle=None)
        self._add("l", "low", age_days=1, lifecycle=None)

        by_title = {e["title"]: e["priority_breakdown"] for e in self._events()}

        self.assertEqual(by_title["h"]["severity"], 9.0)
        self.assertEqual(by_title["m"]["severity"], 3.0)
        self.assertEqual(by_title["l"]["severity"], 1.0)

    def test_the_lifecycle_factor_reflects_the_judgement(self):
        """悬而未决的事抗衰减（×2），已了结的事被打折（×0.5）——这是第四根轴的全部意义。"""

        self._add("ongoing", "medium", age_days=30, lifecycle="ongoing")
        self._add("resolved", "medium", age_days=30, lifecycle="resolved")

        by_title = {e["title"]: e["priority_breakdown"] for e in self._events()}

        self.assertEqual(by_title["ongoing"]["lifecycle"], 2.0)
        self.assertEqual(by_title["resolved"]["lifecycle"], 0.5)

    def test_an_unjudged_lifecycle_degrades_to_a_factor_of_one(self):
        """LLM 没研判过（关掉 / 失败 / 老数据）→ 因子 1.0 → 逐位退化回两轴版本。

        **AI 不可用时排序不变，而不是变成随机。** 这是降级契约。
        """

        self._add("unjudged", "high", age_days=10, lifecycle=None)

        event = self._events()[0]
        breakdown = event["priority_breakdown"]

        self.assertEqual(breakdown["lifecycle"], 1.0, "未研判的生命周期不许变成一个因子")
        self.assertAlmostEqual(
            event["priority_score"],
            breakdown["severity"] * breakdown["recency"],
            places=6,
            msg="未研判时，四轴必须逐位退化回改造前的 severity × recency",
        )

    def test_the_recency_factor_is_the_decay_curve(self):
        """时效权重 = 0.5 ** (age / 半衰期)。一个半衰期之后正好剩一半。"""

        from backend.agent.public_opinion_core.recency import recency_config

        half_life = recency_config()["half_life_days"] or 21.0
        self._add("half", "low", age_days=half_life, lifecycle=None)

        breakdown = self._events()[0]["priority_breakdown"]

        self.assertAlmostEqual(breakdown["recency"], 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
