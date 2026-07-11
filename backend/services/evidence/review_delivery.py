"""Human review, verification, and delivery boundaries for evidence.

This module is deliberately persistence-only: it never calls a provider or a
network service.  Callers decide when to commit the supplied SQLAlchemy
session; failed validation is raised before a flush so the caller can roll
back the surrounding transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import json
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import RawPost
from backend.models_evidence import (
    EvidenceDeliveryBatch,
    EvidenceItem,
    EvidenceRun,
    EvidenceVerification,
    utcnow,
)
from backend.services.evidence.schemas import (
    DELIVERY_STATUSES,
    REVIEW_STATUSES,
    VERIFICATION_STATUSES,
)
from backend.services.evidence.collector import sanitize_error


logger = logging.getLogger(__name__)


_TERMINAL_VERIFICATION_STATUSES = frozenset({"verified", "rejected", "failed"})
_MARKABLE_DELIVERY_STATUSES = frozenset({"delivered", "failed"})

# Evidence enters the 舆情 pipeline as a first-class platform of its own: it is
# not crawled from a MediaCrawler native table, so it needs a platform code that
# no crawler owns.  ``raw_posts`` is UNIQUE on (platform, external_id), and the
# evidence canonical URL digest is already a stable per-URL identity, so using it
# as ``external_id`` makes redelivery idempotent without a separate ledger.
DELIVERY_PLATFORM = "web"
DELIVERY_SOURCE_TABLE = "evidence_items"


def _text(value: Any, field: str, *, required: bool = True, limit: int | None = None) -> str | None:
    """Normalize human-entered text without allowing credentials in errors."""

    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{field} must not be blank")
    if limit is not None and len(cleaned) > limit:
        raise ValueError(f"{field} is too long")
    return cleaned or None


def _status(value: str, allowed: Iterable[str], field: str) -> str:
    cleaned = _text(value, field)
    assert cleaned is not None
    normalized = cleaned.lower()
    if normalized not in set(allowed):
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _reasons(value: str | Iterable[str] | None) -> str | None:
    """Store reasons as bounded JSON text, preserving audit readability."""

    if value is None:
        return None
    if isinstance(value, str):
        cleaned = _text(value, "reasons", required=False, limit=8_000)
        return cleaned
    try:
        cleaned = [
            _text(reason, "reason", limit=2_000)
            for reason in value
        ]
    except TypeError as exc:
        raise ValueError("reasons must be text or an iterable of text") from exc
    values = [reason for reason in cleaned if reason]
    if not values:
        return None
    return json.dumps(values, ensure_ascii=False)


def _item(session: Session, item_id: int) -> EvidenceItem:
    item = session.get(EvidenceItem, item_id)
    if item is None:
        raise LookupError("evidence item was not found")
    return item


def verify_item(
    session: Session,
    item_id: int,
    method: str,
    status: str,
    reasons: str | Iterable[str] | None = None,
    verification_version: str | None = None,
    model_version: str | None = None,
    conflict_reason: str | None = None,
) -> EvidenceVerification:
    """Append a verification record and synchronize the item's status.

    Verification records are append-only audit facts.  The latest supplied
    status is reflected on ``EvidenceItem`` for efficient review queries.
    The function does not commit the caller's transaction.
    """

    item = _item(session, item_id)
    normalized_status = _status(status, VERIFICATION_STATUSES, "status")
    normalized_method = _text(method, "method", limit=64)
    assert normalized_method is not None
    verification = EvidenceVerification(
        item_id=item.id,
        method=normalized_method,
        status=normalized_status,
        reasons=_reasons(reasons),
        conflict_reason=_text(conflict_reason, "conflict_reason", required=False, limit=8_000),
        verification_version=_text(
            verification_version, "verification_version", required=False, limit=64
        ),
        model_version=_text(model_version, "model_version", required=False, limit=128),
        verified_at=utcnow() if normalized_status in _TERMINAL_VERIFICATION_STATUSES else None,
    )
    item.verification_status = normalized_status
    item.updated_at = utcnow()
    session.add(verification)
    session.flush()
    return verification


def review_item(
    session: Session,
    item_id: int,
    reviewer: str,
    status: str,
    note: str | None = None,
) -> EvidenceItem:
    """Set a human review status, enforcing approval prerequisites."""

    item = _item(session, item_id)
    normalized_status = _status(status, REVIEW_STATUSES, "status")
    normalized_reviewer = _text(reviewer, "reviewer", limit=255)
    assert normalized_reviewer is not None
    if normalized_status == "approved":
        if item.scope_decision != "in_scope":
            raise ValueError("approved review requires an in_scope item")
        if item.verification_status != "verified":
            raise ValueError("approved review requires verified evidence")
    item.review_status = normalized_status
    item.reviewed_by = normalized_reviewer
    item.review_note = _text(note, "note", required=False, limit=8_000)
    item.updated_at = utcnow()
    session.flush()
    return item


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def eligible_items(session: Session, run_id: int) -> list[EvidenceItem]:
    """Return the run's deliverable evidence: in-scope AND verified AND approved.

    This is the single delivery gate.  ``build_delivery_payload`` and
    ``deliver_batch`` both go through it so the export view and the rows that
    actually reach ``raw_posts`` can never drift apart.
    """

    if session.get(EvidenceRun, run_id) is None:
        raise LookupError("evidence run was not found")
    return (
        session.query(EvidenceItem)
        .filter(
            EvidenceItem.run_id == run_id,
            EvidenceItem.review_status == "approved",
            EvidenceItem.scope_decision == "in_scope",
            EvidenceItem.verification_status == "verified",
        )
        .order_by(EvidenceItem.id)
        .all()
    )


def build_delivery_payload(session: Session, run_id: int) -> dict[str, Any]:
    """Return only reviewed, in-scope, verified evidence for a run.

    The payload intentionally omits database credentials, internal errors,
    reviewer identities, prompts, and raw provider responses.
    """

    eligible = eligible_items(session, run_id)
    run = session.get(EvidenceRun, run_id)
    assert run is not None  # eligible_items raises LookupError when it is missing
    items: list[dict[str, Any]] = []
    for item in eligible:
        document = item.document
        items.append(
            {
                "url": item.canonical_url,
                "canonical_url_hash": item.canonical_url_hash,
                "title": document.title if document is not None else None,
                "publisher": document.publisher if document is not None else None,
                "published_at": _iso(item.published_at or (document.published_at if document else None)),
                "quote": item.evidence_quote,
                "provider": item.retrieval_provider,
                "model": item.retrieval_model,
            }
        )
    return {"run_id": run.id, "topic": run.topic, "items": items}


def create_delivery_batch(
    session: Session,
    run_id: int,
    approver: str,
    *,
    raw_post_id: int | None = None,
) -> EvidenceDeliveryBatch:
    """Create a pending delivery batch containing only eligible evidence."""

    if session.get(EvidenceRun, run_id) is None:
        raise LookupError("evidence run was not found")
    normalized_approver = _text(approver, "approver", limit=255)
    assert normalized_approver is not None
    payload = build_delivery_payload(session, run_id)
    if not payload["items"]:
        raise ValueError("no approved in-scope verified evidence is available for delivery")
    batch = EvidenceDeliveryBatch(
        run_id=run_id,
        raw_post_id=raw_post_id,
        status="pending",
        approver=normalized_approver,
        approved_at=utcnow(),
    )
    session.add(batch)
    session.flush()
    return batch


def mark_delivery(
    session: Session,
    batch_id: int,
    status: str,
    *,
    error: str | None = None,
) -> EvidenceDeliveryBatch:
    """Finalize a pending batch, rejecting duplicate or unsafe transitions."""

    batch = session.get(EvidenceDeliveryBatch, batch_id)
    if batch is None:
        raise LookupError("delivery batch was not found")
    normalized_status = _status(status, _MARKABLE_DELIVERY_STATUSES, "status")
    if batch.status != "pending":
        raise ValueError("only pending delivery batches can be finalized")
    if normalized_status == "delivered":
        if not batch.approver:
            raise ValueError("delivered batch requires an approver")
        if not build_delivery_payload(session, batch.run_id)["items"]:
            raise ValueError("cannot deliver a batch with no approved evidence")
        batch.error = None
        batch.delivered_at = utcnow()
    else:
        batch.error = sanitize_error(error or "delivery failed")
        batch.delivered_at = None
    batch.status = normalized_status
    session.flush()
    return batch


def _naive_utc(value: datetime | None) -> datetime | None:
    """Drop the tzinfo after normalizing to UTC.

    Evidence timestamps are timezone-aware; ``raw_posts`` stores naive DateTime
    (MySQL DATETIME carries no offset).  Converting first, then dropping tzinfo,
    keeps the instant correct instead of silently reinterpreting it as local time.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _clip(value: str | None, limit: int) -> str:
    """Fit a value into its column without raising on over-long provider text."""

    return (value or "").strip()[:limit]


def _raw_post_for(session: Session, item: EvidenceItem, topic: str) -> tuple[RawPost, bool]:
    """Return ``(raw_post, created)`` for one evidence item, inserting it once.

    Redelivery of a run, and two runs that independently found the same URL, both
    land on the same ``(platform, external_id)``.  A plain SELECT-then-INSERT
    loses that race and the resulting ``IntegrityError`` would poison the whole
    session, so the insert runs inside a SAVEPOINT: on conflict we roll back only
    that savepoint and re-read the row the winner committed.  This mirrors
    ``collector._document_for``.
    """

    digest = item.canonical_url_hash
    existing = (
        session.query(RawPost)
        .filter(RawPost.platform == DELIVERY_PLATFORM, RawPost.external_id == digest)
        .one_or_none()
    )
    if existing is not None:
        return existing, False

    document = item.document
    domain = item.source_domain or ""
    # title is NOT NULL: fall back to the domain, then to the canonical URL, so a
    # provider that omitted a title can never drop an approved item.
    title = _clip(
        (document.title if document is not None else None) or domain or item.canonical_url,
        500,
    )
    publisher = (document.publisher if document is not None else None) or domain
    post = RawPost(
        platform=DELIVERY_PLATFORM,
        external_id=digest,
        source_table=DELIVERY_SOURCE_TABLE,
        source_raw_id=str(item.id),
        source_keyword=_clip(topic, 255),
        title=title,
        content=item.evidence_quote or "",
        author=_clip(publisher, 100),
        publish_time=_naive_utc(item.published_at),
        url=_clip(item.canonical_url, 500),
        raw_url=_clip(item.canonical_url, 500),
        crawl_time=_naive_utc(item.retrieved_at),
    )
    try:
        with session.begin_nested():
            session.add(post)
            session.flush()
        return post, True
    except IntegrityError:
        existing = (
            session.query(RawPost)
            .filter(RawPost.platform == DELIVERY_PLATFORM, RawPost.external_id == digest)
            .one_or_none()
        )
        if existing is None:
            logger.warning(
                "raw_post for evidence digest %s conflicted on insert but could "
                "not be re-read",
                digest,
            )
            raise
        return existing, False


def deliver_batch(session: Session, run_id: int, approver: str) -> dict[str, Any]:
    """Insert a run's eligible evidence into ``raw_posts`` and record the batches.

    This is the delivery last mile: ``raw_posts`` is the table the 舆情 pipeline
    consumes, so evidence only becomes a second data entrance once it lands here.
    One :class:`EvidenceDeliveryBatch` is written per delivered row — the model
    carries a single ``raw_post_id`` FK, so a batch is the audit fact "this run's
    evidence became this raw post".

    Redelivery is idempotent: already-present rows are reported as ``existing``
    and no duplicate ``raw_posts`` row is written.  The caller commits.
    """

    items = eligible_items(session, run_id)
    if not items:
        raise ValueError("no approved in-scope verified evidence is available for delivery")
    run = session.get(EvidenceRun, run_id)
    assert run is not None
    normalized_approver = _text(approver, "approver", limit=255)
    assert normalized_approver is not None

    created = 0
    existing = 0
    batch_ids: list[int] = []
    raw_post_ids: list[int] = []
    for item in items:
        batch = EvidenceDeliveryBatch(
            run_id=run_id,
            status="pending",
            approver=normalized_approver,
            approved_at=utcnow(),
        )
        session.add(batch)
        session.flush()
        try:
            post, was_created = _raw_post_for(session, item, run.topic)
        except Exception as error:  # delivery failure is audit data, not a crash
            batch.status = "failed"
            batch.error = sanitize_error(error)
            batch.delivered_at = None
            session.flush()
            raise
        batch.raw_post_id = post.id
        batch.status = "delivered"
        batch.error = None
        batch.delivered_at = utcnow()
        session.flush()
        batch_ids.append(batch.id)
        raw_post_ids.append(post.id)
        if was_created:
            created += 1
        else:
            existing += 1

    return {
        "run_id": run_id,
        "created": created,
        "existing": existing,
        "delivered": created + existing,
        "batch_ids": batch_ids,
        "raw_post_ids": raw_post_ids,
    }


__all__ = [
    "DELIVERY_PLATFORM",
    "build_delivery_payload",
    "create_delivery_batch",
    "deliver_batch",
    "eligible_items",
    "mark_delivery",
    "review_item",
    "verify_item",
]
