"""Administrator endpoints for AI web-search evidence collection and delivery.

The collector is the second data entrance for 舆情 data: when crawlers fail or a
platform blocks us, an admin runs a collection here, reviews the evidence, and
delivers the approved items into ``raw_posts`` — the same table the pipeline
consumes.  Every endpoint sits behind ``require_admin``; there is no second auth
scheme.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.admin_models import User
from backend.database import get_db
from backend.models_evidence import EvidenceItem, EvidenceQuery, EvidenceRun
from backend.schemas import ok
from backend.services.auth_service import require_admin
from backend.services.evidence.collector import EvidenceCollector
from backend.services.evidence.providers import create_provider_registry
from backend.services.evidence.review_delivery import deliver_batch, review_item, verify_item
from backend.services.evidence.schemas import (
    REVIEW_STATUSES,
    SCOPE_DECISIONS,
    VERIFICATION_STATUSES,
)

router = APIRouter(tags=["admin-evidence"])


def get_evidence_collector(db: Session = Depends(get_db)) -> EvidenceCollector:
    """Build a collector bound to the request session.

    Exposed as a dependency so tests can inject a provider-free collector and
    never touch the network.
    """

    return EvidenceCollector(db, create_provider_registry())


class RunCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    queries: list[str] = Field(min_length=1)
    provider_ids: list[str] | None = None

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("topic must not be blank")
        return cleaned

    @field_validator("queries")
    @classmethod
    def queries_must_not_be_blank(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value and value.strip()]
        if not cleaned:
            raise ValueError("at least one non-blank query is required")
        return cleaned


class ItemReviewPatch(BaseModel):
    status: Literal[REVIEW_STATUSES]  # type: ignore[valid-type]
    note: str | None = None


class ItemVerifyRequest(BaseModel):
    method: str = Field(min_length=1, max_length=64)
    status: Literal[VERIFICATION_STATUSES]  # type: ignore[valid-type]
    reasons: list[str] | None = None
    verification_version: str | None = Field(default=None, max_length=64)
    model_version: str | None = Field(default=None, max_length=128)
    conflict_reason: str | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _run_item(run: EvidenceRun, *, item_count: int = 0, query_count: int = 0) -> dict[str, Any]:
    return {
        "id": run.id,
        "topic": run.topic,
        "status": run.status,
        "creator": run.creator,
        "item_count": item_count,
        "query_count": query_count,
        "duration_ms": run.duration_ms,
        "usage_total_tokens": run.usage_total_tokens,
        "error": run.sanitized_error_summary,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
    }


def _query_item(query: EvidenceQuery) -> dict[str, Any]:
    return {
        "id": query.id,
        "provider": query.provider,
        "model": query.model,
        "status": query.status,
        "error": query.error,
        "query_text": query.query_text,
        "created_at": _iso(query.created_at),
        "completed_at": _iso(query.completed_at),
    }


def _item_row(item: EvidenceItem) -> dict[str, Any]:
    document = item.document
    return {
        "id": item.id,
        "run_id": item.run_id,
        "source_url": item.source_url,
        "canonical_url": item.canonical_url,
        "source_domain": item.source_domain,
        "source_type": item.source_type,
        "title": document.title if document is not None else None,
        "publisher": document.publisher if document is not None else None,
        "evidence_quote": item.evidence_quote,
        "retrieval_provider": item.retrieval_provider,
        "retrieval_model": item.retrieval_model,
        "scope_decision": item.scope_decision,
        "scope_reasons": item.scope_reasons,
        "verification_status": item.verification_status,
        "review_status": item.review_status,
        "reviewed_by": item.reviewed_by,
        "review_note": item.review_note,
        "quality_score": item.quality_score,
        "published_at": _iso(item.published_at),
        "retrieved_at": _iso(item.retrieved_at),
    }


def _counts(db: Session, model, run_ids: list[int]) -> dict[int, int]:
    """One grouped COUNT per relation, so listing N runs stays a fixed 3 queries."""

    if not run_ids:
        return {}
    rows = (
        db.query(model.run_id, func.count(model.id))
        .filter(model.run_id.in_(run_ids))
        .group_by(model.run_id)
        .all()
    )
    return {run_id: count for run_id, count in rows}


@router.post("/admin/evidence/runs")
async def create_evidence_run(
    payload: RunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    collector: EvidenceCollector = Depends(get_evidence_collector),
):
    """Start a collection run.

    ``EvidenceCollector.collect`` is async and ``collect_sync`` raises inside a
    running event loop by design, so this route is ``async def`` and awaits it.
    """

    try:
        run = await collector.collect(
            payload.topic,
            payload.queries,
            provider_ids=payload.provider_ids,
            creator=current_user.username,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(_run_item(run))


@router.get("/admin/evidence/runs")
def list_evidence_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(EvidenceRun)
    if status:
        query = query.filter(EvidenceRun.status == status)
    query = query.order_by(EvidenceRun.created_at.desc(), EvidenceRun.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    run_ids = [row.id for row in rows]
    item_counts = _counts(db, EvidenceItem, run_ids)
    query_counts = _counts(db, EvidenceQuery, run_ids)
    items = [
        _run_item(
            row,
            item_count=item_counts.get(row.id, 0),
            query_count=query_counts.get(row.id, 0),
        )
        for row in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/admin/evidence/runs/{run_id}")
def get_evidence_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    run = db.get(EvidenceRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="evidence run not found")

    queries = (
        db.query(EvidenceQuery)
        .filter(EvidenceQuery.run_id == run_id)
        .order_by(EvidenceQuery.id.asc())
        .all()
    )
    item_count = (
        db.query(func.count(EvidenceItem.id)).filter(EvidenceItem.run_id == run_id).scalar() or 0
    )
    detail = _run_item(run, item_count=item_count, query_count=len(queries))
    detail["queries"] = [_query_item(query) for query in queries]
    return ok(detail)


@router.get("/admin/evidence/items")
def list_evidence_items(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    run_id: int | None = None,
    scope_decision: str | None = None,
    verification_status: str | None = None,
    review_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    for value, allowed, label in (
        (scope_decision, SCOPE_DECISIONS, "scope_decision"),
        (verification_status, VERIFICATION_STATUSES, "verification_status"),
        (review_status, REVIEW_STATUSES, "review_status"),
    ):
        if value is not None and value not in allowed:
            raise HTTPException(status_code=400, detail=f"invalid {label}")

    query = db.query(EvidenceItem)
    if run_id is not None:
        query = query.filter(EvidenceItem.run_id == run_id)
    if scope_decision:
        query = query.filter(EvidenceItem.scope_decision == scope_decision)
    if verification_status:
        query = query.filter(EvidenceItem.verification_status == verification_status)
    if review_status:
        query = query.filter(EvidenceItem.review_status == review_status)
    query = query.order_by(EvidenceItem.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return ok(
        {
            "items": [_item_row(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.patch("/admin/evidence/items/{item_id}/review")
def review_evidence_item(
    item_id: int,
    payload: ItemReviewPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        item = review_item(
            db,
            item_id,
            reviewer=current_user.username,
            status=payload.status,
            note=payload.note,
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="evidence item not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(item)
    return ok(_item_row(item))


@router.post("/admin/evidence/items/{item_id}/verify")
def verify_evidence_item(
    item_id: int,
    payload: ItemVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        verify_item(
            db,
            item_id,
            method=payload.method,
            status=payload.status,
            reasons=payload.reasons,
            verification_version=payload.verification_version,
            model_version=payload.model_version,
            conflict_reason=payload.conflict_reason,
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="evidence item not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    item = db.get(EvidenceItem, item_id)
    return ok(_item_row(item))


@router.post("/admin/evidence/runs/{run_id}/deliver")
def deliver_evidence_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Deliver the run's approved evidence into ``raw_posts``.

    Only items that are in_scope AND verified AND approved are delivered — this
    endpoint approves the *batch*, it never auto-approves items, so the human
    review gate cannot be bypassed from the API.
    """

    try:
        result = deliver_batch(db, run_id, approver=current_user.username)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="evidence run not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return ok(result)
