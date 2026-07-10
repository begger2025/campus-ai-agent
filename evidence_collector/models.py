"""SQLAlchemy models owned exclusively by the evidence collector."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for audit fields."""

    return datetime.now(timezone.utc)


class EvidenceRun(Base):
    __tablename__ = "evidence_runs"
    __table_args__ = (Index("ix_evidence_runs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    creator: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    time_window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    time_window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    duration_ms: Mapped[Optional[int]] = mapped_column()
    usage_input_tokens: Mapped[Optional[int]] = mapped_column()
    usage_output_tokens: Mapped[Optional[int]] = mapped_column()
    usage_total_tokens: Mapped[Optional[int]] = mapped_column()
    sanitized_error_summary: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    queries: Mapped[list["EvidenceQuery"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    items: Mapped[list["EvidenceItem"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    delivery_batches: Mapped[list["EvidenceDeliveryBatch"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvidenceQuery(Base):
    __tablename__ = "evidence_queries"
    __table_args__ = (Index("ix_evidence_queries_run_status", "run_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evidence_runs.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    run: Mapped[EvidenceRun] = relationship(back_populates="queries")
    documents: Mapped[list["EvidenceDocument"]] = relationship(back_populates="query")


class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"
    __table_args__ = (
        UniqueConstraint("source_type", "canonical_url", name="uq_evidence_documents_source_canonical"),
        Index("ix_evidence_documents_domain_fetched", "domain", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[Optional[int]] = mapped_column(ForeignKey("evidence_queries.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    document_type: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[Optional[str]] = mapped_column(Text)
    publisher: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    query: Mapped[Optional[EvidenceQuery]] = relationship(back_populates="documents")
    items: Mapped[list["EvidenceItem"]] = relationship(back_populates="document")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        Index("ix_evidence_items_run_review", "run_id", "review_status"),
        Index("ix_evidence_items_verifier_status", "verifier_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evidence_runs.id"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("evidence_documents.id"), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    retrieval_model: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_decision: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    scope_reasons: Mapped[Optional[str]] = mapped_column(Text)
    verifier_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255))
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    run: Mapped[EvidenceRun] = relationship(back_populates="items")
    document: Mapped[EvidenceDocument] = relationship(back_populates="items")
    verifications: Mapped[list["EvidenceVerification"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class EvidenceVerification(Base):
    __tablename__ = "evidence_verifications"
    __table_args__ = (Index("ix_evidence_verifications_item_status", "item_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("evidence_items.id"), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reasons: Mapped[Optional[str]] = mapped_column(Text)
    conflict_reason: Mapped[Optional[str]] = mapped_column(Text)
    verification_version: Mapped[Optional[str]] = mapped_column(String(64))
    model_version: Mapped[Optional[str]] = mapped_column(String(128))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    item: Mapped[EvidenceItem] = relationship(back_populates="verifications")


class EvidenceDeliveryBatch(Base):
    __tablename__ = "evidence_delivery_batches"
    __table_args__ = (Index("ix_evidence_delivery_batches_run_status", "run_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evidence_runs.id"), nullable=False, index=True)
    raw_post_id: Mapped[Optional[int]] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[Optional[str]] = mapped_column(Text)
    approver: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    run: Mapped[EvidenceRun] = relationship(back_populates="delivery_batches")
