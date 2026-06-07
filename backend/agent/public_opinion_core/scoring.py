"""Heat score calculation for OpinionNote records."""

from __future__ import annotations

from typing import Any

from .schemas import OpinionNote


def _non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def calculate_heat_score(
    *,
    like_count: int,
    collect_count: int,
    comment_count: int,
    share_count: int,
) -> float:
    """Use the same first-week weighting: comments and shares matter more."""

    return round(
        _non_negative_int(like_count) * 1.0
        + _non_negative_int(collect_count) * 1.5
        + _non_negative_int(comment_count) * 3.0
        + _non_negative_int(share_count) * 2.5,
        2,
    )


def score_note(note: OpinionNote) -> OpinionNote:
    note.heat_score = calculate_heat_score(
        like_count=note.like_count,
        collect_count=note.collect_count,
        comment_count=note.comment_count,
        share_count=note.share_count,
    )
    return note


def score_notes(notes: list[OpinionNote]) -> list[OpinionNote]:
    return [score_note(note) for note in notes]
