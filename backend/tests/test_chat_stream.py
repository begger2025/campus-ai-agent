"""流式聊天的事件契约。

为什么要流式（实测，synai996 / gpt-5.4）：
    简报意图 = 3 次串行 LLM 调用（路由 4.2s + 生成 19.4s + AI 审校 19.4s）≈ 43 秒。
    用户全程盯着一个**假进度条**（AgentChatView.vue 按 elapsed 秒数猜阶段文案）。
    改成流式后：2.7 秒开始出字，而且进度条说的是真话。

事件顺序就是体验本身，所以逐条钉死：

    meta   → 路由一出来就发（用户立刻知道"这是一份简报"，而不是干等）
    step   → ReAct 每走完一步就发（"正在检索宿舍…""正在对比食堂…"）
    delta  → 正文逐段流出
    done   → 事件列表 / 引用表 / 审校结论 / 是否降级

三条最容易做错、代价也最大的：
  1. **critic 必须在正文流完之后才跑**。它是第二次完整 LLM 调用（19 秒）。
     堵在正文前面 = 用户白等 19 秒；放在正文后面 = 用户读简报的时间就把它跑完了，感知为零。
  2. **会话记忆要记完整正文**，不是第一个 delta。记错了下一轮追问就会失忆。
  3. **降级文案要和非流式版逐字一致**。不能因为走了流式就看到不一样的错误提示。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.services import opinion_chat_service as chat_mod
from backend.services.intent_router import IntentRoute
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory


def _collect(stream) -> list[tuple[str, dict]]:
    return list(stream)


def _kinds(events: list[tuple[str, dict]]) -> list[str]:
    return [kind for kind, _payload in events]


def _text(events: list[tuple[str, dict]]) -> str:
    return "".join(p["text"] for k, p in events if k == "delta")


def _payload(events: list[tuple[str, dict]], kind: str) -> dict:
    for k, p in events:
        if k == kind:
            return p
    raise AssertionError(f"没有收到 {kind} 事件，实际收到：{_kinds(events)}")


class _StubService(OpinionChatService):
    """不碰数据库：直接给定 notes/events。"""

    def __init__(self, events=None, notes=None):
        self.db = None
        self._notes_cache = {}
        self._stub_events = events or []
        self._stub_notes = notes or []

    def _notes(self, keyword: str = ""):
        return self._stub_notes

    def _events(self, keyword: str = ""):
        return self._stub_events

    def _risk_sorted_events(self, keyword: str = ""):
        return self._stub_events


def _fake_stream(*deltas: str):
    def _stream(*, outcome=None, **_kwargs):
        for delta in deltas:
            yield delta
        if outcome is not None:
            outcome.content = "".join(deltas)

    return _stream


class ChatStreamOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_memory()

    def tearDown(self) -> None:
        reset_chat_memory()

    def test_meta_arrives_before_any_answer_text(self):
        service = _StubService()
        routed = IntentRoute(intent="hotspots", keyword="宿舍", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=_fake_stream("热点", "分析")
        ):
            events = _collect(service.chat_stream("最近热点", user_id="u1"))

        kinds = _kinds(events)
        self.assertEqual(kinds[0], "meta", f"meta 必须第一个到，用户才能立刻看到意图；实际：{kinds}")
        meta = _payload(events, "meta")
        self.assertEqual(meta["intent"], "hotspots")
        self.assertEqual(meta["keyword"], "宿舍")
        self.assertLess(
            kinds.index("meta"),
            kinds.index("delta"),
            "meta 必须早于第一个 delta",
        )

    def test_the_answer_text_arrives_as_deltas_and_done_comes_last(self):
        service = _StubService()
        routed = IntentRoute(intent="hotspots", keyword="", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=_fake_stream("校园", "热点", "分析")
        ):
            events = _collect(service.chat_stream("热点", user_id="u1"))

        self.assertEqual(_text(events), "校园热点分析")
        self.assertEqual(_kinds(events)[-1], "done", "done 必须收尾")

    def test_the_full_answer_lands_in_conversation_memory(self):
        """记忆里要存完整正文——存成第一个 delta 的话，下一轮追问就失忆了。"""

        service = _StubService()
        routed = IntentRoute(intent="hotspots", keyword="食堂", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=_fake_stream("食堂", "的", "热点")
        ):
            _collect(service.chat_stream("食堂热点", user_id="u1"))

        history = chat_mod._history_by_user["u1"]
        roles = [role for role, _text in history]
        answers = [text for role, text in history if role == "assistant"]
        self.assertIn("assistant", roles)
        self.assertEqual(answers[-1], "食堂的热点", "会话记忆存的必须是拼好的完整正文")
        self.assertEqual(chat_mod._last_keyword_by_user["u1"], "食堂")


class ReportStreamTests(unittest.TestCase):
    """简报意图：正文先流完，AI 审校随后——不能让 19 秒的审校堵在正文前面。"""

    def setUp(self) -> None:
        reset_chat_memory()

    def tearDown(self) -> None:
        reset_chat_memory()

    def test_the_critic_runs_after_the_report_text_not_before(self):
        service = _StubService()
        routed = IntentRoute(intent="report", keyword="宿舍", source="llm")
        call_order: list[str] = []

        def tracked_stream(*, outcome=None, **_kwargs):
            call_order.append("report")
            yield "简报正文"
            if outcome is not None:
                outcome.content = "简报正文"

        def tracked_critic(*_args, **_kwargs):
            call_order.append("critic")
            return chat_mod.ReviewResult(verdict="warn", issues=["缺少引用"])

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=tracked_stream
        ), mock.patch.object(chat_mod, "review_report", side_effect=tracked_critic):
            events = _collect(service.chat_stream("给我简报", user_id="u1"))

        self.assertEqual(
            call_order,
            ["report", "critic"],
            "审校跑在正文前面了：用户会为一次自己看不见的 LLM 调用白等 19 秒",
        )
        kinds = _kinds(events)
        self.assertLess(
            kinds.index("delta"),
            kinds.index("done"),
            "正文必须先于 done 送达",
        )
        done = _payload(events, "done")
        self.assertEqual(done["review"]["verdict"], "warn")
        self.assertEqual(done["review"]["issues"], ["缺少引用"])

    def test_a_warned_report_appends_the_review_notice_to_the_streamed_text(self):
        """审校提示要真的追加到正文末尾（非流式版就是这么做的，行为不能变）。"""

        service = _StubService()
        routed = IntentRoute(intent="report", keyword="", source="llm")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=_fake_stream("简报正文")
        ), mock.patch.object(
            chat_mod,
            "review_report",
            return_value=chat_mod.ReviewResult(verdict="warn", issues=["缺少引用"]),
        ):
            events = _collect(service.chat_stream("给我简报", user_id="u1"))

        self.assertIn("⚠️ 审校提示", _text(events), "审校提示必须作为增量流给用户，而不是悄悄丢掉")
        self.assertIn("缺少引用", _text(events))


class ComplexStreamTests(unittest.TestCase):
    """多步推理：每走完一步就推一次，而不是攒 40 秒一次性倒给用户。"""

    def setUp(self) -> None:
        reset_chat_memory()

    def tearDown(self) -> None:
        reset_chat_memory()

    def test_react_steps_stream_out_before_the_final_answer(self):
        service = _StubService()
        routed = IntentRoute(intent="complex_analysis", keyword="", source="llm")

        def fake_react(_message, *, tools, **_kwargs):
            from backend.services.react_loop import ReactResult, ReactStep

            step1 = ReactStep(thought="先查宿舍", action="hotspots", action_input={"keyword": "宿舍"})
            step2 = ReactStep(thought="再查食堂", action="hotspots", action_input={"keyword": "食堂"})
            yield step1
            yield step2
            yield ReactResult(answer="对比结论", steps=[step1, step2], stop_reason="answered")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "iter_react", side_effect=fake_react
        ):
            events = _collect(service.chat_stream("对比宿舍和食堂", user_id="u1"))

        kinds = _kinds(events)
        self.assertEqual(kinds.count("step"), 2, f"两步推理应该推两个 step 事件；实际：{kinds}")
        self.assertLess(
            kinds.index("step"),
            kinds.index("delta"),
            "step 必须在最终答案之前到达——这才叫实时进度",
        )
        steps = [p for k, p in events if k == "step"]
        self.assertEqual(steps[0]["action_input"]["keyword"], "宿舍")
        self.assertEqual(steps[1]["action_input"]["keyword"], "食堂")
        self.assertEqual(_text(events), "对比结论")
        self.assertEqual(_payload(events, "done")["stop_reason"], "answered")

    def test_a_degraded_react_run_still_answers_with_the_rule_digest(self):
        service = _StubService()
        routed = IntentRoute(intent="complex_analysis", keyword="", source="llm")

        def dead_react(_message, *, tools, **_kwargs):
            from backend.services.react_loop import ReactResult

            yield ReactResult(answer="", steps=[], stop_reason="llm_error")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "iter_react", side_effect=dead_react
        ):
            events = _collect(service.chat_stream("对比", user_id="u1"))

        self.assertTrue(_payload(events, "done")["degraded"], "LLM 挂了必须如实标记降级")
        self.assertTrue(_text(events).strip(), "降级也必须给用户一个规则版答案，不能是空白")


class SearchStreamTests(unittest.TestCase):
    """检索意图不需要生成，一个 LLM 都不该打。"""

    def setUp(self) -> None:
        reset_chat_memory()

    def tearDown(self) -> None:
        reset_chat_memory()

    def test_search_streams_its_canned_answer_without_calling_the_llm(self):
        service = _StubService()
        routed = IntentRoute(intent="search", keyword="宿舍", source="rules")

        def explode(*_args, **_kwargs):
            raise AssertionError("检索意图不该调用生成模型")

        with mock.patch.object(chat_mod, "route_intent", return_value=routed), mock.patch.object(
            chat_mod, "stream_llm_report", side_effect=explode
        ):
            events = _collect(service.chat_stream("宿舍", user_id="u1"))

        self.assertIn("相关校园公开内容", _text(events))
        self.assertIn("notes", _payload(events, "done"))


if __name__ == "__main__":
    unittest.main()
