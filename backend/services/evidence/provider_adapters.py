"""Per-provider web-search seam.

Every provider enables web search differently and returns its citations in a
different place, so the transport must not hardcode one vendor's contract.  An
adapter owns two responsibilities:

``build_request``
    Turn a :class:`SearchRequest` plus a :class:`TransportContext` into the
    complete HTTP request (URL, headers, body).  It is deliberately *not* just
    "extra body fields": a provider whose endpoint or auth header differs (豆包
    is expected to) can be added without changing this seam.

``extract_citations``
    Pull the vendor-shaped citation records out of the JSON response.  The rows
    it returns are still raw provider dictionaries; ``http_transport`` maps them
    onto the neutral url/quote/title/source_type shape.

Only 智谱 GLM is implemented here.  The other four providers keep the previous
generic behaviour (a plain chat-completions body, citations discovered by the
generic parser) until their contracts are confirmed; adding one is a local
change: write two functions and register one adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from backend.services.evidence import scope_policy
from backend.services.evidence.providers import SearchRequest


DEFAULT_SOURCE_TYPE = "web"


@dataclass(frozen=True, slots=True)
class ProviderHttpRequest:
    """One fully-formed provider HTTP request."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransportContext:
    """Everything an adapter may need, minus anything it may log."""

    provider_id: str
    endpoint: str
    model: str | None = None
    api_key: str = field(default="", repr=False)
    system_prompt: str = ""


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    return None


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def bearer_headers(context: TransportContext) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {context.api_key}",
        "Content-Type": "application/json",
    }


def chat_completions_body(request: SearchRequest, context: TransportContext) -> dict[str, Any]:
    return {
        "model": request.model or context.model,
        "messages": [
            {"role": "system", "content": context.system_prompt},
            {"role": "user", "content": request.query},
        ],
        "temperature": 0,
        "max_tokens": max(256, request.max_results * 256),
    }


def build_generic_request(request: SearchRequest, context: TransportContext) -> ProviderHttpRequest:
    """The previous behaviour: an OpenAI-compatible chat body, no search tool."""

    return ProviderHttpRequest(
        url=context.endpoint,
        headers=bearer_headers(context),
        body=chat_completions_body(request, context),
    )


def extract_generic_citations(payload: Mapping[str, Any]) -> list[Any]:
    """No vendor-specific citation location is known for generic providers.

    The generic parser in ``http_transport`` still inspects ``citations`` /
    ``sources`` / JSON in the message content, so returning nothing here means
    "nothing *extra* to look at", not "no citations".
    """

    return []


# —— 智谱 GLM ————————————————————————————————————————————————
# 契约（官方文档）：
#   POST https://open.bigmodel.cn/api/paas/v4/chat/completions
#   body.tools = [{"type": "web_search",
#                  "web_search": {"enable": true, "search_result": true}}]
#   引用回传在 choices[].message.tool_calls[] 中 type == "web_search" 的
#   search_result[] 数组里，正文在 content 字段、链接在 link 字段。
GLM_WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search",
    "web_search": {"enable": True, "search_result": True},
}


def build_glm_request(request: SearchRequest, context: TransportContext) -> ProviderHttpRequest:
    """A chat body that actually turns 联网检索 on.

    Without ``tools`` the model never searches: it answers from memory and
    invents plausible-looking citation URLs.
    """

    generic = build_generic_request(request, context)
    body = dict(generic.body)
    body["tools"] = [dict(GLM_WEB_SEARCH_TOOL)]
    return ProviderHttpRequest(url=generic.url, headers=generic.headers, body=body)


def extract_glm_citations(payload: Mapping[str, Any]) -> list[Any]:
    """Return GLM's ``search_result`` entries from the web_search tool call."""

    rows: list[Any] = []
    for choice in _sequence(payload.get("choices")):
        choice_map = _mapping(choice)
        if choice_map is None:
            continue
        message = _mapping(choice_map.get("message")) or {}
        for call in _sequence(message.get("tool_calls")):
            call_map = _mapping(call)
            if call_map is None:
                continue
            if str(call_map.get("type", "")).strip().lower() != "web_search":
                continue
            for result in _sequence(call_map.get("search_result")):
                result_map = _mapping(result)
                if result_map is not None:
                    rows.append(dict(result_map))
    return rows


@dataclass(frozen=True, slots=True)
class ProviderWebSearchAdapter:
    """How one provider is asked to search, and where its citations land."""

    provider_id: str
    build_request: Callable[[SearchRequest, TransportContext], ProviderHttpRequest]
    extract_citations: Callable[[Mapping[str, Any]], list[Any]]


GENERIC_ADAPTER = ProviderWebSearchAdapter(
    provider_id="generic",
    build_request=build_generic_request,
    extract_citations=extract_generic_citations,
)

GLM_ADAPTER = ProviderWebSearchAdapter(
    provider_id="glm",
    build_request=build_glm_request,
    extract_citations=extract_glm_citations,
)

# deepseek / kimi / doubao / qwen intentionally fall through to GENERIC_ADAPTER
# until their real contracts are confirmed.
PROVIDER_WEB_SEARCH_ADAPTERS: dict[str, ProviderWebSearchAdapter] = {"glm": GLM_ADAPTER}


def adapter_for(provider_id: str) -> ProviderWebSearchAdapter:
    """Return the provider's adapter, or the generic one."""

    return PROVIDER_WEB_SEARCH_ADAPTERS.get(
        (provider_id or "").strip().lower(), GENERIC_ADAPTER
    )


def derive_source_type(url: Any, default: str = DEFAULT_SOURCE_TYPE) -> str:
    """Classify a citation by its domain.

    Real web-search results do not label themselves ``official``/``news``, so the
    provider layer derives the label the scope policy needs.  The allowlists and
    the dot-boundary matcher are reused from ``scope_policy`` on purpose: that
    matcher is what stops ``sysu.edu.cn.evil.com`` from passing as official, and
    a second copy of it here would eventually drift out of sync.
    """

    if not isinstance(url, str) or not url.strip():
        return default
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return default
    domain = scope_policy._normalize_hostname(parsed.hostname)
    if not domain:
        return default
    if scope_policy._domain_allowed(domain, scope_policy.SYSU_OFFICIAL_DOMAIN_ALLOWLIST):
        return "official"
    if scope_policy._domain_allowed(domain, scope_policy.NEWS_DOMAIN_ALLOWLIST):
        return "news"
    return default


__all__ = [
    "DEFAULT_SOURCE_TYPE",
    "GENERIC_ADAPTER",
    "GLM_ADAPTER",
    "GLM_WEB_SEARCH_TOOL",
    "PROVIDER_WEB_SEARCH_ADAPTERS",
    "ProviderHttpRequest",
    "ProviderWebSearchAdapter",
    "TransportContext",
    "adapter_for",
    "bearer_headers",
    "build_generic_request",
    "build_glm_request",
    "chat_completions_body",
    "derive_source_type",
    "extract_generic_citations",
    "extract_glm_citations",
]
