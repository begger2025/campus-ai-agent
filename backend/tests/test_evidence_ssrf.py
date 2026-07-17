"""审计第 2 批：证据核验 SSRF 防护。

核验端点会对 provider 返回的任意 URL 发起服务端 GET（out_of_scope 条目也可核验，
无前置门）。原实现只校验 scheme/netloc，不拦内网——管理员点一次「核验」就能让后端
探测 127.0.0.1 / 10.x / 169.254.169.254（云元数据）等内网地址。

修复：抓取前解析主机，命中私网/环回/链路本地/保留地址即拒绝，绝不发起请求；
重定向逐跳复检（provider 的 URL 已过 scope 门要求 sysu 域名，但 302 可跳内网）。
"""

from __future__ import annotations

import unittest

from backend.services.evidence.verification import (
    UrlFetchVerifier,
    private_network_reason,
)


def _resolver_to(ip: str):
    # 仿 socket.getaddrinfo 的返回结构：[(family, type, proto, canonname, sockaddr)]
    return lambda host, port: [(2, 1, 6, "", (ip, 0))]


class PrivateNetworkReasonTests(unittest.TestCase):
    def test_loopback_link_local_private_reserved_are_blocked(self) -> None:
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                   "169.254.169.254", "::1", "0.0.0.0", "fd00::1"):
            reason = private_network_reason(f"http://host/x", resolver=_resolver_to(ip))
            self.assertIsNotNone(reason, f"{ip} 必须被拦")

    def test_public_ip_is_allowed(self) -> None:
        reason = private_network_reason(
            "https://www.sysu.edu.cn/notice", resolver=_resolver_to("202.116.64.10")
        )
        self.assertIsNone(reason)

    def test_localhost_hostname_blocked_without_resolving(self) -> None:
        def exploding(host, port):
            raise AssertionError("localhost 应在解析前就被拦")

        self.assertIsNotNone(private_network_reason("http://localhost:8000/", resolver=exploding))

    def test_literal_private_ip_host_blocked(self) -> None:
        # 直接写 IP 字面量也要拦（不依赖 DNS）
        self.assertIsNotNone(private_network_reason("http://169.254.169.254/latest/meta-data/"))

    def test_missing_host_is_blocked(self) -> None:
        self.assertIsNotNone(private_network_reason("not-a-url"))


class _RecordingClient:
    def __init__(self):
        self.calls: list = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        raise AssertionError("被拦的内网 URL 不许发起请求")


class CheckBlocksBeforeFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_url_rejected_without_any_request(self) -> None:
        client = _RecordingClient()
        verifier = UrlFetchVerifier(client=client, resolver=_resolver_to("127.0.0.1"))

        result = await verifier.check("http://internal.example/x", "引用文本")

        self.assertEqual(result.status, "needs_review")
        self.assertEqual(client.calls, [], "内网 URL 必须在发起请求前被拦")
        self.assertTrue(any("内网" in r or "安全" in r for r in result.reasons))


if __name__ == "__main__":
    unittest.main()
