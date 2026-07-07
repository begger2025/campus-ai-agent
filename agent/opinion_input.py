"""Load Agent-ready public opinion notes from processed_posts."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal  # noqa: E402
from backend.models import ProcessedPost  # noqa: E402


@dataclass
class OpinionNote:
    note_id: str
    title: str
    content: str
    source_keyword: str
    publish_date: str = ""
    publish_time_raw: str = ""
    author_name: str = ""
    tags: list[str] = field(default_factory=list)
    note_url: str = ""
    raw_note_url: str = ""
    images: list[str] = field(default_factory=list)
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    heat_score: float = 0.0
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    risk_level: str = "low"
    risk_score: float = 0.0
    risk_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    platform: str = ""
    raw_post_id: int | None = None


def _list_from_json(value: str | None) -> list[Any]:
    if not value:
        return []
    text_value = value.strip()
    if not text_value:
        return []
    try:
        parsed = json.loads(text_value)
    except json.JSONDecodeError:
        return [item.strip() for item in text_value.split(",") if item.strip()]
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return list(parsed.values())
    if parsed in (None, ""):
        return []
    return [parsed]


def _str_list(value: str | None) -> list[str]:
    result = []
    for item in _list_from_json(value):
        text_item = str(item).strip()
        if text_item:
            result.append(text_item)
    return result


def processed_post_to_opinion_note(row: ProcessedPost) -> OpinionNote:
    title = (row.title or row.content or row.note_id or "").strip()
    content = (row.content or row.title or "").strip()
    source_keyword = (row.source_keyword or row.platform or "").strip()
    return OpinionNote(
        note_id=row.note_id or f"{row.platform}:{row.raw_post_id}",
        title=title,
        content=content,
        source_keyword=source_keyword,
        publish_date=row.publish_date or "",
        publish_time_raw=row.publish_time_raw or "",
        author_name=row.author_name or row.author or "",
        tags=_str_list(row.tags_json),
        note_url=row.note_url or "",
        raw_note_url=row.raw_note_url or row.note_url or "",
        images=_str_list(row.images_json),
        like_count=row.like_count or 0,
        collect_count=row.collect_count or 0,
        comment_count=row.comment_count or 0,
        share_count=row.share_count or 0,
        heat_score=float(row.heat_score or 0.0),
        sentiment=row.sentiment or "neutral",
        sentiment_score=float(row.sentiment_score or 0.0),
        risk_level=row.risk_level or "low",
        risk_score=float(row.risk_score or 0.0),
        risk_reasons=_str_list(row.risk_reasons_json),
        concerns=_str_list(row.concerns_json),
        platform=row.platform or "",
        raw_post_id=row.raw_post_id,
    )


def load_opinion_notes_from_db(
    *,
    limit: int = 100,
    keyword: str | None = None,
    platform: str | None = None,
    min_heat_score: float | None = None,
    db: Session | None = None,
) -> list[OpinionNote]:
    """Load processed posts and convert them to OpinionNote objects."""

    owns_session = db is None
    session = db or SessionLocal()
    try:
        query = session.query(ProcessedPost)
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.filter(
                (ProcessedPost.title.like(like_pattern))
                | (ProcessedPost.content.like(like_pattern))
                | (ProcessedPost.source_keyword.like(like_pattern))
            )
        if platform:
            query = query.filter(ProcessedPost.platform == platform)
        if min_heat_score is not None:
            query = query.filter(ProcessedPost.heat_score >= min_heat_score)
        rows = (
            query.order_by(ProcessedPost.heat_score.desc(), ProcessedPost.id.desc())
            .limit(limit)
            .all()
        )
        return [processed_post_to_opinion_note(row) for row in rows]
    finally:
        if owns_session:
            session.close()


def _safe_console_text(value: str) -> str:
    return value.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
        sys.stdout.encoding or "utf-8"
    )


def main() -> int:
    notes = load_opinion_notes_from_db(limit=5)
    print(f"OpinionNote count: {len(notes)}")
    for note in notes:
        title = _safe_console_text(note.title[:60])
        print(
            f"- {note.note_id} | {title} | "
            f"keyword={note.source_keyword} | heat={note.heat_score}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
