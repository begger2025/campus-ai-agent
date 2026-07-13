"""/agent/public/chat/stream 的 SSE 线格式。

SSE 的格式细节很容易写错，而且错了以后**前端只会安静地少收到几条消息**，不会报错：
  - 字段用换行分隔、事件用空行分隔 → data 里出现裸换行就会把一条消息劈成两条。
    舆情简报是 Markdown，**满篇都是换行**，所以这一条不是理论风险。
  - 必须 text/event-stream，否则浏览器不当流处理。
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import agent_public
from backend.services.auth_service import get_current_user
from backend.database import get_db


class _FakeUser:
    id = 7


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """把 SSE 原文解析回 (事件名, 载荷) 列表——按 SSE 规范：空行分隔事件。"""

    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name:
            events.append((name, json.loads(data)))
    return events


class ChatStreamRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(agent_public.router)
        app.dependency_overrides[get_current_user] = lambda: _FakeUser()
        app.dependency_overrides[get_db] = lambda: mock.MagicMock()
        self.client = TestClient(app)

    def test_a_markdown_answer_with_newlines_survives_the_wire(self):
        """简报是 Markdown，正文里全是换行——不转义就会把一条 SSE 消息劈成好几条。"""

        markdown = "### 一、热点概括\n近期宿舍搬迁引发讨论。\n\n### 二、主要观点\n- 通知仓促\n- 行李无处安置"

        def fake_stream(_message, user_id="", reset=False):
            yield ("meta", {"intent": "report", "keyword": "宿舍", "route_source": "llm"})
            yield ("delta", {"text": markdown})
            yield ("done", {"intent": "report", "keyword": "宿舍", "events": [], "answer": markdown})

        with mock.patch.object(agent_public.OpinionChatService, "chat_stream", side_effect=fake_stream), \
             mock.patch.object(agent_public, "record_chat_query"):
            response = self.client.post("/agent/public/chat/stream", json={"message": "给我简报"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

        events = _parse_sse(response.text)
        kinds = [name for name, _ in events]
        self.assertEqual(kinds, ["meta", "delta", "done"], f"事件被劈开或丢失了：{kinds}")

        delta = next(p for n, p in events if n == "delta")
        self.assertEqual(
            delta["text"],
            markdown,
            "Markdown 的换行没能原样穿过 SSE——前端拿到的会是残缺的简报",
        )

    def test_react_steps_are_forwarded_as_step_events(self):
        def fake_stream(_message, user_id="", reset=False):
            yield ("meta", {"intent": "complex_analysis", "keyword": "", "route_source": "llm"})
            yield ("step", {"thought": "先查宿舍", "action": "hotspots", "action_input": {"keyword": "宿舍"}})
            yield ("step", {"thought": "再查食堂", "action": "hotspots", "action_input": {"keyword": "食堂"}})
            yield ("delta", {"text": "对比结论"})
            yield ("done", {"intent": "complex_analysis", "events": [], "steps": []})

        with mock.patch.object(agent_public.OpinionChatService, "chat_stream", side_effect=fake_stream), \
             mock.patch.object(agent_public, "record_chat_query"):
            response = self.client.post("/agent/public/chat/stream", json={"message": "对比宿舍和食堂"})

        events = _parse_sse(response.text)
        steps = [p for n, p in events if n == "step"]
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["action_input"]["keyword"], "宿舍")

    def test_a_failure_midstream_is_delivered_as_an_error_event(self):
        """流已经开始了，HTTP 状态码早发出去了——错误只能作为事件送下去。"""

        def dying_stream(_message, user_id="", reset=False):
            yield ("meta", {"intent": "report", "keyword": "", "route_source": "llm"})
            raise RuntimeError("数据库连接断了")

        with mock.patch.object(agent_public.OpinionChatService, "chat_stream", side_effect=dying_stream), \
             mock.patch.object(agent_public, "write_system_log"), \
             mock.patch.object(agent_public, "record_chat_query"):
            response = self.client.post("/agent/public/chat/stream", json={"message": "给我简报"})

        self.assertEqual(response.status_code, 200, "流一旦开始就不能再改状态码")
        events = _parse_sse(response.text)
        kinds = [name for name, _ in events]
        self.assertIn("error", kinds, f"中途失败必须告诉前端，不能静默截断；实际：{kinds}")

    def test_the_chat_query_is_still_logged_for_keyword_planning(self):
        """智能选题靠这条提问日志采需求信号——改流式不能把它弄丢。"""

        def fake_stream(_message, user_id="", reset=False):
            yield ("meta", {"intent": "hotspots", "keyword": "食堂", "route_source": "llm"})
            yield ("delta", {"text": "答案"})
            yield ("done", {"intent": "hotspots", "keyword": "食堂", "events": [{"title": "e1"}]})

        with mock.patch.object(agent_public.OpinionChatService, "chat_stream", side_effect=fake_stream), \
             mock.patch.object(agent_public, "record_chat_query") as logged:
            self.client.post("/agent/public/chat/stream", json={"message": "食堂热点"})

        logged.assert_called_once()
        self.assertEqual(logged.call_args.kwargs["keyword"], "食堂")
        self.assertEqual(logged.call_args.kwargs["hit_count"], 1)


if __name__ == "__main__":
    unittest.main()
