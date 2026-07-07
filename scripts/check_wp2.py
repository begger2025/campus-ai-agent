"""Work package 2 schema acceptance checks.

Usage:
  python scripts/check_wp2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)


EXPECTED_COLUMNS = {
    "raw_posts": [
        "id",
        "platform",
        "external_id",
        "source_table",
        "source_raw_id",
        "source_keyword",
        "title",
        "content",
        "author",
        "publish_time",
        "url",
        "raw_url",
        "like_count",
        "collect_count",
        "comment_count",
        "share_count",
        "tags_json",
        "images_json",
        "raw_json",
        "crawl_time",
        "status",
        "created_at",
        "updated_at",
    ],
    "processed_posts": [
        "id",
        "raw_post_id",
        "platform",
        "note_id",
        "title",
        "content",
        "source_keyword",
        "publish_date",
        "publish_time_raw",
        "author_name",
        "tags_json",
        "note_url",
        "raw_note_url",
        "images_json",
        "like_count",
        "collect_count",
        "comment_count",
        "share_count",
        "heat_score",
        "sentiment",
        "sentiment_score",
        "risk_level",
        "risk_score",
        "risk_reasons_json",
        "concerns_json",
        "created_at",
        "updated_at",
    ],
    "public_events": [
        "id",
        "event_key",
        "title",
        "summary",
        "topic",
        "event_type",
        "sentiment",
        "risk_level",
        "risk_score",
        "heat_score",
        "confidence",
        "source_count",
        "date_range_json",
        "source_keywords_json",
        "top_tags_json",
        "concerns_json",
        "risk_reasons_json",
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_comment",
        "created_at",
        "updated_at",
    ],
    "event_post_links": [
        "id",
        "event_id",
        "processed_post_id",
        "raw_post_id",
        "rank",
        "role",
        "created_at",
    ],
    "users": [
        "id",
        "username",
        "password_hash",
        "display_name",
        "role",
        "email",
        "phone",
        "status",
        "last_login_at",
        "created_at",
        "updated_at",
    ],
    "crawl_tasks": [
        "id",
        "task_name",
        "task_type",
        "platform",
        "keyword",
        "status",
        "started_by",
        "started_at",
        "finished_at",
        "total_count",
        "success_count",
        "failed_count",
        "error_message",
        "report_path",
        "created_at",
        "updated_at",
    ],
    "agent_run_logs": [
        "id",
        "agent_type",
        "keyword",
        "input_count",
        "output_count",
        "input_summary",
        "output_summary",
        "status",
        "error_message",
        "duration_ms",
        "created_by",
        "created_at",
    ],
    "event_review_logs": [
        "id",
        "event_id",
        "reviewer_id",
        "old_status",
        "new_status",
        "review_comment",
        "created_at",
    ],
    "admin_operation_logs": [
        "id",
        "admin_user_id",
        "action",
        "target_type",
        "target_id",
        "detail",
        "ip_address",
        "user_agent",
        "created_at",
    ],
    "system_logs": [
        "id",
        "level",
        "module",
        "message",
        "detail",
        "request_id",
        "created_at",
    ],
    "user_feedback": [
        "id",
        "user_id",
        "target_type",
        "target_id",
        "feedback_type",
        "content",
        "status",
        "handled_by",
        "handled_at",
        "handle_note",
        "created_at",
        "updated_at",
    ],
}

OPTIONAL_TABLES = {"system_configs"}
FORBIDDEN_TABLES = {
    "personal_advices",
    "roles",
    "permissions",
    "notifications",
    "user_login_logs",
}
MEDIACRAWLER_TABLES = {
    "xhs_note",
    "xhs_note_comment",
    "weibo_note",
    "weibo_note_comment",
    "tieba_note",
}


def _columns_for(insp, table_name: str) -> list[str]:
    return [col["name"] for col in insp.get_columns(table_name)]


def _has_unique(insp, table_name: str, expected_cols: list[str]) -> bool:
    expected = set(expected_cols)
    for constraint in insp.get_unique_constraints(table_name):
        if set(constraint.get("column_names") or []) == expected:
            return True
    for index in insp.get_indexes(table_name):
        if index.get("unique") and set(index.get("column_names") or []) == expected:
            return True
    return False


def _fk_targets(insp, table_name: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    result = set()
    for fk in insp.get_foreign_keys(table_name):
        result.add(
            (
                tuple(fk.get("constrained_columns") or []),
                fk.get("referred_table") or "",
                tuple(fk.get("referred_columns") or []),
            )
        )
    return result


def main() -> int:
    from sqlalchemy import inspect, text

    from backend import admin_models, models  # noqa: F401
    from backend.database import Base, DATABASE_URL, engine, uses_mysql

    print("=" * 60)
    print("Work package 2 schema acceptance check")
    print("=" * 60)

    ok = True
    if not uses_mysql():
        print("[FAIL] DATABASE_URL must point to shared MySQL, not SQLite.")
        ok = False
    else:
        print("[OK] Using MySQL")

    if "campus_ai_agent" not in DATABASE_URL:
        print("[FAIL] DATABASE_URL should use database campus_ai_agent.")
        ok = False
    else:
        print("[OK] DATABASE_URL uses campus_ai_agent")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    print(f"[INFO] table count: {len(tables)}")

    for table_name, required_cols in EXPECTED_COLUMNS.items():
        if table_name not in tables:
            print(f"[FAIL] missing table: {table_name}")
            ok = False
            continue

        actual_cols = _columns_for(insp, table_name)
        missing = [col for col in required_cols if col not in actual_cols]
        if missing:
            print(f"[FAIL] {table_name} missing columns: {', '.join(missing)}")
            ok = False
        else:
            print(f"[OK] {table_name} required columns present")

        orm_table = Base.metadata.tables.get(table_name)
        if orm_table is None:
            print(f"[FAIL] {table_name} missing in SQLAlchemy ORM")
            ok = False
        else:
            orm_cols = [col.name for col in orm_table.columns]
            db_only = [col for col in actual_cols if col not in orm_cols]
            if db_only:
                print(f"[FAIL] {table_name} DB columns not mapped in ORM: {', '.join(db_only)}")
                ok = False
            else:
                print(f"[OK] {table_name} ORM covers DB columns")

    for table_name in OPTIONAL_TABLES:
        if table_name in tables:
            print(f"[OK] optional table present: {table_name}")
        else:
            print(f"[INFO] optional table not present: {table_name}")

    forbidden_found = sorted(FORBIDDEN_TABLES.intersection(tables))
    if forbidden_found:
        print(f"[FAIL] forbidden/deferred tables present: {', '.join(forbidden_found)}")
        ok = False
    else:
        print("[OK] no forbidden/deferred week-2 tables present")

    if "raw_posts" in tables and _has_unique(insp, "raw_posts", ["platform", "external_id"]):
        print("[OK] raw_posts has UNIQUE(platform, external_id)")
    else:
        print("[FAIL] raw_posts missing UNIQUE(platform, external_id)")
        ok = False

    if "public_events" in tables and _has_unique(insp, "public_events", ["event_key"]):
        print("[OK] public_events has UNIQUE(event_key)")
    else:
        print("[FAIL] public_events missing UNIQUE(event_key)")
        ok = False

    if "event_post_links" in tables:
        fks = _fk_targets(insp, "event_post_links")
        required_fks = {
            (("event_id",), "public_events", ("id",)),
            (("processed_post_id",), "processed_posts", ("id",)),
            (("raw_post_id",), "raw_posts", ("id",)),
        }
        missing_fks = required_fks.difference(fks)
        if missing_fks:
            print(f"[FAIL] event_post_links missing foreign keys: {missing_fks}")
            ok = False
        else:
            print("[OK] event_post_links foreign keys present")

    media_found = sorted(MEDIACRAWLER_TABLES.intersection(tables))
    if media_found:
        print(f"[OK] MediaCrawler sample tables present: {', '.join(media_found)}")
    else:
        print("[WARN] no MediaCrawler sample tables found")

    with engine.connect() as conn:
        for table_name in sorted(EXPECTED_COLUMNS):
            if table_name in tables:
                n = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar()
                print(f"[INFO] {table_name}: {n} rows")

    print()
    if ok:
        print("WP2 schema checks PASSED.")
        return 0
    print("WP2 schema checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
