"""Optional, provider-neutral HTTP transport for citation-bearing AI search.

The collector never creates a network client by itself.  Applications may
inject an async JSON client (for example an ``httpx.AsyncClient``) and build
one transport per configured provider.  API keys live only in the transport
instance and are excluded from representations; provider responses are
accepted only when they contain HTTP(S) citations and a non-empty quote.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias
from urllib.parse import urlsplit

from ..config import SUPPORTED_PROVIDER_IDS
from .providers import SearchRequest, normalize_hits


class AsyncJsonClient(Protocol):
    async def post(self, url: str, *, headers: Mapping[str, str], json: Mapping[str, Any]) -> Any: ...


class HttpTransportUnavailableError(RuntimeError):
    """Raised when an HTTP transport was used without an injected client."""


class HttpTransportResponseError(RuntimeError):
    """Raised for non-success HTTP responses or malformed JSON responses."""


JsonTransport: TypeAlias = Any


def _http_url(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be configured")
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    return url.rstrip("/")


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value] if isinstance(value, Mapping) else []


def _citation_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in _as_list(value):
        item = _mapping(entry)
        if item is None:
            continue
        url = item.get("url", item.get("link", item.get("source")))
        quote = item.get("quote", item.get("evidence_quote", item.get("snippet", item.get("text"))))
        if url and quote:
            rows.append(
                {
                    "url": str(url),
                    "quote": str(quote),
                    "title": item.get("title", item.get("name")),
                    "source_type": item.get("source_type", "web"),
                    "publisher": item.get("publisher"),
                    "published_at": item.get("published_at"),
                    "metadata": dict(item),
                }
            )
    return rows


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts = []
        for part in content:
            item = _mapping(part)
            if item and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _json_candidates(text: str) -> list[Any]:
    candidates: list[Any] = []
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    for candidate in [*fenced, text]:
        try:
            parsed = json.loads(candidate.strip())
        except (TypeError, json.JSONDecodeError):
            continue
        candidates.append(parsed)
    return candidates


def _markdown_rows(text: str) -> list[dict[str, Any]]:
    rows = []
    for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", text):
        rows.append({"url": url, "quote": text, "title": title, "source_type": "web"})
    return rows


def parse_citation_response(
    payload: Any,
    *,
    provider_id: str,
    model: str | None = None,
    request_id: str | None = None,
) -> list[Any]:
    """Extract normalized citation-bearing hits from common JSON responses."""

    root = _mapping(payload)
    if root is None:
        return []
    response_id = str(root.get("id", request_id)) if root.get("id", request_id) else request_id
    response_model = str(root.get("model", model)) if root.get("model", model) else model
    rows: list[dict[str, Any]] = []
    for key in ("hits", "results", "items", "citations", "sources"):
        rows.extend(_citation_rows(root.get(key)))

    choices = _as_list(root.get("choices"))
    for choice in choices:
        choice_map = _mapping(choice) or {}
        message = _mapping(choice_map.get("message")) or {}
        for key in ("citations", "sources", "annotations"):
            rows.extend(_citation_rows(message.get(key)))
        content = _content_text(message.get("content", choice_map.get("text")))
        for candidate in _json_candidates(content):
            candidate_map = _mapping(candidate)
            if candidate_map is not None:
                for key in ("hits", "results", "items", "citations", "sources"):
                    rows.extend(_citation_rows(candidate_map.get(key)))
            else:
                rows.extend(_citation_rows(candidate))
        if not rows:
            rows.extend(_markdown_rows(content))

    normalized: list[Any] = []
    for row in rows:
        row["provider"] = provider_id
        row["model"] = response_model
        row["request_id"] = response_id
        try:
            normalized.extend(
                normalize_hits([row], provider_id=provider_id, model=response_model, request_id=response_id)
            )
        except Exception:
            # Invalid or non-HTTP citations are deliberately ignored.  The
            # collector will persist nothing when a response has no usable URL.
            continue
    return normalized


async def _response_json(response: Any) -> Any:
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and status >= 400:
        raise HttpTransportResponseError(f"provider HTTP status {status}")
    value = response.json() if hasattr(response, "json") else response
    if inspect.isawaitable(value):
        value = await value
    if _mapping(value) is None:
        raise HttpTransportResponseError("provider response was not a JSON object")
    return value


@dataclass(slots=True)
class OpenAICompatibleTransport:
    """An explicitly injected, citation-only JSON transport."""

    provider_id: str
    endpoint: str
    model: str | None = None
    api_key: str = field(default="", repr=False)
    client: AsyncJsonClient | None = field(default=None, repr=False)
    system_prompt: str = (
        "Search the public internet for the requested SYSU information. "
        "Return only JSON with a citations array; every citation needs url, quote, and title."
    )

    def __post_init__(self) -> None:
        self.provider_id = self.provider_id.strip().lower()
        if self.provider_id not in SUPPORTED_PROVIDER_IDS:
            raise ValueError(f"unsupported provider_id: {self.provider_id!r}")
        self.endpoint = _http_url(self.endpoint, "endpoint")
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise ValueError("api_key must be configured")

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleTransport(provider_id={self.provider_id!r}, "
            f"endpoint={self.endpoint!r}, model={self.model!r}, client_injected={self.client is not None})"
        )

    async def __call__(self, request: SearchRequest, _safe_settings: Mapping[str, Any] | None = None) -> Any:
        if request.provider != self.provider_id:
            raise ValueError("request provider does not match transport provider")
        if self.client is None:
            raise HttpTransportUnavailableError(
                f"provider '{self.provider_id}' has no injected HTTP client; network access is disabled"
            )
        body = {
            "model": request.model or self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": request.query},
            ],
            "temperature": 0,
            "max_tokens": max(256, request.max_results * 256),
        }
        response = await self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
        )
        return await _response_json(response)


def build_http_transports(
    environ: Mapping[str, str] | None = None,
    *,
    client: AsyncJsonClient | Mapping[str, AsyncJsonClient] | None = None,
) -> dict[str, OpenAICompatibleTransport]:
    """Build transports only for fully configured providers and an injected client."""

    env = os.environ if environ is None else environ
    if client is None:
        return {}
    result: dict[str, OpenAICompatibleTransport] = {}
    for provider_id in SUPPORTED_PROVIDER_IDS:
        prefix = f"EVIDENCE_{provider_id.upper()}"
        key = (env.get(f"{prefix}_API_KEY") or "").strip()
        endpoint = (env.get(f"{prefix}_BASE_URL") or "").strip()
        model = (env.get(f"{prefix}_MODEL") or "").strip() or None
        enabled = (env.get(f"{prefix}_WEB_SEARCH_ENABLED") or "").strip().lower() == "true"
        if not (key and endpoint and model and enabled):
            continue
        selected_client = client.get(provider_id) if isinstance(client, Mapping) else client
        if selected_client is None:
            continue
        result[provider_id] = OpenAICompatibleTransport(
            provider_id=provider_id,
            endpoint=endpoint,
            model=model,
            api_key=key,
            client=selected_client,
        )
    return result


__all__ = [
    "AsyncJsonClient",
    "HttpTransportUnavailableError",
    "HttpTransportResponseError",
    "OpenAICompatibleTransport",
    "build_http_transports",
    "parse_citation_response",
]
