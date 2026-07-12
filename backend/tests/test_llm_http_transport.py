"""LLM 的 HTTP 传输层：默认必须直连，不继承系统代理。

背景（实测）：openai SDK 底层是 httpx，而 ``httpx.Client`` 默认 ``trust_env=True``。
在 Windows 上它不只读 HTTP_PROXY/HTTPS_PROXY 环境变量，还会读**注册表里的系统代理**
（Clash 一类工具会写这里）——所以清空环境变量对它无效。

实测同一次智谱调用：走系统代理 14.4s，直连 4.5s（慢 3 倍）。证据模块的抓取校验
已经因为同一个坑把真实可达的 sysu.edu.cn 判成 ConnectTimeout（见
``evidence/config.py::http_trust_env``），这里用同样的语义：默认直连，
显式设 ``LLM_HTTP_TRUST_ENV=true`` 才走代理。
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.services import llm_client
from backend.services.llm_client import LlmEndpoint


class _FakeCompletions:
    def create(self, **_kwargs):
        message = mock.Mock(content="ok")
        choice = mock.Mock(message=message)
        return mock.Mock(choices=[choice], usage=None)


class _FakeOpenAI:
    """记录构造参数，替代真实 SDK；不发任何网络请求。"""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self.chat = mock.Mock(completions=_FakeCompletions())


class LlmHttpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeOpenAI.last_kwargs = {}
        self.endpoint = LlmEndpoint(api_key="k", base_url="https://example.test/v1", model="m")

    def _send(self):
        with mock.patch.dict("sys.modules", {"openai": mock.Mock(OpenAI=_FakeOpenAI)}):
            llm_client._send_chat_completion([{"role": "user", "content": "hi"}], None, self.endpoint)
        return _FakeOpenAI.last_kwargs

    def test_an_http_client_is_injected_rather_than_left_to_the_sdk_default(self):
        kwargs = self._send()
        self.assertIn(
            "http_client",
            kwargs,
            "必须显式注入 httpx 客户端；用 SDK 默认值就会继承系统代理",
        )

    def test_the_injected_client_does_not_trust_the_environment_by_default(self):
        with mock.patch.object(llm_client, "LLM_HTTP_TRUST_ENV", False):
            client = self._send()["http_client"]
        self.assertFalse(
            client.trust_env,
            "默认必须 trust_env=False（直连）：否则 Windows 注册表里的系统代理会被静默继承",
        )

    def test_the_environment_can_be_trusted_when_explicitly_configured(self):
        with mock.patch.object(llm_client, "LLM_HTTP_TRUST_ENV", True):
            client = self._send()["http_client"]
        self.assertTrue(
            client.trust_env,
            "确实需要走代理才能上网的人，设 LLM_HTTP_TRUST_ENV=true 后必须生效",
        )


if __name__ == "__main__":
    unittest.main()
