"""引用真实性核验：真的把那个 URL 抓下来看一眼。

这是整个证据采集功能的要害。模型可以凭空编出一个看起来完全合理的
``https://news.sysu.edu.cn/...`` 链接——而这样的域名还会被 ``derive_source_type``
判为 ``official``、被 ``scope_policy`` 判为 ``in_scope``，人工审核员看到的会是一条
"完美"的假证据。所以核验必须落到实处：GET 那个 URL，页面不存在就当场驳回。

HTTP 客户端一律由调用方注入，与本包"没有注入客户端 = 不上网"的纪律一致：
没有客户端时核验器是**不可用**（抛异常），而不是静默通过。

**但"抓不到"不等于"是假的"。** 早期实现把任何抓取异常都判成 ``rejected`` +
"可能是编造的链接"，结果本机代理配置一出问题，真实的中大信息公开网通知就被扣上"AI 幻觉"
的帽子，审核员照着那句话把真证据丢掉——核验器把真的变成了假的，比不核验更糟。所以结论
必须与证据强度匹配（见 ``_classify_transport_error`` 与 ``check``）：
只有**域名不存在**和 **404/410** 才是伪造的硬证据；超时/连接失败/403 一律是"核验未完成"。
"""

from __future__ import annotations

import html as html_module
import json
import re
import socket
import ssl
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from backend.models_evidence import EvidenceItem, EvidenceVerification
from backend.services.evidence.collector import sanitize_error
from backend.services.evidence.review_delivery import verify_item


# ``EvidenceVerification.method`` 上限 64 字符；这个名字会进审计行，别改。
FETCH_VERIFICATION_METHOD = "fetch_url"

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; SYSU-CampusEvidenceBot/1.0; +https://www.sysu.edu.cn/)"
)

# 供应商经常截断引用、或把句读改写一遍，所以不要求全文命中：去掉全部空白之后，
# 只要正文里能连续命中引用的前 ``_PREFIX_CHARS`` 个字符，就算命中（引用本身更短时
# 用全文）。前缀太短会误判，因此低于 ``_MIN_MATCH_CHARS`` 的引用一律不算命中。
_PREFIX_CHARS = 16
_MIN_MATCH_CHARS = 8

_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


# 页面明确不存在，这是死链/编造链接的硬证据（410 Gone 同理）。其余非 2xx（401/403/429/5xx）
# 多半是反爬保护或服务端故障，真实页面天天返回 403——据此驳回等于销毁真证据。
_DEAD_PAGE_STATUSES = frozenset({404, 410})

# 审核员会一字不差地读到这句话，所以必须写清楚"这不是对链接真伪的判断"。
_NOT_A_FABRICATION_VERDICT = "不能据此认定该链接是编造的，请人工打开链接确认"


class AsyncHttpClient(Protocol):
    async def get(self, url: str, **kwargs: Any) -> Any: ...


class VerifierUnavailableError(RuntimeError):
    """没有注入 HTTP 客户端时抛出——不可用，而不是"默认通过"。"""


@dataclass(frozen=True, slots=True)
class FetchVerificationResult:
    """一次抓取核验的结论；``status`` 取自 schemas.VERIFICATION_STATUSES。"""

    status: str
    reasons: list[str] = field(default_factory=list)
    method: str = FETCH_VERIFICATION_METHOD
    http_status: int | None = None


def page_text(html: str) -> str:
    """把页面压成可比对的纯文本：去脚本、去标签、解实体、归一空白。"""

    if not isinstance(html, str):
        return ""
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _TAG.sub(" ", text)
    text = html_module.unescape(text)
    return _WHITESPACE.sub("", text)


def _needle(quote: str) -> str:
    """引用本身也要按同样规则归一，否则空白/换行差异会造成假阴性。"""

    return _WHITESPACE.sub("", html_module.unescape(quote or ""))


def quote_found(html: str, quote: str) -> bool:
    text = page_text(html)
    needle = _needle(quote)
    if not text or len(needle) < _MIN_MATCH_CHARS:
        return False
    if needle in text:
        return True
    prefix = needle[:_PREFIX_CHARS]
    return len(prefix) >= _MIN_MATCH_CHARS and prefix in text


def _cause_chain(error: BaseException) -> Iterator[BaseException]:
    """异常本身 + 它的 ``__cause__`` / ``__context__`` 链（防环）。"""

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _chain_contains(error: BaseException, kind: type[BaseException]) -> bool:
    return any(isinstance(exc, kind) for exc in _cause_chain(error))


def classify_fetch_error(error: BaseException) -> FetchVerificationResult:
    """把一次抓取失败翻译成"证据强度匹配"的结论。

    只有 **DNS 解析失败** 才是伪造的硬证据：主机名压根不存在。httpx 会把它包成
    ``httpx.ConnectError``，真正的 ``socket.gaierror`` 挂在 ``__cause__`` 链上，因此这里
    按**异常类型沿因果链判断**，而不是匹配错误文案（文案随平台/语言变）。

    超时、连接被拒、网络不可达、TLS 失败、代理故障——这些只说明**我们没能完成这次核验**，
    对引用的真伪一无所知。把它们判成 ``rejected`` 曾让真实的中大官网通知被当成 AI 幻觉丢掉。
    """

    detail = sanitize_error(error, limit=300)
    if _chain_contains(error, socket.gaierror):
        return FetchVerificationResult(
            status="rejected",
            reasons=[
                f"证据链接的域名无法解析（DNS 中不存在该主机名），该站点根本不存在，"
                f"判定为编造的链接：{detail}"
            ],
        )

    if isinstance(error, httpx.TimeoutException):
        cause = "连接/读取该链接超时"
    elif _chain_contains(error, ssl.SSLError):
        cause = "与该站点的 TLS 握手失败"
    elif isinstance(error, httpx.ProxyError):
        cause = "本机代理不可用"
    elif isinstance(error, httpx.TransportError) or _chain_contains(error, OSError):
        cause = "无法连接到该链接（网络不可达或连接被拒）"
    else:
        cause = "抓取过程出现异常"
    return FetchVerificationResult(
        status="needs_review",
        reasons=[
            f"未能完成核验：{cause}，通常是本机网络不通或系统代理（如 Clash）拦截所致；"
            f"{_NOT_A_FABRICATION_VERDICT}。（详情：{detail}）"
        ],
    )


class UrlFetchVerifier:
    """GET 证据的 canonical_url，用页面正文验证引用是否真实存在。"""

    def __init__(
        self,
        client: AsyncHttpClient | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._user_agent = user_agent

    @property
    def available(self) -> bool:
        return self._client is not None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"UrlFetchVerifier(client_injected={self.available})"

    async def check(self, url: str, quote: str) -> FetchVerificationResult:
        if self._client is None:
            raise VerifierUnavailableError(
                "evidence verification has no injected HTTP client; network access is disabled"
            )
        candidate = (url or "").strip()
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return FetchVerificationResult(
                status="rejected",
                reasons=[f"证据链接不是可访问的 HTTP(S) 地址：{candidate[:200] or '<空>'}"],
            )

        try:
            response = await self._client.get(
                candidate,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
                timeout=self._timeout,
            )
        except Exception as error:  # 域名不存在 / 超时 / 连接被拒 / TLS / 代理
            # 只有"域名不存在"才是编造的证据；其余失败只说明这次核验没做成。
            return classify_fetch_error(error)

        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            return FetchVerificationResult(
                status="needs_review",
                reasons=[f"未能完成核验：无法识别响应的 HTTP 状态码；{_NOT_A_FABRICATION_VERDICT}。"],
            )
        if status_code in _DEAD_PAGE_STATUSES:
            return FetchVerificationResult(
                status="rejected",
                reasons=[f"证据链接返回 HTTP {status_code}，该页面确实不存在（死链或编造的链接）"],
                http_status=status_code,
            )
        if not 200 <= status_code < 300:
            return FetchVerificationResult(
                status="needs_review",
                reasons=[
                    f"未能完成核验：证据链接返回 HTTP {status_code}，"
                    "常见于反爬保护、限流或服务端临时故障（真实页面同样会这样返回）；"
                    f"{_NOT_A_FABRICATION_VERDICT}。"
                ],
                http_status=status_code,
            )

        body = getattr(response, "text", "") or ""
        if quote_found(body, quote):
            return FetchVerificationResult(
                status="verified",
                reasons=[f"已抓取原页面（HTTP {status_code}）并在正文中定位到证据引用"],
                http_status=status_code,
            )
        return FetchVerificationResult(
            status="needs_review",
            reasons=[
                f"页面可访问（HTTP {status_code}），但正文中未能定位到该证据引用，"
                "可能被供应商改写/截断，需要人工比对原文"
            ],
            http_status=status_code,
        )


async def verify_item_by_fetch(
    session: Session,
    item_id: int,
    verifier: UrlFetchVerifier,
    *,
    verification_version: str | None = None,
) -> EvidenceVerification:
    """抓取核验一条证据，并写入一条可审计的 ``EvidenceVerification``。

    不提交事务（与 ``review_delivery`` 一致，由调用方决定何时 commit）；核验器不可用
    时抛 ``VerifierUnavailableError``，此时**不会**写任何行、不会改条目状态。
    """

    item = session.get(EvidenceItem, item_id)
    if item is None:
        raise LookupError("evidence item was not found")
    if not verifier.available:
        raise VerifierUnavailableError(
            "evidence verification has no injected HTTP client; network access is disabled"
        )
    result = await verifier.check(item.canonical_url or item.source_url, item.evidence_quote or "")
    return verify_item(
        session,
        item_id,
        method=result.method,
        status=result.status,
        reasons=list(result.reasons),
        verification_version=verification_version,
    )


def verification_reasons(value: str | None) -> list[str]:
    """把 ``EvidenceVerification.reasons``（JSON 文本或裸文本）还原成列表。"""

    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [value]
    if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
        return [str(entry) for entry in parsed if str(entry).strip()]
    return [str(parsed)]


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER_AGENT",
    "FETCH_VERIFICATION_METHOD",
    "AsyncHttpClient",
    "FetchVerificationResult",
    "UrlFetchVerifier",
    "VerifierUnavailableError",
    "classify_fetch_error",
    "page_text",
    "quote_found",
    "verification_reasons",
    "verify_item_by_fetch",
]
