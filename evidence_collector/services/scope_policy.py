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


# Keep these values aligned with ``evidence_collector.schemas.SCOPE_DECISIONS``
# so service results can be stored without translation at call sites.
Decision = Literal["in_scope", "out_of_scope", "needs_review"]
_VALID_DECISIONS = frozenset({"in_scope", "out_of_scope", "needs_review"})
_SOURCE_TYPE_ALIASES = {"official": "official", "official_notice": "official", "news": "news"}


def _normalize_hostname(hostname: str | None) -> str:
    """Return a lowercase DNS hostname or an empty string when malformed."""

    if not isinstance(hostname, str):
        return ""
    value = hostname.strip().lower()
    if value.endswith("."):
        # A single DNS root terminator is harmless; multiple trailing dots
        # indicate an empty label and are rejected below.
        if value.endswith(".."):
            return ""
        value = value[:-1]
    if not value or len(value) > 253:
        return ""
    labels = value.split(".")
    if any(not label or len(label) > 63 for label in labels):
        return ""
    label_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    if any(label_pattern.fullmatch(label) is None for label in labels):
        return ""
    return value


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
        if self.decision not in _VALID_DECISIONS:
            raise ValueError(
                "decision must be one of: in_scope, out_of_scope, needs_review"
            )
        cleaned = [
            reason.strip()
            for reason in self.reasons
            if isinstance(reason, str) and reason.strip()
        ]
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
    raw = source_domain.strip()
    if not raw or any(character.isspace() for character in raw):
        return ""
    # URL-shaped values are accepted only as valid HTTP(S) URLs.  In
    # particular, do not let ``file://sysu.edu.cn`` or a bad port collapse to
    # the hostname and accidentally pass the official-domain policy.
    if "://" in raw:
        try:
            parsed = urlsplit(raw)
            if parsed.scheme.lower() not in {"http", "https"}:
                return ""
            if not parsed.netloc or parsed.username is not None or parsed.password is not None:
                return ""
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                return ""
            # Accessing ``port`` validates malformed and out-of-range ports.
            _ = parsed.port
            value = _normalize_hostname(parsed.hostname)
        except ValueError:
            return ""
        return value

    # Bare domains are intentionally strict: ports, paths, credentials, and
    # URL delimiters are not part of a source-domain value.
    value = _normalize_hostname(raw)
    if any(character in value for character in "/?#@:"):
        return ""
    return value


def _domain_allowed(domain: str, allowlist: Iterable[str]) -> bool:
    for allowed in allowlist:
        value = allowed.lower().strip().rstrip(".")
        if not value:
            continue
        if value.startswith("*."):
            if domain == value[2:] or domain.endswith(f".{value[2:]}"):
                return True
        # Bare entries cover ordinary subdomains at a dot boundary, while
        # preventing lookalikes such as ``evil-sysu.edu.cn`` from matching
        # ``sysu.edu.cn``.
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
    """Classify a candidate as ``in_scope``, ``needs_review`` or ``out_of_scope``.

    Full ``中山大学``/``Sun Yat-sen University`` evidence is required.  A
    record mentioning only the ambiguous shorthand ``中大`` is
    ``needs_review``; missing evidence, entities, domains, or unsupported
    source types are ``out_of_scope``.  In-scope official notices and news must also match their
    respective allowlists.  ``official_notice`` is accepted as a compatibility
    alias and normalized to the canonical ``official`` source type first.
    """

    raw_type = source_type.strip().lower() if isinstance(source_type, str) else ""
    normalized_type = _SOURCE_TYPE_ALIASES.get(raw_type, "")
    if not normalized_type:
        return ScopeDecision("out_of_scope", ["unsupported source type"])

    quote = evidence_quote.strip() if isinstance(evidence_quote, str) else ""
    if not quote:
        return ScopeDecision("out_of_scope", ["evidence quote is required"])

    domain = _normalize_domain(source_domain)
    if not domain:
        return ScopeDecision("out_of_scope", ["source domain is missing or malformed"])

    combined_text = " ".join(
        part.strip() for part in (title or "", quote) if isinstance(part, str) and part.strip()
    )
    if not _has_explicit_entity(combined_text):
        if "中大" in combined_text:
            return ScopeDecision(
                "needs_review",
                ["ambiguous 中大 reference lacks the full SYSU entity"],
            )
        return ScopeDecision(
            "out_of_scope",
            ["title/evidence quote lacks an explicit SYSU entity"],
        )

    if normalized_type == "official":
        if _domain_allowed(domain, SYSU_OFFICIAL_DOMAIN_ALLOWLIST):
            return ScopeDecision("in_scope", ["explicit SYSU entity on an allowlisted official domain"])
        return ScopeDecision("needs_review", ["official source domain is not in the SYSU allowlist"])

    if _domain_allowed(domain, NEWS_DOMAIN_ALLOWLIST):
        return ScopeDecision("in_scope", ["explicit SYSU entity on an allowlisted news domain"])
    return ScopeDecision("needs_review", ["news source domain is not in the allowed news list"])


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
