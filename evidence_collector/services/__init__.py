"""Small, deterministic helpers used by the evidence collector."""

from .canonicalize import canonical_url_hash, canonicalize_url, stable_external_id
from .scope_policy import ScopeDecision, assess_scope

__all__ = [
    "ScopeDecision",
    "assess_scope",
    "canonical_url_hash",
    "canonicalize_url",
    "stable_external_id",
]
