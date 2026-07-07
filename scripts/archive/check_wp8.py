"""Work package 8 acceptance checks.

This validates the minimal administrator backend API:
auth login/me, admin-only dependencies, admin overview, raw post list,
event review with audit logs, crawl task list, and feedback list.
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


def _expect_http_error(func, expected_status: int) -> bool:
    from fastapi import HTTPException

    try:
        func()
    except HTTPException as exc:
        return exc.status_code == expected_status
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check WP8 admin backend API")
    parser.add_argument("--admin-username", default="wp8_admin")
    parser.add_argument("--admin-password", default="wp8_admin_password")
    parser.add_argument("--user-username", default="wp8_user")
    parser.add_argument("--user-password", default="wp8_user_password")
    args = parser.parse_args()

    print("=" * 60)
    print("Work package 8 admin backend API acceptance check")
    print("=" * 60)

    ok = True
    try:
        from backend.admin_models import AdminOperationLog, EventReviewLog, User
        from backend.database import SessionLocal, uses_mysql
        from backend.main import app
        from backend.models import PublicEvent, RawPost
        from backend.routers.admin import (
            list_admin_crawl_tasks,
            list_admin_feedback,
            list_admin_raw_posts,
            overview,
        )
        from backend.routers.admin_events import EventStatusPatch, update_event_status
        from backend.routers.auth import LoginRequest, login, me
        from backend.services.auth_service import (
            ensure_user,
            get_current_user,
            require_admin,
        )
    except Exception as exc:
        print(f"[FAIL] WP8 imports failed: {exc}")
        return 1

    ok &= _check(uses_mysql(), "using shared MySQL", "DATABASE_URL is not shared MySQL")

    routes = _route_paths(app)
    required_routes = {
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/admin/overview"),
        ("GET", "/api/admin/raw-posts"),
        ("GET", "/api/admin/events"),
        ("PATCH", "/api/admin/events/{event_id}/status"),
        ("GET", "/api/admin/crawl-tasks"),
        ("GET", "/api/admin/feedback"),
        ("POST", "/api/agent/public/analyze"),
    }
    missing_routes = sorted(required_routes.difference(routes))
    ok &= _check(
        not missing_routes,
        "WP8 auth/admin routes registered",
        "missing routes: " + ", ".join(f"{method} {path}" for method, path in missing_routes),
    )

    db = SessionLocal()
    try:
        admin_user = ensure_user(
            db,
            username=args.admin_username,
            password=args.admin_password,
            role="admin",
            display_name="WP8 Admin",
        )
        normal_user = ensure_user(
            db,
            username=args.user_username,
            password=args.user_password,
            role="user",
            display_name="WP8 User",
        )
        db.commit()

        ok &= _check(
            _expect_http_error(lambda: get_current_user(authorization=None, db=db), 401),
            "missing token returns 401",
            "missing token did not return 401",
        )
        ok &= _check(
            _expect_http_error(lambda: require_admin(current_user=normal_user), 403),
            "normal user admin access returns 403",
            "normal user admin access did not return 403",
        )

        admin_login = login(
            LoginRequest(username=args.admin_username, password=args.admin_password),
            db=db,
        )
        token = _response_data(admin_login).get("access_token")
        ok &= _check(bool(token), "admin login returns access token", "admin login did not return token")
        current_admin = get_current_user(authorization=f"Bearer {token}", db=db)
        ok &= _check(
            current_admin.username == admin_user.username and current_admin.role == "admin",
            "Bearer token resolves current admin",
            "Bearer token did not resolve current admin",
        )
        ok &= _check(
            _response_data(me(current_user=current_admin)).get("role") == "admin",
            "GET /api/auth/me returns current admin profile",
            "GET /api/auth/me did not return admin profile",
        )

        overview_data = _response_data(overview(db=db, current_user=current_admin))
        ok &= _check(
            "raw_posts_count" in overview_data and "events" in overview_data,
            "admin overview returns dashboard counts",
            "admin overview missing expected counts",
        )

        raw_posts = _response_data(
            list_admin_raw_posts(db=db, current_user=current_admin, page=1, page_size=5)
        )
        raw_count = db.query(RawPost).count()
        ok &= _check(
            raw_posts.get("total", 0) == raw_count and isinstance(raw_posts.get("items"), list),
            "admin raw-posts returns stable paginated structure",
            "admin raw-posts did not return expected structure",
        )

        crawl_tasks = _response_data(
            list_admin_crawl_tasks(db=db, current_user=current_admin, page=1, page_size=5)
        )
        ok &= _check(
            isinstance(crawl_tasks.get("items"), list) and "total" in crawl_tasks,
            "admin crawl-tasks returns stable structure",
            "admin crawl-tasks did not return expected structure",
        )

        feedback = _response_data(
            list_admin_feedback(db=db, current_user=current_admin, page=1, page_size=5)
        )
        ok &= _check(
            isinstance(feedback.get("items"), list) and "total" in feedback,
            "admin feedback returns stable structure",
            "admin feedback did not return expected structure",
        )

        event = (
            db.query(PublicEvent)
            .filter(PublicEvent.status.in_(["draft", "published", "rejected", "archived"]))
            .first()
        )
        ok &= _check(event is not None, "public event exists for status review", "no public event available")
        if event is not None:
            target_status = "archived" if event.status == "published" else "published"
            before_reviews = db.query(EventReviewLog).count()
            before_ops = db.query(AdminOperationLog).count()
            result = update_event_status(
                event.id,
                EventStatusPatch(status=target_status, review_comment="WP8 acceptance status change"),
                db=db,
                current_user=current_admin,
            )
            patch_data = _response_data(result)
            after_reviews = db.query(EventReviewLog).count()
            after_ops = db.query(AdminOperationLog).count()
            ok &= _check(
                patch_data.get("new_status") == target_status,
                "admin event status patch updates event",
                "admin event status patch did not update event",
            )
            ok &= _check(
                after_reviews > before_reviews,
                "event_review_logs records admin review",
                "event_review_logs did not record admin review",
            )
            ok &= _check(
                after_ops > before_ops,
                "admin_operation_logs records status update",
                "admin_operation_logs did not record status update",
            )

    finally:
        db.close()

    print()
    if ok:
        print("WP8 admin backend API checks PASSED.")
        return 0
    print("WP8 admin backend API checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
