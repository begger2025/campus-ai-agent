"""Provider configuration for the evidence collector.

Provider credentials are inspected only to determine availability; configuration
objects retain no credential values.  The database URL and any collector-side
API token are deliberately NOT part of this module: the backend owns the single
SQLAlchemy engine (``backend.database``) and already authenticates callers with
JWT, so a second DB URL or a second auth token would only be a liability.

Reads the main project's .env (already loaded by backend.database, but load
again defensively so this module works standalone).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent.parent.parent

# interpolate=False: Windows 下 %26 不会被 dotenv 误解析
load_dotenv(ROOT / ".env", override=False, interpolate=False)


SUPPORTED_PROVIDER_IDS = ("deepseek", "glm", "kimi", "doubao", "qwen")


@dataclass(frozen=True)
class ProviderSettings:
    """Non-sensitive provider availability state."""

    provider_id: str
    enabled: bool


@dataclass(frozen=True)
class CollectorSettings:
    """Configuration that is safe to log, display, and pass around."""

    providers: Mapping[str, ProviderSettings]

    @property
    def enabled_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            provider_id
            for provider_id, provider in self.providers.items()
            if provider.enabled
        )


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def http_trust_env(environ: Mapping[str, str] | None = None) -> bool:
    """证据侧的 httpx 客户端是否允许继承环境/系统代理配置。**默认 False（直连）。**

    ``httpx.AsyncClient`` 默认 ``trust_env=True``，在 Windows 上它不只读
    ``HTTP_PROXY``/``HTTPS_PROXY``，还会读**注册表里的系统代理**（Clash 一类工具会写
    这里）。结果是：清空环境变量也没用，抓取真实可达的 ``https://xxgk.sysu.edu.cn/``
    会 ConnectTimeout——而校验器曾把这种失败报成"可能是编造的链接"，真证据被当成幻觉。
    所以默认直连；确实需要走代理才能上网的人，显式设 ``EVIDENCE_HTTP_TRUST_ENV=true``。
    """

    return _is_true(_environment(environ).get("EVIDENCE_HTTP_TRUST_ENV"))


def load_settings(environ: Mapping[str, str] | None = None) -> CollectorSettings:
    """Load non-sensitive provider settings without requiring API keys."""

    environment = _environment(environ)
    providers: dict[str, ProviderSettings] = {}
    for provider_id in SUPPORTED_PROVIDER_IDS:
        prefix = f"EVIDENCE_{provider_id.upper()}"
        has_api_key = bool((environment.get(f"{prefix}_API_KEY") or "").strip())
        web_search_enabled = _is_true(environment.get(f"{prefix}_WEB_SEARCH_ENABLED"))
        providers[provider_id] = ProviderSettings(
            provider_id=provider_id,
            enabled=has_api_key and web_search_enabled,
        )
    return CollectorSettings(providers=providers)


__all__ = [
    "SUPPORTED_PROVIDER_IDS",
    "CollectorSettings",
    "ProviderSettings",
    "http_trust_env",
    "load_settings",
]
