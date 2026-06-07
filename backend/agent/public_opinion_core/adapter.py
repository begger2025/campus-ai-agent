"""Adapters from processed_posts-like rows to portable OpinionNote objects."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .schemas import OpinionNote


KEYWORD_CANDIDATES = [
    "宿舍",
    "热水",
    "后勤",
    "维修",
    "洗衣房",
    "食堂",
    "饭堂",
    "排队",
    "价格",
    "卫生",
    "错峰",
    "课程安排",
    "课程",
    "课表",
    "考试",
    "选课",
    "补退选",
    "教务",
    "作业",
    "压力",
    "问卷",
    "校园安全",
    "诈骗",
    "防诈骗",
    "短信",
    "缴费",
    "路灯",
    "夜间",
    "巡逻",
    "门禁",
    "通知",
    "反馈",
    "讲座",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u200b", " ")).strip()


def parse_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)

    text = clean_text(value).replace(",", "").replace("+", "")
    if not text:
        return 0

    multiplier = 1
    lowered = text.lower()
    if "万" in text or "w" in lowered:
        multiplier = 10_000
    elif "千" in text or "k" in lowered:
        multiplier = 1_000

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return max(int(float(match.group(0)) * multiplier), 0)


def calculate_heat_score(*, like_count: int, collect_count: int, comment_count: int, share_count: int) -> float:
    return round(
        like_count * 1.0
        + collect_count * 1.5
        + comment_count * 3.0
        + share_count * 2.5,
        2,
    )


def normalize_keywords(value: Any, *, text: str = "") -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(r"[,，#\s]+", value)
    elif value is None:
        raw_items = []
    else:
        raw_items = [value]

    keywords: list[str] = []
    for item in raw_items:
        cleaned = clean_text(item).strip("# ")
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)

    if keywords:
        return keywords

    for candidate in KEYWORD_CANDIDATES:
        if candidate in text and candidate not in keywords:
            keywords.append(candidate)
    return keywords


def _publish_date_from_time(publish_time: str) -> str:
    if re.match(r"^\d{4}-\d{2}-\d{2}", publish_time):
        return publish_time[:10]
    return ""


def _append_warning(warnings: list[str] | None, message: str) -> None:
    if warnings is not None:
        warnings.append(message)


def processed_post_to_note(row: Mapping[str, Any] | Any, warnings: list[str] | None = None) -> OpinionNote | None:
    """Convert one processed_posts-like mapping into an OpinionNote.

    Invalid rows return None and append a warning when a warning list is
    provided. This keeps batch conversion resilient to dirty records.
    """

    if not isinstance(row, Mapping):
        _append_warning(warnings, f"skipped non-mapping row: {type(row).__name__}")
        return None

    processed_post_id = row.get("id") or row.get("processed_post_id")
    raw_post_id = row.get("raw_post_id")
    if processed_post_id is None:
        _append_warning(warnings, "skipped row without id/processed_post_id")
        return None

    content = clean_text(row.get("content") or row.get("desc") or row.get("body"))
    title = clean_text(row.get("title"))
    if not title and content:
        title = content[:30]
    if not title and not content:
        _append_warning(warnings, f"skipped row {processed_post_id}: missing title and content")
        return None

    combined_text = " ".join(
        [
            title,
            content,
            clean_text(row.get("expected_topic")),
            clean_text(row.get("source_keyword")),
        ]
    )
    keywords = normalize_keywords(row.get("keywords"), text=combined_text)
    publish_time = clean_text(row.get("publish_time") or row.get("created_at") or "")
    like_count = parse_int(row.get("like_count"))
    collect_count = parse_int(row.get("collect_count"))
    comment_count = parse_int(row.get("comment_count"))
    share_count = parse_int(row.get("share_count"))

    note_id = clean_text(row.get("note_id") or row.get("post_id") or processed_post_id)
    platform = clean_text(row.get("platform"))
    url = clean_text(row.get("url") or row.get("note_url"))

    extra = {
        key: row[key]
        for key in ("expected_event", "expected_topic")
        if key in row
    }

    return OpinionNote(
        note_id=note_id,
        processed_post_id=parse_int(processed_post_id),
        raw_post_id=parse_int(raw_post_id) if raw_post_id is not None else None,
        platform=platform,
        title=title,
        content=content,
        author_name=clean_text(row.get("author") or row.get("author_name")),
        publish_time=publish_time,
        publish_date=clean_text(row.get("publish_date")) or _publish_date_from_time(publish_time),
        url=url,
        raw_url=clean_text(row.get("raw_url") or row.get("raw_note_url") or url),
        source_keyword=clean_text(row.get("source_keyword") or row.get("expected_topic") or (keywords[0] if keywords else "")),
        keywords=keywords,
        tags=list(keywords),
        like_count=like_count,
        collect_count=collect_count,
        comment_count=comment_count,
        share_count=share_count,
        heat_score=calculate_heat_score(
            like_count=like_count,
            collect_count=collect_count,
            comment_count=comment_count,
            share_count=share_count,
        ),
        sentiment=clean_text(row.get("sentiment")) or "neutral",
        risk_level=clean_text(row.get("risk_level")) or "low",
        extra=extra,
    )


def processed_posts_to_notes(rows: Iterable[Mapping[str, Any] | Any], warnings: list[str] | None = None) -> list[OpinionNote]:
    notes: list[OpinionNote] = []
    for index, row in enumerate(rows, start=1):
        note = processed_post_to_note(row, warnings=warnings)
        if note is None:
            if warnings is not None and (not warnings or f"row #{index}" not in warnings[-1]):
                # The concrete reason is usually recorded by processed_post_to_note.
                pass
            continue
        notes.append(note)
    return notes
