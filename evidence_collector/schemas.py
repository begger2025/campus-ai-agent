"""Validated request and response primitives for future collector APIs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .config import SUPPORTED_PROVIDER_IDS


SOURCE_TYPES = ("web", "news", "official", "academic", "social", "other")
RUN_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
QUERY_STATUSES = ("pending", "running", "completed", "failed")
VERIFICATION_STATUSES = ("pending", "verified", "rejected", "needs_review", "failed")
REVIEW_STATUSES = ("pending", "approved", "rejected", "needs_review")
DELIVERY_STATUSES = ("pending", "delivered", "failed")
SCOPE_DECISIONS = ("in_scope", "out_of_scope", "needs_review")


class SearchHit(BaseModel):
    """A provider-returned web hit with a usable evidence excerpt."""

    url: HttpUrl
    quote: str = Field(min_length=1)
    title: Optional[str] = None
    source_type: Literal["web", "news", "official", "academic", "social", "other"] = "web"

    @field_validator("quote")
    @classmethod
    def quote_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("quote must not be blank")
        return cleaned


class SearchRequest(BaseModel):
    """A bounded request to one configured search provider."""

    query: str = Field(min_length=1, max_length=2_000)
    provider: Literal["deepseek", "glm", "kimi", "doubao", "qwen"]
    model: Optional[str] = Field(default=None, max_length=128)
    max_results: int = Field(default=10, ge=1, le=50)
    prompt_version: str = Field(default="v1", min_length=1, max_length=64)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be blank")
        return cleaned


class ScopeDecision(BaseModel):
    """The auditable scope classification for a candidate evidence item."""

    decision: Literal["in_scope", "out_of_scope", "needs_review"]
    reasons: list[str] = Field(default_factory=list)
    quality_score: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("reasons")
    @classmethod
    def reasons_must_not_include_blanks(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("reasons must not include blank values")
        return cleaned
