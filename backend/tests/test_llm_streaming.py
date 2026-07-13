"""流式 LLM 调用：把「干等 21.9 秒然后整篇蹦出来」变成「2.7 秒开始出字」。

实测（synai996 / gpt-5.4，一份完整舆情简报）：
    非流式：用户盯着转圈 21.9s，然后 1561 字一次性出现
    流式：  2.7s 收到第一个字，之后逐字流出，总时长不变
总耗时一个字没省，但**感知延迟差 8 倍**——这是聊天体验最大的一块。

流式引入了一个非流式没有的正确性问题，本文件的核心就是钉死它：

    **一旦已经向用户吐出了文字，就不能再重试。**

非流式调用失败了重试一次，用户什么都看不见。流式调用如果吐到一半失败再重试，
用户会眼睁睁看着答案写到一半、然后从头开始重写——这比慢更糟。
所以重试窗口只在**第一个字之前**。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest import mock

from backend.services import llm_client
from backend.services.llm_client import (
    JsonLlmCache,
    LlmCallResult,
    build_cache_key,
    call_llm,
    call_llm_stream,
    reset_llm_usage,
)


MESSAGES = [{"role": "user", "content": "宿舍搬迁的舆情怎么样"}]


def _stream_of(*deltas: str, usage: dict | None = None):
    """造一个假的流：产出若干 delta，最后带上 token 用量。"""

    def _send(_messages, _temperature, _endpoint=None):
        for delta in deltas:
            yield delta, {}
        yield "", (usage or {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13})

    return _send


class StreamBasicsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_llm_usage()

    def tearDown(self) -> None:
        reset_llm_usage()

    def test_deltas_reach_the_caller_in_order(self):
        send = _stream_of("宿舍", "搬迁", "争议")
        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=send):
            chunks = list(call_llm_stream(MESSAGES, cache=None))
        self.assertEqual(chunks, ["宿舍", "搬迁", "争议"])

    def test_the_outcome_holder_receives_the_full_text_and_token_usage(self):
        outcome = LlmCallResult()
        send = _stream_of("热", "点", usage={"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9})
        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=send):
            list(call_llm_stream(MESSAGES, cache=None, outcome=outcome))

        self.assertEqual(outcome.content, "热点", "调用方要拿完整正文去写会话记忆/送 critic")
        self.assertEqual(outcome.error, "")
        self.assertEqual(outcome.total_tokens, 9, "流式下 token 计费不能静默变 0——那是答辩材料")

    def test_usage_accounting_matches_the_non_streaming_path(self):
        send = _stream_of("a", "b")
        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=send):
            list(call_llm_stream(MESSAGES, cache=None))
        usage = llm_client.get_llm_usage()
        self.assertEqual(usage["calls"], 1)
        self.assertEqual(usage["total_tokens"], 13)


class StreamCacheTests(unittest.TestCase):
    """流式和非流式必须共用同一份缓存，否则消融实验的可复现性就断了。"""

    def setUp(self) -> None:
        reset_llm_usage()
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = JsonLlmCache(Path(self._tmp.name) / "cache.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()
        reset_llm_usage()

    def test_a_completed_stream_is_written_to_the_cache(self):
        send = _stream_of("宿舍", "搬迁")
        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=send):
            list(call_llm_stream(MESSAGES, temperature=0, cache=self.cache))

        key = build_cache_key(llm_client.OPENAI_MODEL, MESSAGES, 0)
        entry = self.cache.get(key)
        self.assertIsNotNone(entry, "流式跑完必须落缓存，否则同一个问题每次都要重新付费")
        self.assertEqual(entry["content"], "宿舍搬迁")

    def test_a_cached_answer_is_replayed_without_touching_the_api(self):
        key = build_cache_key(llm_client.OPENAI_MODEL, MESSAGES, 0)
        self.cache.set(key, {"content": "缓存里的旧答案"})

        def explode(*_args, **_kwargs):
            raise AssertionError("缓存命中了还去打 API，等于白花钱")

        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=explode):
            chunks = list(call_llm_stream(MESSAGES, temperature=0, cache=self.cache))

        self.assertEqual("".join(chunks), "缓存里的旧答案")
        self.assertEqual(llm_client.get_llm_usage()["cache_hits"], 1)

    def test_streaming_and_non_streaming_share_one_cache_key(self):
        """非流式脚本（消融实验）写的缓存，流式聊天必须能命中，反之亦然。"""

        def fake_send(_messages, _temperature, _endpoint=None):
            return "非流式写进去的答案", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

        with mock.patch.object(llm_client, "_send_chat_completion", side_effect=fake_send):
            call_llm(MESSAGES, temperature=0, cache=self.cache)

        def explode(*_args, **_kwargs):
            raise AssertionError("两条路径的缓存键不一致——同一个问题会被付两次钱")

        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=explode):
            chunks = list(call_llm_stream(MESSAGES, temperature=0, cache=self.cache))

        self.assertEqual("".join(chunks), "非流式写进去的答案")


class StreamRetryTests(unittest.TestCase):
    """重试窗口只在第一个字之前——这是流式引入的唯一新正确性要求。"""

    def setUp(self) -> None:
        reset_llm_usage()
        llm_client._sleep = lambda _seconds: None  # 别在测试里真睡

    def tearDown(self) -> None:
        import time as _time

        llm_client._sleep = _time.sleep
        reset_llm_usage()

    def test_a_failure_before_the_first_delta_is_retried(self):
        attempts = {"n": 0}

        def flaky(_messages, _temperature, _endpoint=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("第一次连接就超时了")
            yield "重试后成功", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=flaky):
            chunks = list(call_llm_stream(MESSAGES, cache=None))

        self.assertEqual("".join(chunks), "重试后成功")
        self.assertEqual(attempts["n"], 2, "还没吐出任何字就失败，应该照常重试")

    def test_a_failure_after_the_first_delta_is_terminal_and_never_restarts(self):
        """已经吐了字之后失败：不能重试——用户会看到答案写到一半从头重写。"""

        attempts = {"n": 0}

        def dies_midway(_messages, _temperature, _endpoint=None):
            attempts["n"] += 1
            yield "宿舍搬迁的舆情", {}
            raise ConnectionError("连接在中途断了")

        outcome = LlmCallResult()
        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=dies_midway):
            chunks = list(call_llm_stream(MESSAGES, cache=None, outcome=outcome))

        self.assertEqual(attempts["n"], 1, "已经向用户吐过字了，绝不能重试——那会让答案从头重写")
        self.assertEqual(
            "".join(chunks),
            "宿舍搬迁的舆情",
            "已经吐出去的部分要保留，不能重复也不能吞掉",
        )
        self.assertEqual(outcome.error, "ConnectionError", "调用方要知道这是个残缺的答案")
        self.assertTrue(outcome.truncated, "残缺必须可判别，前端才能提示用户")

    def test_a_partial_answer_is_not_cached(self):
        """半截答案绝不能进缓存——否则这个问题以后永远只能得到半截答案。"""

        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonLlmCache(Path(tmp) / "cache.json")

            def dies_midway(_messages, _temperature, _endpoint=None):
                yield "只写了一半", {}
                raise ConnectionError("断了")

            with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=dies_midway):
                list(call_llm_stream(MESSAGES, temperature=0, cache=cache))

            key = build_cache_key(llm_client.OPENAI_MODEL, MESSAGES, 0)
            self.assertIsNone(
                cache.get(key),
                "半截答案进了缓存：这个问题以后每次都会返回这半截，而且再也不会重新调用",
            )

    def test_an_empty_stream_is_treated_as_a_retryable_failure(self):
        """推理模型偶发只返回思考过程、一个字都不吐——和非流式路径同样视为可重试故障。"""

        attempts = {"n": 0}

        def empty_then_ok(_messages, _temperature, _endpoint=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return
                yield  # noqa: unreachable — 造一个空生成器
            yield "这次有内容了", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}

        with mock.patch.object(llm_client, "_send_chat_completion_stream", side_effect=empty_then_ok):
            chunks = list(call_llm_stream(MESSAGES, cache=None))

        self.assertEqual("".join(chunks), "这次有内容了")
        self.assertEqual(attempts["n"], 2)


if __name__ == "__main__":
    unittest.main()
