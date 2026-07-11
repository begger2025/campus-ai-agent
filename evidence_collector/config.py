"""Environment-only configuration for the evidence collector.

Provider credentials are inspected only to determine availability; configuration
objects retain no credential values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_PROVIDER_IDS = ("deepseek", "glm", "kimi", "doubao", "qwen")


@dataclass(frozen=True)
class ProviderSettings:
    """Non-sensitive provider availability state."""

    provider_id: str
    enabled: bool


@dataclass(frozen=True)
class CollectorSettings:
    """Configuration that is safe to log, display, and pass around."""

    database_url: str
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


def _local_database_url() -> str:
    database_path = Path(__file__).resolve().parent / "evidence_collector.db"
    return f"sqlite:///{database_path.as_posix()}"


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def load_settings(environ: Mapping[str, str] | None = None) -> CollectorSettings:
    """Load non-sensitive settings without requiring API or collector tokens."""

    environment = _environment(environ)
    database_url = (
        environment.get("EVIDENCE_DATABASE_URL")
        or environment.get("DATABASE_URL")
        or _local_database_url()
    )
    providers: dict[str, ProviderSettings] = {}
    for provider_id in SUPPORTED_PROVIDER_IDS:
        prefix = f"EVIDENCE_{provider_id.upper()}"
        has_api_key = bool((environment.get(f"{prefix}_API_KEY") or "").strip())
        web_search_enabled = _is_true(environment.get(f"{prefix}_WEB_SEARCH_ENABLED"))
        providers[provider_id] = ProviderSettings(
            provider_id=provider_id,
            enabled=has_api_key and web_search_enabled,
        )
    return CollectorSettings(database_url=database_url, providers=providers)


def require_collector_token(environ: Mapping[str, str] | None = None) -> str:
    """Require the API token at API startup, rather than during configuration."""

    token = (_environment(environ).get("EVIDENCE_COLLECTOR_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("EVIDENCE_COLLECTOR_TOKEN must be set before starting the API")
    return token
