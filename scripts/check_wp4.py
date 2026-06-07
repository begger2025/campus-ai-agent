"""Work package 4 acceptance checks.

This validates the unified path:
MediaCrawler / enhanced JSONL -> raw_posts -> processed_posts -> OpinionNote.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)


def main() -> int:
    from sqlalchemy import inspect, text

    from agent.opinion_input import load_opinion_notes_from_db
    from backend.database import engine, uses_mysql
    from scripts.process_raw_posts import process_raw_posts
    from scripts.sync_media_to_raw_posts import sync_media_to_raw_posts

    parser = argparse.ArgumentParser(description="Check WP4 data pipeline")
    parser.add_argument("--min-raw", type=int, default=1)
    parser.add_argument("--min-processed", type=int, default=1)
    parser.add_argument("--min-notes", type=int, default=1)
    args = parser.parse_args()

    print("=" * 60)
    print("Work package 4 data pipeline acceptance check")
    print("=" * 60)

    ok = True
    if uses_mysql():
        print("[OK] Using shared MySQL")
    else:
        print("[FAIL] DATABASE_URL must use shared MySQL for WP4 acceptance")
        ok = False

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    required_tables = {
        "xhs_note",
        "weibo_note",
        "tieba_note",
        "raw_posts",
        "processed_posts",
    }
    missing_tables = sorted(required_tables.difference(tables))
    if missing_tables:
        print(f"[FAIL] missing required tables: {', '.join(missing_tables)}")
        ok = False
    else:
        print("[OK] MediaCrawler and main project tables present")

    if "raw_posts" in tables:
        raw_cols = {col["name"] for col in insp.get_columns("raw_posts")}
        if "source_raw_id" in raw_cols:
            print("[OK] raw_posts.source_raw_id present")
        else:
            print("[FAIL] raw_posts.source_raw_id missing")
            ok = False

    if ok:
        dry_result = sync_media_to_raw_posts(platforms=["xhs"], limit=3, dry_run=True)
        if dry_result.total_scanned > 0:
            print(f"[OK] xhs dry-run scanned {dry_result.total_scanned} rows")
        else:
            print("[FAIL] xhs dry-run scanned 0 rows")
            ok = False

        process_result = process_raw_posts(limit=3, dry_run=True)
        print(
            "[OK] raw -> processed dry-run callable "
            f"(scanned={process_result.scanned}, insertable={process_result.inserted})"
        )

    with engine.connect() as conn:
        counts: dict[str, int] = {}
        for table in ["xhs_note", "weibo_note", "tieba_note", "raw_posts", "processed_posts"]:
            if table in tables:
                n = int(conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0)
                counts[table] = n
                print(f"[INFO] {table}: {n} rows")

    raw_count = counts.get("raw_posts", 0)
    processed_count = counts.get("processed_posts", 0)

    if raw_count < args.min_raw:
        print(f"[FAIL] raw_posts has {raw_count} rows, expected >= {args.min_raw}")
        ok = False
    else:
        print(f"[OK] raw_posts row count >= {args.min_raw}")

    if processed_count < args.min_processed:
        print(
            f"[FAIL] processed_posts has {processed_count} rows, "
            f"expected >= {args.min_processed}"
        )
        ok = False
    else:
        print(f"[OK] processed_posts row count >= {args.min_processed}")

    notes = load_opinion_notes_from_db(limit=args.min_notes)
    if len(notes) < args.min_notes:
        print(f"[FAIL] OpinionNote count {len(notes)}, expected >= {args.min_notes}")
        ok = False
    else:
        sample = notes[0]
        missing = [
            name
            for name in ["note_id", "title", "content", "source_keyword"]
            if getattr(sample, name) in (None, "")
        ]
        if sample.heat_score is None:
            missing.append("heat_score")
        if missing:
            print(f"[FAIL] OpinionNote sample missing fields: {', '.join(missing)}")
            ok = False
        else:
            print("[OK] processed_posts can be loaded as OpinionNote")

    print()
    if ok:
        print("WP4 data pipeline checks PASSED.")
        return 0
    print("WP4 data pipeline checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
