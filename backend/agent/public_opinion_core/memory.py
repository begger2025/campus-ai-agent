"""Run-to-run event memory for the portable public opinion Agent core.

This module compares the current run's events with a snapshot saved from a
previous run, producing trend annotations (new / rising / falling / stable)
and risk escalation flags. It only uses local JSON files for optional
persistence and never touches databases, FastAPI, or external APIs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import EventSnapshot, MemorySnapshot, OpinionEvent


TREND_NEW = "new"
TREND_RISING = "rising"
TREND_FALLING = "falling"
TREND_STABLE = "stable"

# Heat changes within max(5% of previous heat, 1.0) count as stable noise.
STABLE_HEAT_RATIO = 0.05
STABLE_HEAT_MIN_DELTA = 1.0

_RISK_RANK = {"low": 1, "medium": 2, "high": 3}


def build_snapshot(
    events: list[OpinionEvent],
    captured_at: str = "",
    centroids: dict[str, list[float]] | None = None,
) -> MemorySnapshot:
    """Capture the memory-relevant fields of each event, keyed by event_key.

    ``centroids`` comes from semantic clustering (event_key -> centroid) and
    enables cross-run event alignment; rule clustering passes nothing.
    """

    snapshot_events: dict[str, EventSnapshot] = {}
    for event in events:
        if not event.event_key:
            continue
        snapshot_events[event.event_key] = EventSnapshot(
            event_key=event.event_key,
            title=event.title,
            heat_score=float(event.heat_score),
            risk_level=event.risk_level,
            risk_score=float(event.risk_score),
            source_count=int(event.source_count),
            sentiment=event.sentiment,
            last_seen_at=event.last_seen_at,
            centroid=list((centroids or {}).get(event.event_key) or []),
        )
    return MemorySnapshot(captured_at=captured_at, events=snapshot_events)


def annotate_events_with_memory(
    events: list[OpinionEvent],
    previous: MemorySnapshot | None,
) -> list[OpinionEvent]:
    """Fill trend, heat_delta, previous_risk_level, risk_escalated in place."""

    for event in events:
        saved = previous.events.get(event.event_key) if previous else None
        if saved is None:
            event.trend = TREND_NEW
            event.heat_delta = 0.0
            event.previous_risk_level = ""
            event.risk_escalated = False
            continue

        delta = round(float(event.heat_score) - saved.heat_score, 2)
        threshold = max(abs(saved.heat_score) * STABLE_HEAT_RATIO, STABLE_HEAT_MIN_DELTA)
        if delta > threshold:
            event.trend = TREND_RISING
        elif delta < -threshold:
            event.trend = TREND_FALLING
        else:
            event.trend = TREND_STABLE

        event.heat_delta = delta
        event.previous_risk_level = saved.risk_level
        event.risk_escalated = (
            _RISK_RANK.get(event.risk_level, 0) > _RISK_RANK.get(saved.risk_level, 0)
        )
    return events


class JsonMemoryStore:
    """Optional local JSON persistence for MemorySnapshot between runs."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> MemorySnapshot | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        return _snapshot_from_dict(data)

    def save(self, snapshot: MemorySnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _snapshot_from_dict(data: dict[str, Any]) -> MemorySnapshot:
    raw_events = data.get("events")
    events: dict[str, EventSnapshot] = {}
    if isinstance(raw_events, dict):
        for event_key, raw_event in raw_events.items():
            if not isinstance(raw_event, dict):
                continue
            events[str(event_key)] = _event_snapshot_from_dict(str(event_key), raw_event)
    return MemorySnapshot(captured_at=str(data.get("captured_at") or ""), events=events)


def _event_snapshot_from_dict(event_key: str, data: dict[str, Any]) -> EventSnapshot:
    return EventSnapshot(
        event_key=event_key,
        title=str(data.get("title") or ""),
        heat_score=_as_float(data.get("heat_score")),
        risk_level=str(data.get("risk_level") or "low"),
        risk_score=_as_float(data.get("risk_score")),
        source_count=_as_int(data.get("source_count")),
        sentiment=str(data.get("sentiment") or "neutral"),
        last_seen_at=str(data.get("last_seen_at") or ""),
        centroid=_as_float_list(data.get("centroid")),
    )


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            return []
    return result


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
