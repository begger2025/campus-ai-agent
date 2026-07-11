"""Evidence collection: provider config, schemas, and deterministic helpers.

This package owns only tables whose names begin with ``evidence_``; they are
mapped on the backend's single ``backend.database.Base``.
"""

from .canonicalize import canonical_url_hash, canonicalize_url, stable_external_id
from .config import SUPPORTED_PROVIDER_IDS, CollectorSettings, load_settings
from .http_transport import (
    HttpTransportResponseError,
    HttpTransportUnavailableError,
    OpenAICompatibleTransport,
    build_http_transports,
    parse_citation_response,
)
from .review_delivery import (
    build_delivery_payload,
    create_delivery_batch,
    mark_delivery,
    review_item,
    verify_item,
)
from .scope_policy import ScopeDecision, assess_scope

__all__ = [
    "SUPPORTED_PROVIDER_IDS",
    "CollectorSettings",
    "load_settings",
    "ScopeDecision",
    "assess_scope",
    "canonical_url_hash",
    "canonicalize_url",
    "stable_external_id",
    "HttpTransportResponseError",
    "HttpTransportUnavailableError",
    "OpenAICompatibleTransport",
    "build_http_transports",
    "parse_citation_response",
    "build_delivery_payload",
    "create_delivery_batch",
    "mark_delivery",
    "review_item",
    "verify_item",
]
