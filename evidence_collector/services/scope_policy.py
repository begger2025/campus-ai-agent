"""Pure, auditable source-scope policy for SYSU evidence.

``assess_scope`` uses only source metadata supplied by its caller.  It never
fetches a URL or invokes an AI service, making the result deterministic and
easy to audit in tests.  Domain allowlists are module-level configuration and
can be replaced by an application at startup (or via
``configure_scope_policy``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Iterable, Literal
from urllib.parse import urlsplit


Decision = Literal["accepted", "uncertain", "rejected"]


def _configured_domains(environment_key: str, defaults: Iterable[str]) -> set[str]:
    configured = os.getenv(environment_key)
    if configured is None:
        return {domain.lower().strip().rstrip(".") for domain in defaults}
    return {
        domain.lower().strip().rstrip(".")
        for domain in configured.split(",")
        if domain.strip()
    }


_DEFAULT_SYSU_OFFICIAL_DOMAINS = {
    "sysu.edu.cn",
    "www.sysu.edu.cn",
    "news.sysu.edu.cn",
    "www2.sysu.edu.cn",
    "admission.sysu.edu.cn",
    "graduate.sysu.edu.cn",
    "jwb.sysu.edu.cn",
    "xsc.sysu.edu.cn",
}
_DEFAULT_NEWS_DOMAINS = {
    "people.com.cn",
    "xinhuanet.com",
    "cctv.com",
    "thepaper.cn",
    "sina.com.cn",
    "sohu.com",
    "163.com",
    "qq.com",
    "chinanews.com.cn",
    "caixin.com",
    "yicai.com",
    "ifeng.com",
    "southcn.com",
    "dayoo.com",
}

# Public, replaceable configuration.  The aliases retain intuitive names for
# callers while the longer names make their purpose explicit.
SYSU_OFFICIAL_DOMAIN_ALLOWLIST: set[str] = _configured_domains(
    "EVIDENCE_SYSU_OFFICIAL_DOMAINS", _DEFAULT_SYSU_OFFICIAL_DOMAINS
)
NEWS_DOMAIN_ALLOWLIST: set[str] = _configured_domains(
    "EVIDENCE_ALLOWED_NEWS_DOMAINS", _DEFAULT_NEWS_DOMAINS
)
SYSU_OFFICIAL_DOMAINS = SYSU_OFFICIAL_DOMAIN_ALLOWLIST
ALLOWED_NEWS_DOMAINS = NEWS_DOMAIN_ALLOWLIST
ALLOWED_NEWS_DOMAIN_ALLOWLIST = NEWS_DOMAIN_ALLOWLIST


@dataclass(frozen=True)
class ScopeDecision:
    """A scope classification and at least one human-readable reason."""

    decision: Decision
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        cleaned = [reason.strip() for reason in self.reasons if isinstance(reason, str)]
        if not cleaned:
            raise ValueError("scope decisions require at least one non-empty reason")
        object.__setattr__(self, "reasons", cleaned)

    @property
    def status(self) -> Decision:
        """Alias useful to callers that use ``status`` for result objects."""

        return self.decision

    @property
    def reason(self) -> str:
        """Return the primary reason while ``reasons`` retains full audit text."""

        return self.reasons[0]


def configure_scope_policy(
    *,
    official_domains: Iterable[str] | None = None,
    news_domains: Iterable[str] | None = None,
) -> None:
    """Replace one or both domain allowlists for the current process.

    This is intended for explicit application configuration and tests; no
    network or external configuration service is consulted.
    """

    global SYSU_OFFICIAL_DOMAIN_ALLOWLIST, SYSU_OFFICIAL_DOMAINS
    global NEWS_DOMAIN_ALLOWLIST, ALLOWED_NEWS_DOMAINS, ALLOWED_NEWS_DOMAIN_ALLOWLIST
    if official_domains is not None:
        SYSU_OFFICIAL_DOMAIN_ALLOWLIST = _clean_domains(official_domains)
        SYSU_OFFICIAL_DOMAINS = SYSU_OFFICIAL_DOMAIN_ALLOWLIST
    if news_domains is not None:
        NEWS_DOMAIN_ALLOWLIST = _clean_domains(news_domains)
        ALLOWED_NEWS_DOMAINS = NEWS_DOMAIN_ALLOWLIST
        ALLOWED_NEWS_DOMAIN_ALLOWLIST = NEWS_DOMAIN_ALLOWLIST


def _clean_domains(domains: Iterable[str]) -> set[str]:
    return {
        domain.lower().strip().rstrip(".")
        for domain in domains
        if isinstance(domain, str) and domain.strip()
    }


def _normalize_domain(source_domain: str | None) -> str:
    if not isinstance(source_domain, str):
        return ""
    value = source_domain.strip().lower().rstrip(".")
    if not value:
        return ""
    # Accept either a bare domain or a URL-shaped value for convenience.
    if "://" in value:
        try:
            value = (urlsplit(value).hostname or "").lower().rstrip(".")
        except ValueError:
            return ""
    # A source_domain may include a port, but it must not contain a path.
    if "/" in value:
        return ""
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif ":" in value:
        value = value.split(":", 1)[0]
    return value


def _domain_allowed(domain: str, allowlist: Iterable[str]) -> bool:
    for allowed in allowlist:
        value = allowed.lower().strip().rstrip(".")
        if not value:
            continue
        if value.startswith("*."):
            if domain == value[2:] or domain.endswith(value[1:]):
                return True
        # A configured registrable domain covers its ordinary subdomains,
        # while the dot boundary prevents lookalikes such as
        # ``notpeople.com.cn`` from matching ``people.com.cn``.
        elif domain == value or domain.endswith(f".{value}"):
            return True
    return False


_ENTITY_PATTERNS = (
    re.compile(r"中山大学"),
    re.compile(r"sun\s+yat[- ]sen\s+university", re.IGNORECASE),
)


def _has_explicit_entity(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ENTITY_PATTERNS)


def assess_scope(
    source_type: str | None,
    source_domain: str | None,
    title: str | None,
    evidence_quote: str | None,
) -> ScopeDecision:
    """Classify a candidate as ``accepted``, ``uncertain`` or ``rejected``.

    Full ``中山大学``/``Sun Yat-sen University`` evidence is required.  A
    record mentioning only the ambiguous shorthand ``中大`` is ``uncertain``;
    missing evidence, entities, domains, or unsupported source types are
    rejected.  Accepted official notices and news must also match their
    respective allowlists.
    """

    normalized_type = source_type.strip().lower() if isinstance(source_type, str) else ""
    if normalized_type not in {"official_notice", "news"}:
        return ScopeDecision("rejected", ["unsupported source type"])

    quote = evidence_quote.strip() if isinstance(evidence_quote, str) else ""
    if not quote:
        return ScopeDecision("rejected", ["evidence quote is required"])

    domain = _normalize_domain(source_domain)
    if not domain:
        return ScopeDecision("rejected", ["source domain is required"])

    combined_text = " ".join(
        part.strip() for part in (title or "", quote) if isinstance(part, str) and part.strip()
    )
    if not _has_explicit_entity(combined_text):
        if "中大" in combined_text:
            return ScopeDecision(
                "uncertain",
                ["ambiguous 中大 reference lacks the full SYSU entity"],
            )
        return ScopeDecision(
            "rejected",
            ["title/evidence quote lacks an explicit SYSU entity"],
        )

    if normalized_type == "official_notice":
        if _domain_allowed(domain, SYSU_OFFICIAL_DOMAIN_ALLOWLIST):
            return ScopeDecision("accepted", ["explicit SYSU entity on an allowlisted official domain"])
        return ScopeDecision("uncertain", ["official source domain is not in the SYSU allowlist"])

    if _domain_allowed(domain, NEWS_DOMAIN_ALLOWLIST):
        return ScopeDecision("accepted", ["explicit SYSU entity on an allowlisted news domain"])
    return ScopeDecision("uncertain", ["news source domain is not in the allowed news list"])


__all__ = [
    "ALLOWED_NEWS_DOMAINS",
    "ALLOWED_NEWS_DOMAIN_ALLOWLIST",
    "NEWS_DOMAIN_ALLOWLIST",
    "SYSU_OFFICIAL_DOMAINS",
    "SYSU_OFFICIAL_DOMAIN_ALLOWLIST",
    "ScopeDecision",
    "assess_scope",
    "configure_scope_policy",
]
