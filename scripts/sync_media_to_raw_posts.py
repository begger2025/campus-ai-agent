"""Sync MediaCrawler native tables or enhanced JSON/JSONL into raw_posts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.admin_models import CrawlTask  # noqa: E402
from backend.database import SessionLocal, engine, init_db  # noqa: E402
from backend.models import RawPost  # noqa: E402
from backend.services.log_service import create_crawl_task, finish_crawl_task, write_system_log  # noqa: E402
from scripts.ensure_wp4_schema import ensure_wp4_schema  # noqa: E402


SUPPORTED_PLATFORMS = {"xhs", "weibo", "tieba"}
TABLE_BY_PLATFORM = {
    "xhs": "xhs_note",
    "weibo": "weibo_note",
    "tieba": "tieba_note",
}


@dataclass
class PlatformSyncStats:
    platform: str
    scanned: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    results: list[PlatformSyncStats] = field(default_factory=list)

    @property
    def total_scanned(self) -> int:
        return sum(item.scanned for item in self.results)

    @property
    def total_inserted(self) -> int:
        return sum(item.inserted for item in self.results)

    @property
    def total_skipped_duplicate(self) -> int:
        return sum(item.skipped_duplicate for item in self.results)

    @property
    def total_failed(self) -> int:
        return sum(item.failed for item in self.results)


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    return text_value if text_value else default


def _truncate(value: str, max_len: int) -> str:
    return value[:max_len] if len(value) > max_len else value


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, default=str)


def _raw_json(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, default=str, sort_keys=True)


# 微博话题嵌在正文里：#话题#，可能带 [超话] 后缀；2–20 字，去重保序。
WEIBO_TOPIC_RE = re.compile(r"#([^#\r\n]{1,32}?)#")
WEIBO_TOPIC_MIN_LEN = 2
WEIBO_TOPIC_MAX_LEN = 20
_SUPERTOPIC_SUFFIX = "[超话]"


def extract_weibo_topics(content: Any) -> list[str]:
    if not content:
        return []
    topics: list[str] = []
    for match in WEIBO_TOPIC_RE.findall(str(content)):
        topic = match.strip()
        if topic.endswith(_SUPERTOPIC_SUFFIX):
            topic = topic[: -len(_SUPERTOPIC_SUFFIX)].strip()
        if not (WEIBO_TOPIC_MIN_LEN <= len(topic) <= WEIBO_TOPIC_MAX_LEN):
            continue
        if topic not in topics:
            topics.append(topic)
    return topics


def normalize_xhs_tag_list(tag_list: Any) -> list[str]:
    """xhs 原生 tag_list 是字典数组 JSON（[{"name":...,"type":...}]）；统一成纯名字数组。"""

    if not tag_list:
        return []
    if isinstance(tag_list, str):
        try:
            tag_list = json.loads(tag_list)
        except (TypeError, ValueError):
            return []
    if isinstance(tag_list, str):
        # 旧版爬虫形状：json.dumps 过的逗号分隔字符串（"中山大学,中大破冰"）
        tag_list = [part for part in tag_list.split(",")]
    if not isinstance(tag_list, list):
        return []
    names: list[str] = []
    for item in tag_list:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return names


def _int_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)

    text_value = str(value).strip().replace(",", "")
    if not text_value:
        return 0
    multiplier = 1
    if text_value.endswith("万"):
        multiplier = 10000
        text_value = text_value[:-1]
    elif text_value.lower().endswith("k"):
        multiplier = 1000
        text_value = text_value[:-1]

    match = re.search(r"-?\d+(?:\.\d+)?", text_value)
    if not match:
        return 0
    try:
        return max(int(float(match.group(0)) * multiplier), 0)
    except ValueError:
        return 0


def _datetime_from_epoch(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10_000_000_000:
        number = number / 1000
    try:
        return datetime.fromtimestamp(number)
    except (OSError, OverflowError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return _datetime_from_epoch(value)

    text_value = str(value).strip()
    if not text_value:
        return None
    if text_value.isdigit():
        return _datetime_from_epoch(text_value)

    normalized = text_value.replace("Z", "").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized[: len(fmt)], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _fallback_external_id(platform: str, row: dict[str, Any]) -> str:
    seed = "|".join(
        [
            platform,
            _as_text(row.get("note_url") or row.get("url") or row.get("raw_url")),
            _as_text(row.get("title")),
            _as_text(row.get("content") or row.get("desc")),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]
    return f"generated:{digest}"


def _base_payload(
    *,
    platform: str,
    source_table: str,
    source_raw_id: Any,
    external_id: Any,
    source_keyword: Any,
    title: Any,
    content: Any,
    author: Any,
    publish_time: Any,
    url: Any,
    raw_url: Any = None,
    like_count: Any = 0,
    collect_count: Any = 0,
    comment_count: Any = 0,
    share_count: Any = 0,
    tags_json: Any = "",
    images_json: Any = "",
    crawl_time: Any = None,
    raw_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = raw_row or {}
    ext_id = _as_text(external_id)
    if not ext_id:
        ext_id = _fallback_external_id(platform, row)
    content_text = _as_text(content)
    title_text = _as_text(title) or _truncate(content_text, 80) or ext_id

    return {
        "platform": platform,
        "external_id": _truncate(ext_id, 255),
        "source_table": _truncate(_as_text(source_table), 64),
        "source_raw_id": _truncate(_as_text(source_raw_id), 255),
        "source_keyword": _truncate(_as_text(source_keyword, platform), 255),
        "title": _truncate(title_text, 500),
        "content": content_text,
        "author": _truncate(_as_text(author), 100),
        "publish_time": _parse_datetime(publish_time),
        "url": _truncate(_as_text(url), 500),
        "raw_url": _truncate(_as_text(raw_url or url), 500),
        "like_count": _int_count(like_count),
        "collect_count": _int_count(collect_count),
        "comment_count": _int_count(comment_count),
        "share_count": _int_count(share_count),
        "tags_json": _json_text(tags_json),
        "images_json": _json_text(images_json),
        "raw_json": _raw_json(row),
        "crawl_time": _parse_datetime(crawl_time) or datetime.utcnow(),
        "status": "normal",
    }


def _map_xhs(row: dict[str, Any]) -> dict[str, Any]:
    publish_time = row.get("publish_timestamp_ms") or row.get("time")
    crawl_time = row.get("last_crawled_at") or row.get("last_modify_ts") or row.get("add_ts")
    return _base_payload(
        platform="xhs",
        source_table="xhs_note",
        source_raw_id=row.get("id"),
        external_id=row.get("note_id"),
        source_keyword=row.get("source_keyword"),
        title=row.get("title"),
        content=row.get("desc"),
        author=row.get("nickname"),
        publish_time=publish_time,
        url=row.get("note_url"),
        like_count=row.get("liked_count"),
        collect_count=row.get("collected_count"),
        comment_count=row.get("comment_count"),
        share_count=row.get("share_count"),
        tags_json=normalize_xhs_tag_list(row.get("tag_list")) or "",
        images_json=row.get("image_list"),
        crawl_time=crawl_time,
        raw_row=row,
    )


def _map_weibo(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content")
    crawl_time = row.get("last_modify_ts") or row.get("add_ts")
    return _base_payload(
        platform="weibo",
        source_table="weibo_note",
        source_raw_id=row.get("id"),
        external_id=row.get("note_id"),
        source_keyword=row.get("source_keyword"),
        title=_truncate(_as_text(content), 80),
        content=content,
        author=row.get("nickname"),
        publish_time=row.get("create_time") or row.get("create_date_time"),
        url=row.get("note_url"),
        like_count=row.get("liked_count"),
        collect_count=0,
        comment_count=row.get("comments_count"),
        share_count=row.get("shared_count"),
        tags_json=extract_weibo_topics(content) or "",
        crawl_time=crawl_time,
        raw_row=row,
    )


def _map_tieba(row: dict[str, Any]) -> dict[str, Any]:
    crawl_time = row.get("last_modify_ts") or row.get("add_ts")
    tieba_name = str(row.get("tieba_name") or "").strip()
    return _base_payload(
        platform="tieba",
        source_table="tieba_note",
        source_raw_id=row.get("id"),
        external_id=row.get("note_id"),
        source_keyword=row.get("source_keyword"),
        title=row.get("title"),
        content=row.get("desc"),
        author=row.get("user_nickname"),
        publish_time=row.get("publish_time"),
        url=row.get("note_url"),
        comment_count=row.get("total_replay_num"),
        tags_json=[tieba_name] if tieba_name else "",
        crawl_time=crawl_time,
        raw_row=row,
    )


def _map_json(row: dict[str, Any], platform: str, source_table: str) -> dict[str, Any]:
    return _base_payload(
        platform=platform,
        source_table=source_table,
        source_raw_id=row.get("source_raw_id") or row.get("id"),
        external_id=row.get("external_id") or row.get("note_id") or row.get("id"),
        source_keyword=row.get("source_keyword") or row.get("keyword"),
        title=row.get("title"),
        content=row.get("content") or row.get("desc") or row.get("summary"),
        author=row.get("author") or row.get("author_name") or row.get("nickname"),
        publish_time=row.get("publish_time") or row.get("publish_date") or row.get("time"),
        url=row.get("url") or row.get("note_url"),
        raw_url=row.get("raw_url") or row.get("raw_note_url"),
        like_count=row.get("like_count") or row.get("liked_count"),
        collect_count=row.get("collect_count") or row.get("collected_count"),
        comment_count=row.get("comment_count") or row.get("comments_count"),
        share_count=row.get("share_count") or row.get("shared_count"),
        tags_json=row.get("tags_json") or row.get("tags") or row.get("tag_list"),
        images_json=row.get("images_json") or row.get("images") or row.get("image_list"),
        crawl_time=row.get("crawl_time") or row.get("last_crawled_at"),
        raw_row=row,
    )


MAPPER_BY_PLATFORM = {
    "xhs": _map_xhs,
    "weibo": _map_weibo,
    "tieba": _map_tieba,
}


def _normalize_platforms(platforms: Iterable[str] | None) -> list[str]:
    if not platforms:
        return ["xhs", "weibo", "tieba"]
    result: list[str] = []
    for platform in platforms:
        item = platform.lower().strip()
        if item == "all":
            return ["xhs", "weibo", "tieba"]
        if item not in SUPPORTED_PLATFORMS:
            raise ValueError(f"unsupported platform: {platform}")
        if item not in result:
            result.append(item)
    return result


def _platform_label(platforms: Iterable[str] | None, default: str = "all") -> str:
    if not platforms:
        return default
    values = [str(item).strip() for item in platforms if str(item).strip()]
    if not values or "all" in values:
        return default
    return ",".join(values)


def _should_record_task(dry_run: bool, record_task: bool | None) -> bool:
    if record_task is not None:
        return record_task
    return not dry_run


def _task_status(total_inserted: int, total_failed: int) -> str:
    if total_failed and total_inserted:
        return "partial_success"
    if total_failed:
        return "failed"
    return "success"


def _task_errors(result: SyncResult) -> str:
    errors: list[str] = []
    for item in result.results:
        errors.extend(item.errors)
    return "; ".join(errors[:5])


def _create_task_record(
    *,
    task_name: str,
    task_type: str,
    platform: str,
    created_by: str,
) -> int | None:
    db = SessionLocal()
    try:
        task = create_crawl_task(
            db,
            task_name=task_name,
            task_type=task_type,
            platform=platform,
            created_by=created_by,
        )
        db.commit()
        return task.id
    finally:
        db.close()


def _finish_task_record(task_id: int | None, result: SyncResult) -> None:
    if task_id is None:
        return
    db = SessionLocal()
    try:
        task = db.get(CrawlTask, task_id)
        if task is None:
            return
        status = _task_status(result.total_inserted, result.total_failed)
        finish_crawl_task(
            db,
            task,
            status=status,
            total_count=result.total_scanned,
            success_count=result.total_inserted,
            failed_count=result.total_failed,
            error_message=_task_errors(result),
        )
        if result.total_failed:
            write_system_log(
                db,
                level="warning",
                module="sync",
                message="MediaCrawler sync finished with failed rows",
                detail={
                    "task_id": task_id,
                    "total_scanned": result.total_scanned,
                    "total_inserted": result.total_inserted,
                    "total_failed": result.total_failed,
                    "errors": _task_errors(result),
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
            finish_crawl_task(
                db,
                task,
                status="failed",
                failed_count=1,
                error_message=str(exc),
            )
        write_system_log(
            db,
            level="error",
            module="sync",
            message="MediaCrawler sync failed",
            detail={"task_id": task_id, "error": str(exc)},
            related_task_id=task_id,
        )
        db.commit()
    finally:
        db.close()


def _fetch_platform_rows(platform: str, limit: int | None) -> list[dict[str, Any]]:
    table = TABLE_BY_PLATFORM[platform]
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return []

    limit_clause = ""
    if limit and limit > 0:
        limit_clause = f" LIMIT {int(limit)}"

    sql = f"SELECT * FROM `{table}` ORDER BY id DESC{limit_clause}"
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql)).mappings().all()]


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "records", "posts", "notes"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def _insert_payloads(
    db: Session,
    platform: str,
    payloads: list[dict[str, Any]],
    dry_run: bool,
) -> PlatformSyncStats:
    stats = PlatformSyncStats(platform=platform, scanned=len(payloads))
    for payload in payloads:
        try:
            exists = (
                db.query(RawPost)
                .filter(
                    RawPost.platform == payload["platform"],
                    RawPost.external_id == payload["external_id"],
                )
                .first()
            )
            if exists:
                stats.skipped_duplicate += 1
                continue
            if not dry_run:
                db.add(RawPost(**payload))
            stats.inserted += 1
        except Exception as exc:
            stats.failed += 1
            stats.errors.append(str(exc))
    if not dry_run:
        db.commit()
    else:
        db.rollback()
    return stats


def sync_media_to_raw_posts(
    *,
    platforms: Iterable[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    record_task: bool | None = None,
    created_by: str = "system",
) -> SyncResult:
    init_db()
    if not dry_run:
        ensure_wp4_schema()

    task_id = None
    if _should_record_task(dry_run, record_task):
        task_id = _create_task_record(
            task_name="sync MediaCrawler native tables to raw_posts",
            task_type="sync",
            platform=_platform_label(platforms),
            created_by=created_by,
        )

    result = SyncResult()
    db = SessionLocal()
    try:
        for platform in _normalize_platforms(platforms):
            rows = _fetch_platform_rows(platform, limit)
            mapper = MAPPER_BY_PLATFORM[platform]
            payloads = [mapper(row) for row in rows]
            result.results.append(_insert_payloads(db, platform, payloads, dry_run))
        _finish_task_record(task_id, result)
    except Exception as exc:
        _fail_task_record(task_id, exc)
        raise
    finally:
        db.close()
    return result


def sync_json_to_raw_posts(
    *,
    json_path: Path,
    platform: str = "json",
    source_table: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    record_task: bool | None = None,
    created_by: str = "system",
) -> SyncResult:
    init_db()
    if not dry_run:
        ensure_wp4_schema()

    task_id = None
    if _should_record_task(dry_run, record_task):
        task_id = _create_task_record(
            task_name=f"sync JSON data to raw_posts: {json_path.name}",
            task_type="import",
            platform=platform,
            created_by=created_by,
        )

    records = _read_json_records(json_path)
    if limit and limit > 0:
        records = records[:limit]
    source = source_table or f"enhanced:{json_path.name}"

    payloads = [
        _map_json(
            row,
            platform=_as_text(row.get("platform"), platform),
            source_table=source,
        )
        for row in records
    ]
    db = SessionLocal()
    try:
        stats = _insert_payloads(db, platform, payloads, dry_run)
        result = SyncResult(results=[stats])
        _finish_task_record(task_id, result)
        return result
    except Exception as exc:
        _fail_task_record(task_id, exc)
        raise
    finally:
        db.close()


def _print_result(result: SyncResult, dry_run: bool) -> None:
    if dry_run:
        print("[DRY-RUN] no rows were inserted")
    for stats in result.results:
        print(
            f"platform={stats.platform} "
            f"scanned={stats.scanned} "
            f"inserted={stats.inserted} "
            f"skipped_duplicate={stats.skipped_duplicate} "
            f"failed={stats.failed}"
        )
        for error in stats.errors[:5]:
            print(f"  error: {error}")
    print(
        "total "
        f"scanned={result.total_scanned} "
        f"inserted={result.total_inserted} "
        f"skipped_duplicate={result.total_skipped_duplicate} "
        f"failed={result.total_failed}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync collected data into raw_posts")
    parser.add_argument(
        "--platform",
        action="append",
        choices=["all", "xhs", "weibo", "tieba", "json"],
        default=None,
        help="Platform to sync. Use multiple --platform values or all.",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-path", type=Path)
    args = parser.parse_args()

    if args.json_path:
        platform = "json"
        if args.platform and args.platform[-1] not in {"all", "json"}:
            platform = args.platform[-1]
        result = sync_json_to_raw_posts(
            json_path=args.json_path,
            platform=platform,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    else:
        platforms = args.platform or ["all"]
        if "json" in platforms:
            parser.error("--platform json requires --json-path")
        result = sync_media_to_raw_posts(
            platforms=platforms,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    _print_result(result, args.dry_run)
    return 1 if result.total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
