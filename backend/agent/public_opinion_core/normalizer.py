"""Text and label normalization helpers for the portable Agent core."""

from __future__ import annotations

import re
from typing import Any

from .schemas import OpinionNote


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u200b", " ")).strip()


def unique_strings(values: list[Any] | tuple[Any, ...] | set[Any] | Any) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]

    result: list[str] = []
    for value in raw_values:
        text = clean_text(value)
        if text and text not in result:
            result.append(text)
    return result


def note_text(note: OpinionNote) -> str:
    """帖子本体文本：聚类嵌入的输入口径，不含评论（阈值按此标定，勿改动语义）。"""

    parts = [
        note.title,
        note.content,
        note.source_keyword,
        " ".join(note.keywords),
        " ".join(note.tags),
    ]
    return clean_text(" ".join(parts))


def analysis_text(note: OpinionNote) -> str:
    """情绪/风险分析文本：帖子本体 + 高赞评论摘录（评论区风向参与研判）。"""

    if not note.top_comments:
        return note_text(note)
    return clean_text(" ".join([note_text(note), " ".join(note.top_comments)]))


SENTIMENT_LABELS = {
    "positive": "positive",
    "正面": "positive",
    "偏正面": "positive",
    "neutral": "neutral",
    "中性": "neutral",
    "negative": "negative",
    "负面": "negative",
    "偏负面": "negative",
    "controversial": "controversial",
    "争议": "controversial",
}


RISK_LABELS = {
    "high": "high",
    "高": "high",
    "高风险": "high",
    "medium": "medium",
    "中": "medium",
    "中风险": "medium",
    "low": "low",
    "低": "low",
    "低风险": "low",
}


def normalize_sentiment_label(value: Any) -> str:
    return SENTIMENT_LABELS.get(clean_text(value).lower(), SENTIMENT_LABELS.get(clean_text(value), "neutral"))


def normalize_risk_level(value: Any) -> str:
    return RISK_LABELS.get(clean_text(value).lower(), RISK_LABELS.get(clean_text(value), "low"))


def normalize_note_fields(note: OpinionNote) -> OpinionNote:
    note.title = clean_text(note.title)
    note.content = clean_text(note.content)
    note.source_keyword = clean_text(note.source_keyword)
    note.author_name = clean_text(note.author_name)
    note.keywords = unique_strings(note.keywords)
    note.tags = unique_strings(note.tags or note.keywords)
    note.sentiment = normalize_sentiment_label(note.sentiment)
    note.risk_level = normalize_risk_level(note.risk_level)
    return note


def normalize_notes(notes: list[OpinionNote]) -> list[OpinionNote]:
    return [normalize_note_fields(note) for note in notes]
