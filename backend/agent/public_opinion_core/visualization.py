"""Chart-ready data builders for the portable public opinion Agent core.

Every function takes analyzed notes/events and returns plain JSON-serializable
structures (lists and dicts) that any frontend chart library can consume.
No database, FastAPI, or external API imports.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .schemas import OpinionEvent, OpinionNote


_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")

_SENTIMENT_COUNT_KEYS = {
    "positive": "positive_count",
    "neutral": "neutral_count",
    "negative": "negative_count",
    "controversial": "controversial_count",
}


def build_daily_trend_series(notes: list[OpinionNote]) -> list[dict[str, Any]]:
    """Aggregate notes per day: note count, heat sum, sentiment counts."""

    buckets: dict[str, dict[str, Any]] = {}
    for note in notes:
        date = _note_date(note)
        if not date:
            continue
        bucket = buckets.setdefault(
            date,
            {
                "date": date,
                "note_count": 0,
                "heat_score": 0.0,
                "positive_count": 0,
                "neutral_count": 0,
                "negative_count": 0,
                "controversial_count": 0,
            },
        )
        bucket["note_count"] += 1
        bucket["heat_score"] = round(bucket["heat_score"] + float(note.heat_score), 2)
        sentiment_key = _SENTIMENT_COUNT_KEYS.get(note.sentiment)
        if sentiment_key:
            bucket[sentiment_key] += 1
    return [buckets[date] for date in sorted(buckets)]


def build_keyword_cloud(notes: list[OpinionNote], limit: int = 50) -> list[dict[str, Any]]:
    """Count keywords across notes; one note contributes one count per keyword."""

    counter: Counter[str] = Counter()
    for note in notes:
        note_keywords = {
            keyword.strip()
            for keyword in [*note.keywords, *note.tags, note.source_keyword]
            if keyword and keyword.strip()
        }
        counter.update(note_keywords)
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"keyword": keyword, "count": count} for keyword, count in ranked[: max(limit, 0)]]


def build_sentiment_distribution(notes: list[OpinionNote]) -> dict[str, int]:
    return dict(Counter(note.sentiment for note in notes if note.sentiment))


def build_risk_distribution(events: list[OpinionEvent]) -> dict[str, int]:
    return dict(Counter(event.risk_level for event in events if event.risk_level))


def build_platform_distribution(notes: list[OpinionNote]) -> list[dict[str, Any]]:
    counter = Counter(note.platform for note in notes if note.platform)
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"platform": platform, "count": count} for platform, count in ranked]


def build_event_trend_overview(events: list[OpinionEvent]) -> list[dict[str, Any]]:
    """Per-event card data combining clustering output and memory trend fields."""

    return [
        {
            "event_key": event.event_key,
            "title": event.title,
            "trend": event.trend,
            "heat_delta": float(event.heat_delta),
            "heat_score": float(event.heat_score),
            "risk_level": event.risk_level,
            "previous_risk_level": event.previous_risk_level,
            "risk_escalated": bool(event.risk_escalated),
            "sentiment": event.sentiment,
            "source_count": int(event.source_count),
        }
        for event in events
    ]


def build_visualization_payload(
    notes: list[OpinionNote],
    events: list[OpinionEvent],
    keyword_limit: int = 50,
) -> dict[str, Any]:
    """Bundle all chart sections into one frontend-agnostic payload."""

    return {
        "daily_trend": build_daily_trend_series(notes),
        "keyword_cloud": build_keyword_cloud(notes, limit=keyword_limit),
        "sentiment_distribution": build_sentiment_distribution(notes),
        "risk_distribution": build_risk_distribution(events),
        "platform_distribution": build_platform_distribution(notes),
        "event_trends": build_event_trend_overview(events),
    }


def _note_date(note: OpinionNote) -> str:
    for value in (note.publish_date, note.publish_time):
        text = str(value or "").strip()
        if _DATE_PATTERN.match(text):
            return text[:10]
    return ""
