"""Canonical URL and stable external identifier helpers.

The functions in this module are deliberately pure: they do not resolve URLs
or make network requests.  Tracking query parameters are removed while the
relative order of all meaningful query parameters is retained.
"""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_TRACKING_KEYS = frozenset({"spm", "from"})


def canonicalize_url(url: str) -> str:
    """Return a deterministic canonical representation of an HTTP(S) URL.

    Host names and schemes are lower-cased, fragments are discarded, and
    common tracking parameters (``utm_*``, ``spm`` and ``from``) are removed.
    Meaningful query parameters, including duplicate keys, retain their input
    order.  Empty, malformed, credential-bearing, and non-HTTP(S) URLs raise
    :class:`ValueError`.
    """

    if not isinstance(url, str):
        raise ValueError("url must be a non-empty string")
    value = url.strip()
    if not value:
        raise ValueError("url must not be empty")
    # Whitespace in a URL is ambiguous and urlsplit otherwise accepts some
    # malformed forms (for example spaces in a path) without complaint.
    if any(character.isspace() for character in value):
        raise ValueError("url must not contain whitespace")

    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        # Accessing ``port`` validates malformed/out-of-range port values.
        port = parsed.port
    except ValueError as exc:
        raise ValueError("malformed URL") from exc

    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("URL scheme must be http or https")
    if not parsed.netloc or not hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not supported")

    hostname = hostname.lower().rstrip(".")
    if not hostname:
        raise ValueError("URL must include a hostname")
    # urlunsplit expects IPv6 literals to remain bracketed in netloc.
    host_for_netloc = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    netloc = host_for_netloc if port is None else f"{host_for_netloc}:{port}"

    meaningful_query: list[tuple[str, str]] = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_") or normalized_key in _TRACKING_KEYS:
            continue
        meaningful_query.append((key, query_value))

    query = urlencode(meaningful_query, doseq=True)
    # Keep an empty path empty; adding ``/`` would be an extra normalization
    # not required by the policy and would alter otherwise valid URLs.
    return urlunsplit((scheme, netloc, parsed.path, query, ""))


def stable_external_id(url: str) -> str:
    """Return the lowercase SHA-256 digest of :func:`canonicalize_url`."""

    canonical = canonicalize_url(url)
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_url_hash(url: str) -> str:
    """Return the 64-character lowercase SHA-256 canonical URL digest.

    This named helper mirrors the ``canonical_url_hash`` field used by the
    evidence models while keeping canonicalization in one place.
    """

    return stable_external_id(url)

