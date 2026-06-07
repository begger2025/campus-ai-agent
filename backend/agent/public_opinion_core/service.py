"""Service entrypoint for the portable public opinion Agent core."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import time
from typing import Any

from .adapter import processed_posts_to_notes
from .clustering import cluster_notes
from .normalizer import clean_text, note_text
from .schemas import AgentRunLogPayload, AnalyzeRequest, AnalyzeResult, OpinionNote
from .scoring import score_notes
from .sentiment_risk import analyze_notes_sentiment_and_risk


class PublicOpinionAgentService:
    """Analyze processed_posts-like rows without knowing their data source."""

    def analyze_from_rows(
        self,
        rows: Iterable[Mapping[str, Any] | Any],
        request: AnalyzeRequest | None = None,
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
        if notes:
            notes = score_notes(notes)
            notes = analyze_notes_sentiment_and_risk(notes)
            events = cluster_notes(notes)

        finished_at = _utc_now_text()
        duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
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
            },
        )

        return AnalyzeResult(
            request=request,
            events=events,
            run_log=run_log,
            warnings=list(warnings),
        )

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
