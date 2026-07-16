# -*- coding: utf-8 -*-
import httpx
import config


def make_async_client(**kwargs) -> httpx.AsyncClient:
    """创建统一配置的 httpx.AsyncClient。

    从配置文件读取 DISABLE_SSL_VERIFY（默认 False，即开启 SSL 验证）。
    仅在使用企业代理、Burp、mitmproxy 等中间人代理时才需将其设为 True。

    trust_env=False（审计修复 2026-07-17）：httpx 默认信任环境代理
    （HTTP_PROXY/Clash 系统代理），"关 Clash + 清代理三行"是纯人工纪律，
    漏一次就超时。要代理必须显式传 proxy=，环境里的不认。
    """
    kwargs.setdefault("verify", not getattr(config, "DISABLE_SSL_VERIFY", False))
    kwargs.setdefault("trust_env", False)
    return httpx.AsyncClient(**kwargs)
