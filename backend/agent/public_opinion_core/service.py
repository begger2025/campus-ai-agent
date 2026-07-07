"""Service entrypoint for the portable public opinion Agent core."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
import time
from typing import Any

from .adapter import processed_posts_to_notes
from .clustering import cluster_notes
from .memory import annotate_events_with_memory, build_snapshot
from .normalizer import clean_text, note_text
from .schemas import AgentRunLogPayload, AnalyzeRequest, AnalyzeResult, MemorySnapshot, OpinionNote
from .scoring import score_notes
from .semantic_clustering import cluster_notes_semantic, strip_social_noise
from .sentiment_risk import analyze_notes_sentiment_and_risk
from .visualization import build_visualization_payload


# (list[str]) -> list[list[float]]，由运行环境注入（如 app.services.embedding），核心不依赖模型库。
Embedder = Callable[[list[str]], list[list[float]]]

# (list[str]) -> list[str | None]，None 表示该条保留规则结果（如 app.services.sentiment_llm）。
SentimentClassifier = Callable[[list[str]], list[str | None]]

VALID_SENTIMENT_LABELS = {"positive", "negative", "neutral", "controversial"}


class PublicOpinionAgentService:
    """Analyze processed_posts-like rows without knowing their data source."""

    def analyze_from_rows(
        self,
        rows: Iterable[Mapping[str, Any] | Any],
        request: AnalyzeRequest | None = None,
        previous_snapshot: MemorySnapshot | None = None,
        embedder: Embedder | None = None,
        cluster_threshold: float | None = None,
        align_threshold: float | None = None,
        sentiment_classifier: SentimentClassifier | None = None,
    ) -> AnalyzeResult:
        request = request or AnalyzeRequest()
        started_perf = time.perf_counter()
        started_at = _utc_now_text()

        warnings: list[str] = []
        row_list = list(rows or [])
        notes = processed_posts_to_notes(row_list, warnings=warnings)
        adapted_count = len(notes)

        notes = self._filter_notes(notes, request)
        if request.limit:
            notes = notes[: request.limit]
        matched_count = len(notes)

        if not row_list:
            warnings.append("no input rows")
        elif matched_count == 0:
            warnings.append("no notes matched request filters")

        events = []
        centroids: dict[str, list[float]] = {}
        clustering_mode = "rules"
        sentiment_mode = "rules"
        sentiment_overridden = 0
        if notes:
            notes = score_notes(notes)
            notes = analyze_notes_sentiment_and_risk(notes)
            llm_sentiment = self._try_llm_sentiment(notes, sentiment_classifier, warnings)
            if llm_sentiment is not None:
                sentiment_mode, sentiment_overridden = "llm", llm_sentiment
            semantic = self._try_semantic_clustering(
                notes, embedder, previous_snapshot, cluster_threshold, align_threshold, warnings
            )
            if semantic is not None:
                events, centroids = semantic
                clustering_mode = "semantic"
            else:
                events = cluster_notes(notes)
        events = annotate_events_with_memory(events, previous_snapshot)

        finished_at = _utc_now_text()
        duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
        snapshot = build_snapshot(events, captured_at=finished_at, centroids=centroids)
        visualization = build_visualization_payload(notes, events)
        run_log = AgentRunLogPayload(
            agent_type="public_opinion",
            status="success",
            input_count=len(row_list),
            event_count=len(events),
            keyword=clean_text(request.keyword),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            warnings=list(warnings),
            extra={
                "adapted_count": adapted_count,
                "matched_count": matched_count,
                "platforms": list(request.platforms),
                "limit": request.limit,
                "trend_counts": dict(Counter(event.trend for event in events)),
                "risk_escalated_count": sum(1 for event in events if event.risk_escalated),
                "clustering_mode": clustering_mode,
                "sentiment_mode": sentiment_mode,
                "sentiment_overridden": sentiment_overridden,
            },
        )

        return AnalyzeResult(
            request=request,
            events=events,
            run_log=run_log,
            warnings=list(warnings),
            snapshot=snapshot,
            visualization=visualization,
        )

    def _try_llm_sentiment(
        self,
        notes: list[OpinionNote],
        classifier: SentimentClassifier | None,
        warnings: list[str],
    ) -> int | None:
        """Override note sentiments with LLM labels; None means rules-only.

        Returns the number of overridden notes. Per-item None labels keep the
        rules result for those notes; any structural failure keeps everything.
        """

        if classifier is None:
            return None
        try:
            labels = classifier([note_text(note) for note in notes])
            if labels is None or len(labels) != len(notes):
                raise ValueError("classifier returned wrong label count")
        except Exception as exc:
            warnings.append(f"llm sentiment unavailable, kept rules result: {type(exc).__name__}: {exc}")
            return None

        overridden = 0
        for note, label in zip(notes, labels):
            if isinstance(label, str) and label in VALID_SENTIMENT_LABELS:
                note.sentiment = label
                overridden += 1
        return overridden

    def _try_semantic_clustering(
        self,
        notes: list[OpinionNote],
        embedder: Embedder | None,
        previous_snapshot: MemorySnapshot | None,
        cluster_threshold: float | None,
        align_threshold: float | None,
        warnings: list[str],
    ) -> tuple[list, dict[str, list[float]]] | None:
        """Run semantic clustering if an embedder is supplied; None means fall back to rules."""

        if embedder is None:
            return None
        try:
            vectors = embedder([strip_social_noise(note_text(note)) for note in notes])
            if vectors is None or len(vectors) != len(notes):
                raise ValueError("embedder returned wrong vector count")
            kwargs: dict[str, Any] = {"previous": previous_snapshot}
            if cluster_threshold is not None:
                kwargs["cluster_threshold"] = cluster_threshold
            if align_threshold is not None:
                kwargs["align_threshold"] = align_threshold
            result = cluster_notes_semantic(notes, [list(vector) for vector in vectors], **kwargs)
        except Exception as exc:
            warnings.append(f"semantic clustering unavailable, fell back to rules: {type(exc).__name__}: {exc}")
            return None
        return result.events, result.centroids

    def _filter_notes(self, notes: list[OpinionNote], request: AnalyzeRequest) -> list[OpinionNote]:
        keyword = clean_text(request.keyword)
        platforms = {clean_text(platform).lower() for platform in request.platforms if clean_text(platform)}

        result: list[OpinionNote] = []
        for note in notes:
            if platforms and note.platform.lower() not in platforms:
                continue
            if keyword and keyword not in _search_text(note):
                continue
            result.append(note)
        return result


def _search_text(note: OpinionNote) -> str:
    return " ".join([note_text(note), note.platform, note.author_name])


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
