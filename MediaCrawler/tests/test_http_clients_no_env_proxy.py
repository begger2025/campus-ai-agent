# -*- coding: utf-8 -*-
"""HTTP 客户端不许静默走系统代理（审计修复 2026-07-17）。

后端同款问题早已修过（backend web_evidence 的 trust_env=False）：httpx/requests
默认信任环境代理（HTTP_PROXY 环境变量乃至 Windows 注册表的系统代理/Clash），
清环境变量三行**并不总够**——SOP 坑清单里"微博/贴吧直接开跑走系统代理超时"
就是这个雷。代码层面根治：不信任环境代理，要代理必须显式传。
"""

from typing import Any, Dict

import pytest

from media_platform.tieba.client import BaiduTieBaClient
from tools.httpx_util import make_async_client


class TestMakeAsyncClient:
    @pytest.mark.asyncio
    async def test_defaults_to_not_trusting_env_proxy(self):
        async with make_async_client() as client:
            assert client.trust_env is False

    @pytest.mark.asyncio
    async def test_explicit_override_is_respected(self):
        # 真有企业代理调试需求时仍可显式开回来
        async with make_async_client(trust_env=True) as client:
            assert client.trust_env is True


class TestTiebaSyncRequest:
    def _capture_request(self, monkeypatch) -> Dict[str, Any]:
        captured: Dict[str, Any] = {}

        class FakeResponse:
            status_code = 200
            text = "ok"

        def fake_request(**kwargs):
            captured.update(kwargs)
            return FakeResponse()

        import media_platform.tieba.client as tieba_client_module

        monkeypatch.setattr(tieba_client_module.requests, "request", fake_request)
        return captured

    def test_no_proxy_means_env_proxies_disabled(self, monkeypatch):
        captured = self._capture_request(monkeypatch)
        client = BaiduTieBaClient()

        client._sync_request("GET", "https://tieba.baidu.com/x")

        # requests 语义：按 scheme 显式置 None 才会**禁用**环境代理；
        # proxies=None 反而是"请读环境变量"
        assert captured["proxies"] == {"http": None, "https": None}

    def test_explicit_proxy_still_wins(self, monkeypatch):
        captured = self._capture_request(monkeypatch)
        client = BaiduTieBaClient()

        client._sync_request("GET", "https://tieba.baidu.com/x", proxy="http://1.2.3.4:8080")

        assert captured["proxies"] == {
            "http": "http://1.2.3.4:8080",
            "https": "http://1.2.3.4:8080",
        }
