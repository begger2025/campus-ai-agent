"""Work package 5 acceptance checks.

This validates the unified flow:
processed_posts -> public opinion Agent -> public_events/event_post_links
-> admin review -> public users only see published events.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)


def _check(condition: bool, ok_message: str, fail_message: str) -> bool:
    if condition:
        print(f"[OK] {ok_message}")
        return True
    print(f"[FAIL] {fail_message}")
    return False


def _response_data(response: dict) -> dict:
    return response.get("data") or {}


def _route_paths(app) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        for method in methods:
            pairs.add((method, path))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Check WP5 public opinion Agent workflow")
    parser.add_argument("--keyword", default="")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-processed", type=int, default=1)
    args = parser.parse_args()

    print("=" * 60)
    print("Work package 5 public opinion Agent acceptance check")
    print("=" * 60)

    ok = True

    try:
        from backend.agent.public_opinion_core import AnalyzeRequest, PublicOpinionAgentService
        from backend.services.public_opinion_adapter import run_public_opinion_analysis
        from backend.database import SessionLocal, uses_mysql
        from backend.main import app
        from backend.models import EventPostLink, ProcessedPost, PublicEvent
        from backend.admin_models import AgentRunLog, EventReviewLog
        from backend.routers.admin_events import (
            EventStatusPatch,
            list_admin_events,
            update_event_status,
        )
        from backend.routers.api import get_event_detail, list_events
    except Exception as exc:
        print(f"[FAIL] WP5 imports failed: {exc}")
        return 1

    ok &= _check(
        PublicOpinionAgentService is not None and AnalyzeRequest is not None,
        "portable Agent core importable",
        "portable Agent core cannot be imported",
    )
    ok &= _check(uses_mysql(), "using shared MySQL", "DATABASE_URL is not shared MySQL")

    routes = _route_paths(app)
    required_routes = {
        ("POST", "/api/agent/public/analyze"),
        ("GET", "/api/events"),
        ("GET", "/api/events/{event_id}"),
        ("GET", "/api/admin/events"),
        ("GET", "/api/admin/events/{event_id}"),
        ("PATCH", "/api/admin/events/{event_id}/status"),
    }
    missing_routes = sorted(required_routes.difference(routes))
    ok &= _check(
        not missing_routes,
        "WP5 routes registered",
        "missing routes: " + ", ".join(f"{method} {path}" for method, path in missing_routes),
    )

    db = SessionLocal()
    try:
        processed_count = db.query(ProcessedPost).count()
        ok &= _check(
            processed_count >= args.min_processed,
            f"processed_posts row count >= {args.min_processed} ({processed_count})",
            f"processed_posts has {processed_count} rows, expected >= {args.min_processed}",
        )
        if not ok:
            return 1

        preview = run_public_opinion_analysis(
            db,
            keyword=args.keyword,
            limit=args.limit,
            persist=False,
            created_by="wp5_check",
        )
        preview_events = (
            preview.get("payload_preview", {}).get("public_events", [])
            if preview.get("payload_preview")
            else []
        )
        ok &= _check(
            preview.get("input_count", 0) > 0,
            "Agent preview consumed processed_posts",
            "Agent preview input_count is 0",
        )
        ok &= _check(
            preview.get("event_count", 0) > 0,
            f"Agent preview generated {preview.get('event_count', 0)} events",
            "Agent preview generated 0 events",
        )
        ok &= _check(
            all(event.get("status") == "draft" for event in preview_events),
            "new Agent event payloads default to draft",
            "some new Agent event payloads are not draft",
        )
        db.rollback()
        if not ok:
            return 1

        before_events = db.query(PublicEvent).count()
        before_links = db.query(EventPostLink).count()
        before_logs = db.query(AgentRunLog).filter(AgentRunLog.agent_type == "public_opinion").count()

        persisted = run_public_opinion_analysis(
            db,
            keyword=args.keyword,
            limit=args.limit,
            persist=True,
            created_by="wp5_check",
        )
        db.commit()

        after_events = db.query(PublicEvent).count()
        after_links = db.query(EventPostLink).count()
        after_logs = db.query(AgentRunLog).filter(AgentRunLog.agent_type == "public_opinion").count()

        ok &= _check(
            persisted.get("event_count", 0) > 0,
            f"Agent persisted {persisted.get('event_count', 0)} events",
            "Agent persisted 0 events",
        )
        ok &= _check(
            after_events >= before_events and after_events > 0,
            f"public_events available ({after_events})",
            "public_events was not populated",
        )
        ok &= _check(
            after_links > before_links or after_links > 0,
            f"event_post_links available ({after_links})",
            "event_post_links was not populated",
        )
        ok &= _check(
            after_logs > before_logs,
            "agent_run_logs recorded this analysis run",
            "agent_run_logs did not record this analysis run",
        )
        if not ok:
            return 1

        draft_event = db.query(PublicEvent).filter(PublicEvent.status == "draft").first()
        if draft_event is not None:
            before_reviews = db.query(EventReviewLog).count()
            patch_result = update_event_status(
                draft_event.id,
                EventStatusPatch(
                    status="published",
                    reviewed_by="wp5_check_admin",
                    review_comment="WP5 acceptance publish",
                ),
                db=db,
            )
            published_id = _response_data(patch_result).get("id")
            after_reviews = db.query(EventReviewLog).count()
            ok &= _check(
                published_id == draft_event.id,
                f"admin status patch published event {draft_event.id}",
                "admin status patch did not return expected event id",
            )
            ok &= _check(
                after_reviews > before_reviews,
                "event_review_logs recorded the status change",
                "event_review_logs did not record the status change",
            )
        else:
            published = db.query(PublicEvent).filter(PublicEvent.status == "published").first()
            published_id = published.id if published is not None else None
            ok &= _check(
                published_id is not None,
                "no draft event left; existing published event is available for visibility checks",
                "no draft or published event available",
            )
        if not ok or published_id is None:
            return 1

        public_list = list_events(db=db, status=None, page=1, page_size=100)
        public_items = _response_data(public_list).get("items", [])
        ok &= _check(
            all(item.get("status") == "published" for item in public_items),
            "public events list only returns published events",
            "public events list exposed non-published events",
        )

        public_detail = get_event_detail(published_id, db=db)
        detail_data = _response_data(public_detail)
        ok &= _check(
            detail_data.get("status") == "published"
            and isinstance(detail_data.get("representative_posts"), list),
            "public event detail returns published event with representative_posts",
            "public event detail is missing published status or representative_posts",
        )

        admin_list = list_admin_events(db=db, status="all", page=1, page_size=100)
        admin_items = _response_data(admin_list).get("items", [])
        admin_statuses = {item.get("status") for item in admin_items}
        ok &= _check(
            bool(admin_items) and "published" in admin_statuses,
            "admin events list can see reviewed events",
            "admin events list did not return expected events",
        )

    finally:
        db.close()

    print()
    if ok:
        print("WP5 public opinion Agent checks PASSED.")
        return 0
    print("WP5 public opinion Agent checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
