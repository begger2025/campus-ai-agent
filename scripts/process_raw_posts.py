"""Clean raw_posts into processed_posts for the public opinion agent."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy.orm import Session

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.admin_models import CrawlTask  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import ProcessedPost, RawPost  # noqa: E402
from backend.services.log_service import create_crawl_task, finish_crawl_task, write_system_log  # noqa: E402
from scripts.ensure_wp4_schema import ensure_wp4_schema  # noqa: E402


@dataclass
class ProcessResult:
    scanned: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_empty: int = 0
    failed: int = 0
    refreshed: int = 0
    errors: list[str] = field(default_factory=list)


def _platform_label(platforms: Iterable[str] | None) -> str:
    values = [str(item).strip() for item in platforms or [] if str(item).strip()]
    return ",".join(values) if values else "all"


def _should_record_task(dry_run: bool, record_task: bool | None) -> bool:
    if record_task is not None:
        return record_task
    return not dry_run


def _task_status(result: ProcessResult) -> str:
    if result.failed and result.inserted:
        return "partial_success"
    if result.failed:
        return "failed"
    return "success"


def _create_task_record(*, platforms: Iterable[str] | None, created_by: str) -> int | None:
    db = SessionLocal()
    try:
        task = create_crawl_task(
            db,
            task_name="process raw_posts to processed_posts",
            task_type="import",
            platform=_platform_label(platforms),
            created_by=created_by,
        )
        db.commit()
        return task.id
    finally:
        db.close()


def _finish_task_record(task_id: int | None, result: ProcessResult) -> None:
    if task_id is None:
        return
    db = SessionLocal()
    try:
        task = db.get(CrawlTask, task_id)
        if task is None:
            return
        finish_crawl_task(
            db,
            task,
            status=_task_status(result),
            total_count=result.scanned,
            success_count=result.inserted,
            failed_count=result.failed,
            error_message="; ".join(result.errors[:5]),
        )
        if result.failed:
            write_system_log(
                db,
                level="warning",
                module="sync",
                message="raw_posts processing finished with failed rows",
                detail={
                    "task_id": task_id,
                    "scanned": result.scanned,
                    "inserted": result.inserted,
                    "failed": result.failed,
                    "errors": result.errors[:5],
                },
                related_task_id=task_id,
            )
        db.commit()
    finally:
        db.close()


def _fail_task_record(task_id: int | None, exc: Exception) -> None:
    db = SessionLocal()
    try:
        task = db.get(CrawlTask, task_id) if task_id is not None else None
        if task is not None:
            finish_crawl_task(db, task, status="failed", failed_count=1, error_message=str(exc))
        write_system_log(
            db,
            level="error",
            module="sync",
            message="raw_posts processing failed",
            detail={"task_id": task_id, "error": str(exc)},
            related_task_id=task_id,
        )
        db.commit()
    finally:
        db.close()


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _title_from_raw(raw: RawPost) -> str:
    title = _clean_text(raw.title)
    content = _clean_text(raw.content)
    return (title or content[:80] or f"{raw.platform}:{raw.external_id or raw.id}")[:500]


def _content_from_raw(raw: RawPost) -> str:
    content = _clean_text(raw.content)
    return content or _clean_text(raw.title)


def _publish_date(value: datetime | None) -> str:
    return value.date().isoformat() if value else ""


def _publish_time_raw(value: datetime | None) -> str:
    return value.isoformat(sep=" ") if value else ""


def _note_id(raw: RawPost) -> str:
    external = raw.external_id or str(raw.id)
    return f"{raw.platform}:{external}"


def calculate_heat_score(
    *,
    like_count: int = 0,
    collect_count: int = 0,
    comment_count: int = 0,
    share_count: int = 0,
) -> float:
    return round(
        like_count * 1.0
        + collect_count * 1.5
        + comment_count * 3.0
        + share_count * 2.5,
        2,
    )


def _to_processed(raw: RawPost) -> ProcessedPost:
    title = _title_from_raw(raw)
    content = _content_from_raw(raw)
    source_keyword = _clean_text(raw.source_keyword) or raw.platform
    heat_score = calculate_heat_score(
        like_count=raw.like_count or 0,
        collect_count=raw.collect_count or 0,
        comment_count=raw.comment_count or 0,
        share_count=raw.share_count or 0,
    )

    return ProcessedPost(
        raw_post_id=raw.id,
        platform=raw.platform,
        note_id=_note_id(raw),
        title=title,
        content=content,
        source_keyword=source_keyword,
        publish_date=_publish_date(raw.publish_time),
        publish_time_raw=_publish_time_raw(raw.publish_time),
        author_name=_clean_text(raw.author),
        tags_json=raw.tags_json or "",
        note_url=raw.url or "",
        raw_note_url=raw.raw_url or raw.url or "",
        images_json=raw.images_json or "",
        like_count=raw.like_count or 0,
        collect_count=raw.collect_count or 0,
        comment_count=raw.comment_count or 0,
        share_count=raw.share_count or 0,
        heat_score=heat_score,
        sentiment="neutral",
        sentiment_score=0.0,
        risk_level="low",
        risk_score=0.0,
        risk_reasons_json="[]",
        concerns_json="[]",
        author=_clean_text(raw.author),
        publish_time=raw.publish_time,
    )


# 互动量 + 热度：注意点 3 的 --refresh 只重算这五个字段，情绪/风险/标签等分析字段不动
# （成本高、多为 LLM 相关，交给独立的分析流程）。
REFRESHABLE_FIELDS = ("like_count", "collect_count", "comment_count", "share_count")


def _refresh_processed_posts(db: Session, platforms: Iterable[str] | None = None) -> int:
    """对已存在的 processed_posts 行，从其 raw_post 重算互动量与 heat_score（复用 calculate_heat_score）。"""

    query = db.query(ProcessedPost)
    platform_list = [item for item in platforms or [] if item]
    if platform_list:
        query = query.filter(ProcessedPost.platform.in_(platform_list))

    refreshed = 0
    for processed in query.all():
        raw = processed.raw_post
        if raw is None:
            continue
        new_values = {field_name: getattr(raw, field_name) or 0 for field_name in REFRESHABLE_FIELDS}
        new_values["heat_score"] = calculate_heat_score(**new_values)
        changed = any(getattr(processed, field_name) != value for field_name, value in new_values.items())
        if not changed:
            continue
        for field_name, value in new_values.items():
            setattr(processed, field_name, value)
        refreshed += 1
    return refreshed


def _candidate_query(db: Session, platforms: Iterable[str] | None = None):
    processed_raw_ids = db.query(ProcessedPost.raw_post_id)
    query = (
        db.query(RawPost)
        .filter(RawPost.status.in_(["normal", "active", ""]))
        .filter(~RawPost.id.in_(processed_raw_ids))
        .order_by(RawPost.publish_time.desc(), RawPost.id.desc())
    )
    platform_list = [item for item in platforms or [] if item]
    if platform_list:
        query = query.filter(RawPost.platform.in_(platform_list))
    return query


def _process_raw_posts(
    db: Session,
    *,
    limit: int | None,
    platforms: Iterable[str] | None,
    dry_run: bool,
    refresh: bool = False,
) -> ProcessResult:
    """核心处理逻辑：只依赖传入的 db session，不碰 init_db/SessionLocal，便于单测注入内存库。"""

    result = ProcessResult()
    query = _candidate_query(db, platforms)
    if limit and limit > 0:
        query = query.limit(limit)
    rows = query.all()
    result.scanned = len(rows)

    for raw in rows:
        try:
            title = _title_from_raw(raw)
            content = _content_from_raw(raw)
            if not title and not content:
                result.skipped_empty += 1
                continue
            exists = (
                db.query(ProcessedPost)
                .filter(ProcessedPost.raw_post_id == raw.id)
                .first()
            )
            if exists:
                result.skipped_duplicate += 1
                continue
            if not dry_run:
                db.add(_to_processed(raw))
            result.inserted += 1
        except Exception as exc:
            result.failed += 1
            result.errors.append(str(exc))

    if refresh:
        result.refreshed = _refresh_processed_posts(db, platforms)

    return result


def process_raw_posts(
    *,
    limit: int | None = 100,
    platforms: Iterable[str] | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    record_task: bool | None = None,
    created_by: str = "system",
) -> ProcessResult:
    init_db()
    if not dry_run:
        ensure_wp4_schema()

    task_id = None
    if _should_record_task(dry_run, record_task):
        task_id = _create_task_record(platforms=platforms, created_by=created_by)

    db = SessionLocal()
    try:
        result = _process_raw_posts(db, limit=limit, platforms=platforms, dry_run=dry_run, refresh=refresh)

        if not dry_run:
            db.commit()
        else:
            db.rollback()
        _finish_task_record(task_id, result)
    except Exception as exc:
        _fail_task_record(task_id, exc)
        raise
    finally:
        db.close()
    return result


def _print_result(result: ProcessResult, dry_run: bool) -> None:
    if dry_run:
        print("[DRY-RUN] no rows were inserted")
    print(
        f"scanned={result.scanned} "
        f"inserted={result.inserted} "
        f"skipped_duplicate={result.skipped_duplicate} "
        f"skipped_empty={result.skipped_empty} "
        f"refreshed={result.refreshed} "
        f"failed={result.failed}"
    )
    for error in result.errors[:5]:
        print(f"  error: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Process raw_posts into processed_posts")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--platform", action="append", choices=["xhs", "weibo", "tieba"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="对已存在的 processed_posts 行重新计算互动量与热度（默认不刷新）",
    )
    args = parser.parse_args()

    result = process_raw_posts(
        limit=args.limit,
        platforms=args.platform,
        dry_run=args.dry_run,
        refresh=args.refresh,
    )
    _print_result(result, args.dry_run)
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
