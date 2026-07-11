"""Offline-testable retrieval and evidence persistence pipeline.

The collector is intentionally a small orchestration layer.  Provider adapters
are injected, URL canonicalization and SYSU scope assessment are pure helpers,
and the SQLAlchemy session is supplied by the caller.  Consequently importing
or testing this module never starts a network client and never touches tables
outside the ``evidence_*`` metadata owned by this package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models_evidence import (
    EvidenceDocument,
    EvidenceItem,
    EvidenceQuery,
    EvidenceRun,
    utcnow,
)
from backend.services.evidence.canonicalize import canonical_url_hash, canonicalize_url
from backend.services.evidence.providers import (
    ProviderRegistry,
    SearchHit,
    SearchRequest,
    normalize_hits,
)
from backend.services.evidence.scope_policy import ScopeDecision, assess_scope


logger = logging.getLogger(__name__)


SYSU_QUERY_CONTEXT = (
    "中山大学（Sun Yat-sen University，SYSU）校园公共信息与舆情；"
    "仅返回明确涉及中山大学的可引用公开信息。"
)


def sanitize_error(error: BaseException | str, *, limit: int = 1024) -> str:
    """Return a bounded error suitable for audit columns.

    Provider exceptions are not trusted input: they may contain API keys,
    bearer tokens, or request headers.  Keep the exception class for debugging,
    redact common credential-shaped values, collapse whitespace, and truncate
    before persisting the result.
    """

    if isinstance(error, BaseException):
        message = str(error)
        prefix = type(error).__name__
    else:
        message = str(error)
        prefix = "Error"
    message = re.sub(r"\s+", " ", message).strip()
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer|token|secret|password)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(
        r"(?i)\b(?:authorization|bearer)\s+(?:bearer\s+)?[^\s,;]+",
        "authorization=<redacted>",
        message,
    )
    message = re.sub(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|token|secret|password|key)\s+[^\s,;]+",
        "credential=<redacted>",
        message,
    )
    message = re.sub(
        r"(?i)((?:api[_-]?key|access[_-]?token|token|secret|password|key)=)[^&\s,;]+",
        r"\1<redacted>",
        message,
    )
    message = re.sub(r"(?i)\b(?:sk|ak|key)-[a-z0-9_-]{8,}\b", "<redacted>", message)
    rendered = f"{prefix}: {message or '<no detail>'}"
    return rendered[:limit]


def _metadata(hit: SearchHit, key: str) -> Any:
    value = hit.metadata
    if isinstance(value, Mapping):
        return value.get(key)
    # SearchHit permits extra transport fields; retain compatibility with
    # providers that put provenance at the top level instead of metadata.
    dumped = hit.model_dump()
    return dumped.get(key)


def _published_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _provider_ids(registry: ProviderRegistry, provider_ids: Iterable[str] | None) -> tuple[str, ...]:
    if provider_ids is not None:
        selected = tuple(dict.fromkeys(str(pid).strip().lower() for pid in provider_ids if str(pid).strip()))
    else:
        selected = tuple(registry.enabled_provider_ids)
        # Static/fake providers used by tests need no credentials and therefore
        # do not expose the adapter ``enabled`` property.
        if not selected:
            selected = tuple(
                pid
                for pid, provider in registry.providers.items()
                if getattr(provider, "enabled", True)
            )
    if not selected:
        raise ValueError("at least one provider must be configured or selected")
    return selected


def _query_specs(
    queries: Sequence[Any] | Mapping[str, Any] | str,
    provider_ids: tuple[str, ...],
    *,
    default_max_results: int,
    default_prompt_version: str,
) -> list[dict[str, Any]]:
    """Normalize convenient query input forms into provider request specs."""

    if isinstance(queries, str):
        values: Sequence[Any] = [queries]
    elif isinstance(queries, Mapping):
        # Mapping provider -> query or provider -> [queries] is convenient for
        # callers that want different prompts per provider.
        values = [
            {"provider": provider, "query": query}
            for provider, raw in queries.items()
            for query in (raw if isinstance(raw, (list, tuple)) else [raw])
        ]
    else:
        values = queries

    specs: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, SearchRequest):
            specs.append(
                {
                    "provider": value.provider,
                    "query": value.query,
                    "model": value.model,
                    "max_results": value.max_results,
                    "prompt_version": value.prompt_version,
                }
            )
            continue
        if isinstance(value, Mapping):
            raw_query = value.get("query", value.get("query_text"))
            selected = value.get("provider", value.get("provider_id"))
            selected_providers = (
                [selected]
                if selected is not None
                else list(provider_ids)
            )
            if raw_query is None:
                raise ValueError("each query mapping requires query or query_text")
            for provider in selected_providers:
                specs.append(
                    {
                        "provider": str(provider).strip().lower(),
                        "query": str(raw_query).strip(),
                        "model": value.get("model"),
                        "max_results": value.get("max_results", default_max_results),
                        "prompt_version": value.get("prompt_version", default_prompt_version),
                    }
                )
            continue
        text = str(value).strip()
        if not text:
            raise ValueError("queries must not contain blank values")
        for provider in provider_ids:
            specs.append(
                {
                    "provider": provider,
                    "query": text,
                    "model": None,
                    "max_results": default_max_results,
                    "prompt_version": default_prompt_version,
                }
            )
    if not specs:
        raise ValueError("at least one query is required")
    for spec in specs:
        if not spec["query"]:
            raise ValueError("queries must not contain blank values")
    return specs


class EvidenceCollector:
    """Run provider searches and persist normalized evidence records.

    ``session_or_factory`` accepts either a SQLAlchemy :class:`Session` or a
    zero-argument session factory.  The collector owns a factory-created
    session for the duration of one run and leaves a caller-supplied session
    open.  ``collect`` is asynchronous because provider adapters are async;
    ``collect_sync`` is a convenience for scripts and unit tests.
    """

    def __init__(
        self,
        session_or_factory: Session | Callable[[], Session],
        provider_registry: ProviderRegistry,
        *,
        scope_assessor: Callable[[str | None, str | None, str | None, str | None], ScopeDecision] = assess_scope,
        query_context: str = SYSU_QUERY_CONTEXT,
    ) -> None:
        self._session_or_factory = session_or_factory
        self.registry = provider_registry
        self.scope_assessor = scope_assessor
        self.query_context = query_context.strip()

    async def _search_one(
        self,
        spec: Mapping[str, Any],
        *,
        default_max_results: int,
        default_prompt_version: str,
    ) -> tuple[SearchRequest | None, list[SearchHit], Exception | None]:
        """Resolve one provider and run its query without touching the Session.

        Returned instead of raised so that ``asyncio.gather`` fan-out keeps the
        long-standing invariant that one failing provider never fails the
        others.  The exception is handed back for the caller to sanitize into
        the query's audit row.
        """

        provider_id = str(spec.get("provider", "")).strip().lower()
        query_text = str(spec.get("query", "")).strip()
        prompt_value = str(spec.get("prompt_version", default_prompt_version)).strip()
        try:
            # Resolve and validate inside the query boundary so a bad provider
            # or request is retained as an auditable failure.
            provider = self.registry.get(provider_id)
            request = SearchRequest(
                provider=provider_id,
                model=spec.get("model"),
                query=f"{self.query_context} 原始检索词：{query_text}",
                max_results=int(spec.get("max_results", default_max_results)),
                prompt_version=prompt_value,
            )
            raw_hits = await provider.search(request)
            hits = normalize_hits(raw_hits, provider_id=provider_id, model=request.model)
            return request, list(hits), None
        except Exception as error:  # provider errors are audit data, not fatal
            return None, [], error

    def _document_for(
        self,
        session: Session,
        *,
        digest: str,
        build: Callable[[], EvidenceDocument],
    ) -> EvidenceDocument | None:
        """Return the document for ``digest``, inserting it if we get there first.

        Two collectors working overlapping topics can insert the same canonical
        URL at the same time, so a plain SELECT-then-INSERT loses the race and
        the resulting ``IntegrityError`` would poison the whole session.  The
        insert runs inside a SAVEPOINT: on conflict we roll back only that
        savepoint and re-read the row the winner just committed.
        """

        existing = (
            session.query(EvidenceDocument)
            .filter(EvidenceDocument.canonical_url_hash == digest)
            .one_or_none()
        )
        if existing is not None:
            return existing

        document = build()
        try:
            with session.begin_nested():
                session.add(document)
                session.flush()
            return document
        except IntegrityError:
            existing = (
                session.query(EvidenceDocument)
                .filter(EvidenceDocument.canonical_url_hash == digest)
                .one_or_none()
            )
            if existing is None:
                logger.warning(
                    "evidence document %s conflicted on insert but could not be "
                    "re-read; skipping this hit",
                    digest,
                )
            return existing

    def _session(self) -> tuple[Session, bool]:
        if isinstance(self._session_or_factory, Session) or hasattr(self._session_or_factory, "add"):
            return self._session_or_factory, False  # type: ignore[return-value]
        session = self._session_or_factory()  # type: ignore[operator]
        if not hasattr(session, "add"):
            raise TypeError("session factory must return a SQLAlchemy Session")
        return session, True

    async def collect(
        self,
        topic: str,
        queries: Sequence[Any] | Mapping[str, Any] | str,
        *,
        provider_ids: Iterable[str] | None = None,
        creator: str | None = None,
        max_results: int = 10,
        prompt_version: str = "v1",
        time_window_start: datetime | None = None,
        time_window_end: datetime | None = None,
    ) -> EvidenceRun:
        """Execute one run and return its committed ``EvidenceRun`` row."""

        topic = topic.strip() if isinstance(topic, str) else ""
        if not topic:
            raise ValueError("topic must not be blank")
        if not 1 <= max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        if not prompt_version.strip():
            raise ValueError("prompt_version must not be blank")

        selected_providers = _provider_ids(self.registry, provider_ids)
        specs = _query_specs(
            queries,
            selected_providers,
            default_max_results=max_results,
            default_prompt_version=prompt_version.strip(),
        )
        session, owns_session = self._session()
        started_clock = time.monotonic()
        run = EvidenceRun(
            topic=topic,
            creator=creator,
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            status="running",
            started_at=utcnow(),
        )
        session.add(run)
        session.flush()
        failures = 0
        seen_hashes: set[str] = set()
        try:
            # Every spec gets its own auditable query row up front.  They are
            # created before the fan-out because the Session is not task-safe:
            # only the network calls run concurrently, all ORM writes stay on
            # this single sequential path.
            query_rows: list[EvidenceQuery] = []
            for spec in specs:
                # Keep audit columns valid even when request construction is
                # intentionally going to fail (for example, an empty or
                # overlong prompt version).
                prompt_value = str(spec.get("prompt_version", prompt_version)).strip()
                query_row = EvidenceQuery(
                    run_id=run.id,
                    provider=str(spec.get("provider", "")).strip().lower(),
                    model=(str(spec.get("model")).strip()[:128] if spec.get("model") else None),
                    prompt_version=prompt_value[:64] or "invalid",
                    query_text=str(spec.get("query", "")).strip(),
                    status="running",
                )
                session.add(query_row)
                query_rows.append(query_row)
            session.flush()

            # Providers are independent web-search calls; running them serially
            # cost minutes per run.  Failures are returned, not raised, so one
            # bad provider still cannot fail the others.
            results = await asyncio.gather(
                *(
                    self._search_one(
                        spec,
                        default_max_results=max_results,
                        default_prompt_version=prompt_version,
                    )
                    for spec in specs
                )
            )

            # Persist sequentially in spec order: the per-run seen_hashes dedup
            # stays deterministic even though the hits arrived concurrently.
            for query_row, (request, hits, error) in zip(query_rows, results):
                if error is not None:
                    failures += 1
                    query_row.status = "failed"
                    query_row.error = sanitize_error(error)
                    query_row.completed_at = utcnow()
                    continue
                assert request is not None  # a successful search always has one
                provider_id = query_row.provider
                for hit in hits:
                    try:
                        canonical = canonicalize_url(str(hit.url))
                        digest = canonical_url_hash(canonical)
                    except (TypeError, ValueError):
                        # Provider normalization normally catches this;
                        # keep malformed transport output out of the DB.
                        continue
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    domain = urlsplit(canonical).hostname
                    source_type = hit.source_type
                    title = hit.title
                    quote = hit.quote.strip()
                    scope = self.scope_assessor(source_type, domain, title, quote)
                    reasons = json.dumps(scope.reasons, ensure_ascii=False)
                    document = self._document_for(
                        session,
                        digest=digest,
                        build=lambda: EvidenceDocument(
                            query_id=query_row.id,
                            source_type=source_type,
                            source_url=str(hit.url),
                            canonical_url=canonical,
                            canonical_url_hash=digest,
                            domain=domain,
                            document_type=_metadata(hit, "document_type"),
                            title=title,
                            publisher=_metadata(hit, "publisher"),
                            published_at=_published_at(_metadata(hit, "published_at")),
                            evidence_quote=quote,
                        ),
                    )
                    if document is None:
                        continue
                    item = EvidenceItem(
                        run_id=run.id,
                        document_id=document.id,
                        source_url=str(hit.url),
                        canonical_url=canonical,
                        canonical_url_hash=digest,
                        source_domain=domain,
                        source_type=source_type,
                        published_at=document.published_at,
                        evidence_quote=quote,
                        retrieval_provider=provider_id,
                        retrieval_model=hit.model or request.model,
                        prompt_version=request.prompt_version,
                        scope_decision=scope.decision,
                        scope_reasons=reasons,
                        # Not dead: scope_assessor is injectable and
                        # schemas.ScopeDecision carries a quality_score.  The
                        # default scope_policy.ScopeDecision has none, so this
                        # is None for the built-in policy.
                        quality_score=getattr(scope, "quality_score", None),
                        verification_status="pending",
                        review_status="pending",
                    )
                    session.add(item)
                query_row.status = "completed"
                query_row.completed_at = utcnow()
            session.flush()
            if not failures:
                run.status = "completed"
            elif failures == len(specs):
                run.status = "failed"
            else:
                # Four of five providers succeeding is not a failed run; the
                # partial state keeps the surviving evidence usable while still
                # flagging the gap to reviewers.
                run.status = "partial"
            run.sanitized_error_summary = (
                f"{failures} of {len(specs)} provider queries failed" if failures else None
            )
            run.completed_at = utcnow()
            run.duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
            session.commit()
            # ``sessionmaker`` defaults to expire_on_commit=True.  Refreshing
            # before returning keeps the committed run readable even when a
            # factory-created session is closed in the finally block.
            session.refresh(run)
            return run
        except Exception as error:
            session.rollback()
            # A database failure may have rolled back the run row itself.  Do
            # not attempt a second write on a caller-owned broken transaction.
            if owns_session:
                session.close()
            raise RuntimeError(sanitize_error(error)) from error
        finally:
            if owns_session:
                session.close()

    async def run(self, topic: str, queries: Sequence[Any] | Mapping[str, Any] | str, **kwargs: Any) -> EvidenceRun:
        """Alias for :meth:`collect` used by command-line callers."""

        return await self.collect(topic, queries, **kwargs)

    def collect_sync(self, topic: str, queries: Sequence[Any] | Mapping[str, Any] | str, **kwargs: Any) -> EvidenceRun:
        """Synchronous wrapper; call it outside an already-running loop."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.collect(topic, queries, **kwargs))
        raise RuntimeError("collect_sync cannot be called from a running event loop; await collect instead")

    run_sync = collect_sync


__all__ = ["EvidenceCollector", "SYSU_QUERY_CONTEXT", "sanitize_error"]
