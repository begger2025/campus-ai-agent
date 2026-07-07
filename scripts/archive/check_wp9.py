"""Work package 9 acceptance checks.

This validates the minimal record system:
crawl_tasks, system_logs, user_feedback, admin_operation_logs,
event_review_logs, and the admin APIs used to inspect them.
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
    parser = argparse.ArgumentParser(description="Check WP9 logs/tasks/feedback")
    parser.add_argument("--admin-username", default="wp9_admin")
    parser.add_argument("--admin-password", default="wp9_admin_password")
    args = parser.parse_args()

    print("=" * 60)
    print("Work package 9 logs, feedback, crawl task acceptance check")
    print("=" * 60)

    ok = True
    try:
        from backend.admin_models import (
            AdminOperationLog,
            CrawlTask,
            EventReviewLog,
            SystemLog,
            UserFeedback,
        )
        from backend.database import SessionLocal, uses_mysql
        from backend.main import app
        from backend.models import PublicEvent
        from backend.routers.admin import (
            FeedbackStatusPatch,
            list_admin_feedback,
            list_admin_operation_logs,
            list_admin_system_logs,
            list_event_review_logs,
            overview,
            update_feedback_status,
        )
        from backend.routers.admin_events import EventStatusPatch, update_event_status
        from backend.routers.feedback import FeedbackRequest, submit_feedback
        from backend.services.auth_service import ensure_user
        from backend.services.log_service import write_system_log
        from scripts.sync_media_to_raw_posts import sync_media_to_raw_posts
    except Exception as exc:
        print(f"[FAIL] WP9 imports failed: {exc}")
        return 1

    ok &= _check(uses_mysql(), "using shared MySQL", "DATABASE_URL is not shared MySQL")

    routes = _route_paths(app)
    required_routes = {
        ("POST", "/api/feedback"),
        ("GET", "/api/admin/crawl-tasks"),
        ("GET", "/api/admin/feedback"),
        ("PATCH", "/api/admin/feedback/{feedback_id}/status"),
        ("GET", "/api/admin/system-logs"),
        ("GET", "/api/admin/operation-logs"),
        ("GET", "/api/admin/events/{event_id}/review-logs"),
    }
    missing_routes = sorted(required_routes.difference(routes))
    ok &= _check(
        not missing_routes,
        "WP9 feedback/log routes registered",
        "missing routes: " + ", ".join(f"{method} {path}" for method, path in missing_routes),
    )

    db = SessionLocal()
    try:
        admin_user = ensure_user(
            db,
            username=args.admin_username,
            password=args.admin_password,
            role="admin",
            display_name="WP9 Admin",
        )
        db.commit()

        before_tasks = db.query(CrawlTask).count()
        sync_result = sync_media_to_raw_posts(
            platforms=["xhs"],
            limit=1,
            dry_run=True,
            record_task=True,
            created_by="wp9_check",
        )
        after_tasks = db.query(CrawlTask).count()
        ok &= _check(
            sync_result.total_scanned >= 0 and after_tasks > before_tasks,
            "sync task writes crawl_tasks record",
            "sync task did not write crawl_tasks record",
        )

        before_feedback = db.query(UserFeedback).count()
        feedback_result = submit_feedback(
            FeedbackRequest(
                feedback_type="content_issue",
                content="WP9 acceptance feedback",
                contact="wp9@example.com",
            ),
            db=db,
        )
        feedback_data = _response_data(feedback_result)
        after_feedback = db.query(UserFeedback).count()
        feedback_id = feedback_data.get("id")
        ok &= _check(
            feedback_id and after_feedback > before_feedback,
            "POST /api/feedback creates pending feedback",
            "POST /api/feedback did not create feedback",
        )

        admin_feedback = _response_data(
            list_admin_feedback(db=db, current_user=admin_user, status="pending", page=1, page_size=20)
        )
        ok &= _check(
            any(item.get("id") == feedback_id for item in admin_feedback.get("items", [])),
            "admin feedback list shows submitted feedback",
            "admin feedback list did not show submitted feedback",
        )

        before_ops = db.query(AdminOperationLog).count()
        if feedback_id:
            update_feedback_status(
                feedback_id,
                FeedbackStatusPatch(status="resolved", handle_note="WP9 acceptance handled"),
                db=db,
                current_user=admin_user,
            )
        after_ops = db.query(AdminOperationLog).count()
        ok &= _check(
            after_ops > before_ops,
            "feedback status update writes admin_operation_logs",
            "feedback status update did not write admin_operation_logs",
        )

        before_logs = db.query(SystemLog).count()
        write_system_log(
            db,
            level="error",
            module="wp9_check",
            message="WP9 acceptance system log",
            detail={"source": "scripts/check_wp9.py"},
            trace_id="wp9-check",
        )
        db.commit()
        after_logs = db.query(SystemLog).count()
        ok &= _check(
            after_logs > before_logs,
            "write_system_log creates system_logs record",
            "write_system_log did not create system_logs record",
        )

        system_logs = _response_data(
            list_admin_system_logs(db=db, current_user=admin_user, level="error", page=1, page_size=20)
        )
        ok &= _check(
            any(item.get("module") == "wp9_check" for item in system_logs.get("items", [])),
            "admin system-logs list shows system log",
            "admin system-logs list did not show system log",
        )

        operation_logs = _response_data(
            list_admin_operation_logs(db=db, current_user=admin_user, page=1, page_size=20)
        )
        ok &= _check(
            isinstance(operation_logs.get("items"), list) and operation_logs.get("total", 0) > 0,
            "admin operation-logs returns operation records",
            "admin operation-logs did not return records",
        )

        event = db.query(PublicEvent).first()
        ok &= _check(event is not None, "public event exists for review-log check", "no public event available")
        if event is not None:
            before_reviews = db.query(EventReviewLog).count()
            next_status = "archived" if event.status == "published" else "published"
            update_event_status(
                event.id,
                EventStatusPatch(status=next_status, review_comment="WP9 acceptance review"),
                db=db,
                current_user=admin_user,
            )
            after_reviews = db.query(EventReviewLog).count()
            review_logs = _response_data(
                list_event_review_logs(event.id, db=db, current_user=admin_user, page=1, page_size=20)
            )
            ok &= _check(
                after_reviews > before_reviews and bool(review_logs.get("items")),
                "event review status change is visible in review logs",
                "event review logs did not record or list status change",
            )

        overview_data = _response_data(overview(db=db, current_user=admin_user))
        ok &= _check(
            "recent_crawl_task" in overview_data
            and "pending_feedback_count" in overview_data
            and "recent_system_errors_count" in overview_data,
            "admin overview includes WP9 operational indicators",
            "admin overview missing WP9 operational indicators",
        )

    finally:
        db.close()

    print()
    if ok:
        print("WP9 logs, feedback, crawl task checks PASSED.")
        return 0
    print("WP9 logs, feedback, crawl task checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
