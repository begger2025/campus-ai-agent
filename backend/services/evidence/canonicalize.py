"""Canonical URL and stable external identifier helpers.

The functions in this module are deliberately pure: they do not resolve URLs
or make network requests.  Tracking query parameters are removed and the
remaining meaningful parameters are sorted so that the same page always yields
the same canonical form, whichever provider surfaced it.
"""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_TRACKING_KEYS = frozenset({"spm", "from"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonicalize_url(url: str) -> str:
    """Return a deterministic canonical representation of an HTTP(S) URL.

    Host names and schemes are lower-cased, fragments are discarded, and
    common tracking parameters (``utm_*``, ``spm`` and ``from``) are removed.
    An empty path becomes ``/`` and the scheme's default port (80 for http,
    443 for https) is dropped, so ``https://host`` , ``https://host/`` and
    ``https://host:443/`` share one canonical form.

    A trailing slash on a *non-empty* path is stripped, so ``/notice/1/`` and
    ``/notice/1`` are the same document; providers return the same article both
    ways and two canonical forms would store — and later double-count — it
    twice.  The root path stays ``/``: ``https://host/`` never becomes
    ``https://host``.

    Meaningful query parameters are sorted by ``(key, value)``; different
    providers return the same article with the parameters in different orders
    and an order-sensitive canonical form would store that page twice.
    Duplicate keys are all retained.  Empty, malformed, credential-bearing,
    and non-HTTP(S) URLs raise :class:`ValueError`.
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
    # The scheme's default port carries no information: ``https://host/a`` and
    # ``https://host:443/a`` are the same page and must dedupe to one row.
    if port is None or port == _DEFAULT_PORTS[scheme]:
        netloc = host_for_netloc
    else:
        netloc = f"{host_for_netloc}:{port}"

    meaningful_query: list[tuple[str, str]] = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key.startswith("utm_") or normalized_key in _TRACKING_KEYS:
            continue
        meaningful_query.append((key, query_value))

    # Sort so that ``?b=1&c=2`` and ``?c=2&b=1`` canonicalize identically.
    query = urlencode(sorted(meaningful_query), doseq=True)
    # ``/notice/1/`` and ``/notice/1`` are one article: providers return it both
    # ways and two canonical forms would mean two evidence_documents rows, i.e.
    # the article counted twice downstream.  ``or "/"`` keeps the site root a
    # ``/`` — both an empty path and a bare ``/`` land on the same hash, and
    # ``https://host`` never degrades into a hostname without a path.
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


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

