"""search 兜底不能是黑洞：事件层命中时必须升级为真正的回答。

## 线上实况（2026-07-13 审核，13 样例实测）

13 个样例有 **6 个**被 LLM 路由判成 `search`——「X怎么样了」「X的事」这类问法不落在
任何一个单步意图的定义里。而 search 兜底从不调用事件层，于是：

    「刘一阳的事怎么样了」 → 「已找到 5 条相关校园公开内容。」
        （库里 EVT-89「刘一阳去世」是 published + high 风险，代表帖全含"刘一阳"）

    「东校宿舍搬迁怎么样了」 → 「已找到 0 条相关校园公开内容。」
        （这正是三层检索本来要修的那个问题——被意图路由这一环整条绕过了）

**路由没认出意图 ≠ 库里没有这件事。** 修法：search 兜底先查事件层（字面→语义→裁决
的完整三层），命中就按观点问答的话术生成回答；只有事件层也一无所获，才退回帖子清单
（那条路保持零 LLM 调用——成本语义不变）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import EventPostLink, ProcessedPost, PublicEvent
from backend.services import event_read_model
from backend.services import opinion_chat_service as chat_mod
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _fake_stream(*deltas: str):
    def _stream(*, outcome=None, **_kwargs):
        for delta in deltas:
            yield delta
        if outcome is not None:
            outcome.content = "".join(deltas)

    return _stream


class _Fixture(unittest.TestCase):
    """一个 published 的人物事件 + 两条没有对应事件的食堂帖。"""

    def setUp(self) -> None:
        reset_chat_memory()
        self.addCleanup(reset_chat_memory)
        # 本文件只测"字面命中→升级"和"未命中→帖子清单"两条路，语义层（要加载
        # embedding 模型，冷启动 26 秒）与被测行为无关，关掉保持测试速度。
        patcher = mock.patch.object(event_read_model, "EVENT_SEMANTIC_MATCH_ENABLED", False)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[ProcessedPost.__table__, PublicEvent.__table__, EventPostLink.__table__],
        )
        self.db = sessionmaker(bind=self.engine)()

        # published 事件：标题直接含「刘一阳」，字面层必命中
        self.db.add(
            PublicEvent(
                event_key="sem:liu00001",
                title="刘一阳去世",
                summary="中大体育部副教授刘一阳去世相关讨论。",
                status="published",
                risk_level="high",
                risk_score=80.0,
                heat_score=5000.0,
                source_count=5,
                sentiment="negative",
                date_range_json=json.dumps({"event_time": _iso(10), "member_times": [_iso(10), _iso(11)]}),
            )
        )
        # 食堂帖：真实内容，但没有对应的 published 事件
        for i in range(2):
            self.db.add(
                ProcessedPost(
                    note_id=f"xhs:canteen{i}",
                    raw_post_id=100 + i,
                    platform="xhs",
                    title=f"中大食堂新品试吃 第{i}期",
                    content="食堂窗口排队情况。",
                    source_keyword="中山大学食堂",
                    heat_score=1000 + i,
                    heat_rank=60.0,
                    sentiment="neutral",
                    risk_level="low",
                    publish_time=NOW - timedelta(days=3),
                )
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()


TEMPLATE_PREFIX = "已找到"


class SearchUpgradeTests(_Fixture):
    def test_a_search_routed_question_still_reaches_the_published_event(self):
        """「刘一阳的事怎么样了」被路由成 search——但事件层命中了，就必须真正回答。"""

        service = OpinionChatService(self.db)
        routed = IntentRoute(intent="search", keyword="刘一阳", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "generate_llm_report", return_value="刘一阳去世事件的观点问答正文。"
        ) as llm:
            response = service.chat("刘一阳的事怎么样了", user_id="u1")

        titles = [event["title"] for event in response["events"]]
        self.assertIn(
            "刘一阳去世",
            titles,
            "published 的 high 风险事件被 search 兜底整条绕过了——三层检索在这条路径上不可达",
        )
        self.assertFalse(
            response["answer"].startswith(TEMPLATE_PREFIX),
            f"事件层命中时不能只回一句模板，实际：{response['answer']!r}",
        )
        llm.assert_called_once()
        # 意图如实保留 search：升级的是"答什么"，不是"路由判了什么"
        self.assertEqual(response["intent"], "search")

    def test_search_without_any_event_keeps_the_note_list_behavior(self):
        """事件层一无所获时保持老行为：帖子清单 + 模板，一个 LLM 都不打（成本语义不变）。"""

        service = OpinionChatService(self.db)
        routed = IntentRoute(intent="search", keyword="食堂", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "generate_llm_report"
        ) as llm:
            response = service.chat("食堂", user_id="u1")

        llm.assert_not_called()
        self.assertTrue(response["answer"].startswith(TEMPLATE_PREFIX))
        self.assertEqual(len(response["notes"]), 2, "帖子清单要照旧带回")

    def test_streaming_search_upgrades_the_same_way(self):
        """流式版必须和阻塞版同一语义——两套实现漂移 = 同一个问题两种答案。"""

        service = OpinionChatService(self.db)
        routed = IntentRoute(intent="search", keyword="刘一阳", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=_fake_stream("刘一阳", "事件解读")
        ):
            events = list(service.chat_stream("刘一阳的事怎么样了", user_id="u2"))

        kinds = [kind for kind, _payload in events]
        text = "".join(p["text"] for k, p in events if k == "delta")
        done = dict(events)["done"] if "done" in kinds else {}

        self.assertEqual(text, "刘一阳事件解读", "正文必须来自 LLM 生成，不是那句模板")
        titles = [event["title"] for event in done.get("events", [])]
        self.assertIn("刘一阳去世", titles, "done 里要带上命中的事件（前端要渲染风险标签）")


if __name__ == "__main__":
    unittest.main()
