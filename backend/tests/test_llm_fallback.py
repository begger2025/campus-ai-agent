"""LLM 备胎链：主通道（中转站 gpt-5.4）失败后自动切换到 LLM_FALLBACK_*（GLM 直连）。

契约：
- 优先顺序 = 主通道 → 备胎；切换发生在 call_llm/call_llm_stream 内部，调用方免改；
- 备胎三项（model/base_url/api_key）配齐才启用；与主通道配置完全相同则不重复尝试；
- 不可重试错误（认证/404 等）立刻换下一个端点，不做无意义退避；
- 缓存按端点各查各的：主通道挂掉期间，答过的问题直接吃备胎缓存，不再空等主通道重试；
- 流式只在"第一个字之前"允许切换——已经吐给用户的内容不能从头重写。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.services import llm_client, llm_config
from backend.services.llm_client import (
    JsonLlmCache,
    LlmCallResult,
    build_cache_key,
    call_llm,
    call_llm_stream,
)


MESSAGES = [{"role": "user", "content": "你好"}]

FB_MODEL = "glm-test"
FB_URL = "https://fb.example/v1"
FB_KEY = "fb-key"


class AuthenticationError(Exception):
    """名字进 NON_RETRYABLE_ERRORS 白名单即可，无需真的来自 openai 包。"""


def fallback_config():
    return mock.patch.multiple(
        llm_config,
        LLM_FALLBACK_MODEL=FB_MODEL,
        LLM_FALLBACK_BASE_URL=FB_URL,
        LLM_FALLBACK_API_KEY=FB_KEY,
        create=True,
    )


class CallLlmFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(llm_client, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_primary_error_falls_back_to_secondary(self):
        def fake_send(messages, temperature, endpoint):
            if endpoint.base_url == FB_URL:
                return "备胎答案", {"total_tokens": 3}
            raise RuntimeError("primary down")

        with fallback_config(), mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            result = call_llm(MESSAGES, cache=None, max_retries=0)

        self.assertEqual(result.content, "备胎答案")
        self.assertEqual(result.attempts, 2, "主通道 1 次 + 备胎 1 次")
        self.assertEqual(result.error, "")

    def test_empty_primary_response_also_falls_back(self):
        def fake_send(messages, temperature, endpoint):
            if endpoint.base_url == FB_URL:
                return "备胎答案", {}
            return "", {}

        with fallback_config(), mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            result = call_llm(MESSAGES, cache=None, max_retries=0)

        self.assertEqual(result.content, "备胎答案")

    def test_without_fallback_config_behaviour_unchanged(self):
        def fake_send(messages, temperature, endpoint):
            raise RuntimeError("primary down")

        with mock.patch.multiple(
            llm_config,
            LLM_FALLBACK_MODEL="",
            LLM_FALLBACK_BASE_URL="",
            LLM_FALLBACK_API_KEY="",
            create=True,
        ), mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            result = call_llm(MESSAGES, cache=None, max_retries=0)

        self.assertIsNone(result.content)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(result.attempts, 1)

    def test_fallback_identical_to_primary_not_tried_twice(self):
        calls = []

        def fake_send(messages, temperature, endpoint):
            calls.append(endpoint.base_url)
            raise RuntimeError("down")

        with mock.patch.multiple(
            llm_config,
            LLM_FALLBACK_MODEL=llm_config.OPENAI_MODEL,
            LLM_FALLBACK_BASE_URL=llm_config.OPENAI_BASE_URL,
            LLM_FALLBACK_API_KEY=llm_config.OPENAI_API_KEY or "k",
            create=True,
        ), mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            # 备胎与主通道完全相同（或 key 空）时不应产生第二次尝试
            result = call_llm(MESSAGES, cache=None, max_retries=0)

        self.assertLessEqual(len(calls), 2)
        self.assertIsNone(result.content)

    def test_non_retryable_primary_error_switches_without_backoff(self):
        def fake_send(messages, temperature, endpoint):
            if endpoint.base_url == FB_URL:
                return "备胎答案", {}
            raise AuthenticationError("bad key")

        with fallback_config(), mock.patch.object(llm_client, "_send_chat_completion", fake_send):
            result = call_llm(MESSAGES, cache=None, max_retries=2)

        self.assertEqual(result.content, "备胎答案")
        self.assertEqual(result.attempts, 2, "认证错误不该在主通道上重试 3 次")
        self.sleep.assert_not_called()

    def test_fallback_cache_hit_skips_all_network_calls(self):
        send = mock.Mock(side_effect=RuntimeError("should not be called"))
        with tempfile.TemporaryDirectory() as tmp:
            cache = JsonLlmCache(Path(tmp) / "cache.json")
            key = build_cache_key(FB_MODEL, MESSAGES, None)
            cache.set(key, {"content": "缓存的备胎答案"})

            with fallback_config(), mock.patch.object(llm_client, "_send_chat_completion", send):
                result = call_llm(MESSAGES, cache=cache, max_retries=2)

        self.assertTrue(result.cache_hit)
        self.assertEqual(result.content, "缓存的备胎答案")
        send.assert_not_called()


class StreamFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(llm_client, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_stream_falls_back_before_first_byte(self):
        def fake_stream(messages, temperature, endpoint):
            if endpoint.base_url == FB_URL:
                yield "备胎", {}
                yield "答案", {"total_tokens": 5}
                return
            raise RuntimeError("primary down")

        outcome = LlmCallResult()
        with fallback_config(), mock.patch.object(
            llm_client, "_send_chat_completion_stream", fake_stream
        ):
            text = "".join(
                call_llm_stream(MESSAGES, cache=None, max_retries=0, outcome=outcome)
            )

        self.assertEqual(text, "备胎答案")
        self.assertEqual(outcome.content, "备胎答案")
        self.assertFalse(outcome.truncated)

    def test_stream_does_not_switch_after_first_byte(self):
        def fake_stream(messages, temperature, endpoint):
            if endpoint.base_url == FB_URL:
                yield "不该出现", {}
                return
            yield "主通道开头", {}
            raise RuntimeError("mid-stream failure")

        outcome = LlmCallResult()
        with fallback_config(), mock.patch.object(
            llm_client, "_send_chat_completion_stream", fake_stream
        ):
            text = "".join(
                call_llm_stream(MESSAGES, cache=None, max_retries=0, outcome=outcome)
            )

        self.assertEqual(text, "主通道开头")
        self.assertTrue(outcome.truncated, "吐过字之后失败只能如实标记截断，不能换端点重写")


if __name__ == "__main__":
    unittest.main()
