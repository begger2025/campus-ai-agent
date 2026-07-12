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
    search_engine: str | None = None


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
# 实测契约（用真实 key 打过线上接口，以此为准，勿信文档/模型的转述）：
#   POST https://open.bigmodel.cn/api/paas/v4/web_search
#   headers: Authorization: Bearer <key>
#   body:    {"search_engine": "<engine>", "search_query": "<query>"}
#   response（顶层，不套 choices）：
#     {"id": ..., "request_id": ..., "search_intent": [...],
#      "search_result": [{"title", "content", "link", "media", "icon",
#                         "refer", "publish_date"}]}
#
# 这不是 chat 接口。之前的实现打的是 chat/completions 并从
# choices[].message.tool_calls[].search_result[] 里取引用——线上响应里根本
# 没有 tool_calls 字段：联网检索确实发生了（答案含最新信息），但**不回传任何
# 来源 URL**；再要求模型给出引用，它就会编造（实测出现过
# https://example.com/reference1）。
#
# 设计收益：引用现在直接来自搜索引擎索引，而不是模型生成的文本，因此在引用层
# 面伪造来源 URL 结构上不可能发生。verification.py 的抓取校验仍然保留，但职责
# 从“抓模型幻觉”变成“抓死链与引文漂移”——纵深防御。
#
# 引擎档位（同一 query 实测）：
#   search_std / search_pro          → 10 条结果，link 全为 ""（无来源 URL）
#   search_pro_sogou / _bing / _quark / _jina → 10 条结果，link 全部真实可用
# 基础档位没有归属 URL，无法做可审计证据，因此只用 search_pro_* 档位。
DEFAULT_GLM_SEARCH_ENGINE = "search_pro_bing"
GLM_SEARCH_PATH = "/web_search"
_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


def glm_search_url(endpoint: str | None) -> str:
    """Resolve the 智谱 web-search endpoint from whatever is configured.

    A leftover ``.../chat/completions`` base URL is migrated to the search
    endpoint rather than posted to: the chat endpoint answers a search body with
    HTTP 200 and a useless payload, and that silent success is exactly what
    produced the fabricated citation URLs.  Anything else fails loudly.
    """

    url = (endpoint or "").strip().rstrip("/")
    if url.endswith(GLM_SEARCH_PATH):
        return url
    if url.endswith(_CHAT_COMPLETIONS_SUFFIX):
        return url[: -len(_CHAT_COMPLETIONS_SUFFIX)] + GLM_SEARCH_PATH
    raise ValueError(
        "EVIDENCE_GLM_BASE_URL must point at 智谱的独立检索接口 "
        "https://open.bigmodel.cn/api/paas/v4/web_search "
        f"(configured: {url or '<empty>'!r}); the chat/completions endpoint returns "
        "no source URLs and must not be used for evidence"
    )


# ``search_query`` 是**检索词**，不是提示词。采集器给每条查询都套了一句上下文
# （"中山大学……校园公共信息与舆情；仅返回明确涉及中山大学的可引用公开信息。原始检索词：X"），
# 那对 chat 供应商是对的，对搜索引擎却是灾难：整句话就是检索式本身，"信息公开"这类样板词
# 会盖过真正的关键词。首次真实运行实测——6 个关键词（学术不端/实名举报/东校宿舍搬迁/作息调整/
# 宿舍起火/食堂）返回的是**完全相同**的 10 条"中山大学信息公开网"页面，关键词一个字都没起作用。
# 所以这里把提示词还原成检索式：取回原始检索词，并保证带上"中山大学"做学校限定
# （否则"宿舍起火"会搜到台湾的国立中山大学 nsysu.edu.tw）。
_RAW_QUERY_MARKER = "原始检索词："
_SYSU_QUALIFIER = "中山大学"


def glm_search_query(query: str) -> str:
    """把采集器的提示词还原成一条真正的检索式。"""

    text = str(query or "").strip()
    if _RAW_QUERY_MARKER in text:
        text = text.rsplit(_RAW_QUERY_MARKER, 1)[1].strip()
    if not text:
        return _SYSU_QUALIFIER
    if _SYSU_QUALIFIER in text:
        return text
    return f"{_SYSU_QUALIFIER} {text}"


def build_glm_request(request: SearchRequest, context: TransportContext) -> ProviderHttpRequest:
    """The standalone web-search call: no model, no messages, just a query."""

    engine = (context.search_engine or "").strip() or DEFAULT_GLM_SEARCH_ENGINE
    return ProviderHttpRequest(
        url=glm_search_url(context.endpoint),
        headers=bearer_headers(context),
        body={"search_engine": engine, "search_query": glm_search_query(request.query)},
    )


def _http_link(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    link = value.strip()
    return link if urlsplit(link).scheme.lower() in {"http", "https"} else ""


def extract_glm_citations(payload: Mapping[str, Any]) -> list[Any]:
    """Map the top-level ``search_result`` entries onto citation rows.

    Entries without a usable HTTP(S) ``link`` are dropped: the basic engine tiers
    return content with an empty ``link``, and an un-attributed result is not
    evidence.
    """

    rows: list[Any] = []
    for result in _sequence(payload.get("search_result")):
        result_map = _mapping(result)
        if result_map is None:
            continue
        link = _http_link(result_map.get("link"))
        if not link:
            continue
        rows.append(
            {
                "url": link,
                "quote": result_map.get("content"),
                "title": result_map.get("title"),
                "publisher": result_map.get("media") or None,
                "published_at": result_map.get("publish_date") or None,
                "refer": result_map.get("refer"),
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class ProviderWebSearchAdapter:
    """How one provider is asked to search, and where its citations land."""

    provider_id: str
    build_request: Callable[[SearchRequest, TransportContext], ProviderHttpRequest]
    extract_citations: Callable[[Mapping[str, Any]], list[Any]]
    # Chat providers cannot be called without a model; 智谱的 web_search 接口不接受
    # model，所以它不能因为 EVIDENCE_GLM_MODEL 为空就被工厂悄悄跳过。
    requires_model: bool = True


GENERIC_ADAPTER = ProviderWebSearchAdapter(
    provider_id="generic",
    build_request=build_generic_request,
    extract_citations=extract_generic_citations,
)

GLM_ADAPTER = ProviderWebSearchAdapter(
    provider_id="glm",
    build_request=build_glm_request,
    extract_citations=extract_glm_citations,
    requires_model=False,
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
    "DEFAULT_GLM_SEARCH_ENGINE",
    "DEFAULT_SOURCE_TYPE",
    "GENERIC_ADAPTER",
    "GLM_ADAPTER",
    "GLM_SEARCH_PATH",
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
    "glm_search_query",
    "glm_search_url",
]
