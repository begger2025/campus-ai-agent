"""Generate public opinion events from processed_posts.

This script is the command-line entry for the Week2 smoke chain:
processed_posts -> public opinion Agent -> public_events/event_post_links.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.services.public_opinion_adapter import run_public_opinion_analysis  # noqa: E402


def generate_public_events(
    *,
    keyword: str = "",
    limit: int = 200,
    persist: bool = True,
    created_by: str = "smoke",
    allow_fallback: bool = True,
) -> dict:
    init_db()
    db = SessionLocal()
    try:
        result = run_public_opinion_analysis(
            db,
            keyword=keyword,
            limit=limit,
            persist=persist,
            created_by=created_by,
        )
        if allow_fallback and keyword and result.get("event_count", 0) == 0:
            print(f"[WARN] keyword '{keyword}' generated 0 events; retrying without keyword")
            db.rollback()
            result = run_public_opinion_analysis(
                db,
                keyword="",
                limit=limit,
                persist=persist,
                created_by=created_by,
            )
        if persist:
            db.commit()
        else:
            db.rollback()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate public_events from processed_posts")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--created-by", default="smoke")
    parser.add_argument("--preview", action="store_true", help="Build payloads without database writes")
    parser.add_argument("--no-fallback", action="store_true", help="Do not retry without keyword")
    args = parser.parse_args()

    result = generate_public_events(
        keyword=args.keyword,
        limit=args.limit,
        persist=not args.preview,
        created_by=args.created_by,
        allow_fallback=not args.no_fallback,
    )
    print(
        "[OK] public opinion analysis "
        f"input_count={result.get('input_count')} "
        f"event_count={result.get('event_count')} "
        f"run_log_id={result.get('run_log_id')}"
    )
    warnings = result.get("warnings") or []
    for warning in warnings[:5]:
        print(f"[WARN] {warning}")
    return 0 if result.get("input_count", 0) > 0 and result.get("event_count", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
