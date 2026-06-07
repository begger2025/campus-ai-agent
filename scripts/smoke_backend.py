"""Week2 backend smoke test for the public-opinion chain.

The script uses existing MediaCrawler data or a deterministic fixture,
starts a temporary backend server when needed, and checks real HTTP endpoints.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.admin_models import (  # noqa: E402
    AdminOperationLog,
    AgentRunLog,
    CrawlTask,
    EventReviewLog,
    SystemLog,
    UserFeedback,
)
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import ProcessedPost, PublicEvent, RawPost  # noqa: E402
from backend.services.auth_service import ensure_user  # noqa: E402
from backend.services.log_service import write_system_log  # noqa: E402
from scripts.generate_public_events import generate_public_events  # noqa: E402
from scripts.process_raw_posts import process_raw_posts  # noqa: E402
from scripts.sync_media_to_raw_posts import sync_media_to_raw_posts  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def _ok(message: str) -> None:
    print(f"[OK] {message}")


def _fail(message: str) -> None:
    print(f"[FAIL] {message}")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def _count(model) -> int:
    db = SessionLocal()
    try:
        return db.query(model).count()
    finally:
        db.close()


def _first_event_id() -> int:
    db = SessionLocal()
    try:
        event = db.query(PublicEvent).order_by(PublicEvent.id.asc()).first()
        if event is None:
            raise SmokeFailure("public_events is empty")
        return event.id
    finally:
        db.close()


def _ensure_smoke_users(
    admin_username: str,
    admin_password: str,
    user_username: str,
    user_password: str,
) -> None:
    db = SessionLocal()
    try:
        ensure_user(
            db,
            username=admin_username,
            password=admin_password,
            role="admin",
            display_name="Smoke Admin",
        )
        ensure_user(
            db,
            username=user_username,
            password=user_password,
            role="user",
            display_name="Smoke User",
        )
        db.commit()
    finally:
        db.close()


def _ensure_fixture_raw_post() -> None:
    """Create one deterministic raw post if no source data exists."""

    db = SessionLocal()
    try:
        if db.query(RawPost).count() > 0:
            return
        row = RawPost(
            platform="fixture",
            external_id="smoke-fixture-001",
            source_table="smoke_fixture",
            source_raw_id="smoke-fixture-001",
            source_keyword="campus",
            title="Campus hot water maintenance feedback",
            content=(
                "Students reported unstable dormitory hot water service. "
                "The logistics office should repair it and publish progress."
            ),
            author="smoke",
            publish_time=datetime.utcnow(),
            url="https://example.com/smoke-fixture-001",
            raw_url="https://example.com/smoke-fixture-001",
            like_count=12,
            collect_count=3,
            comment_count=8,
            share_count=1,
            tags_json='["dormitory","hot_water","logistics"]',
            images_json="[]",
            raw_json="{}",
            crawl_time=datetime.utcnow(),
            status="normal",
        )
        db.add(row)
        db.commit()
        _ok("created fixture raw_post because no source data existed")
    finally:
        db.close()


def _http_get_json(
    base_url: str,
    path: str,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict:
    response = requests.get(f"{base_url}{path}", headers=headers, timeout=20)
    _assert(
        response.status_code == expected_status,
        f"GET {path} expected {expected_status}, got {response.status_code}: {response.text[:200]}",
    )
    if not response.text:
        return {}
    return response.json()


def _http_post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict:
    response = requests.post(f"{base_url}{path}", json=payload, headers=headers, timeout=20)
    _assert(
        response.status_code == expected_status,
        f"POST {path} expected {expected_status}, got {response.status_code}: {response.text[:200]}",
    )
    return response.json()


def _http_patch_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict:
    response = requests.patch(f"{base_url}{path}", json=payload, headers=headers, timeout=20)
    _assert(
        response.status_code == expected_status,
        f"PATCH {path} expected {expected_status}, got {response.status_code}: {response.text[:200]}",
    )
    return response.json()


def _server_alive(base_url: str) -> bool:
    try:
        response = requests.get(f"{base_url}/health", timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _start_server_if_needed(port: int) -> tuple[subprocess.Popen | None, str]:
    base_url = f"http://127.0.0.1:{port}"
    if _server_alive(base_url):
        _ok(f"backend already running at {base_url}")
        return None, base_url

    env = os.environ.copy()
    env["APP_HOST"] = "127.0.0.1"
    env["APP_PORT"] = str(port)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(60):
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise SmokeFailure(f"backend server exited early\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        if _server_alive(base_url):
            _ok(f"started temporary backend at {base_url}")
            return process, base_url
        time.sleep(0.5)
    process.terminate()
    raise SmokeFailure(f"backend did not become ready at {base_url}")


def _stop_server(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def _verify_response_shape(name: str, payload: dict, *, expect_items: bool = False) -> None:
    _assert(payload.get("code") == 0, f"{name} code must be 0")
    _assert(payload.get("message") == "ok", f"{name} message must be ok")
    _assert("data" in payload, f"{name} must contain data")
    if expect_items:
        data = payload.get("data") or {}
        _assert(isinstance(data.get("items"), list), f"{name}.data.items must be list")
        _assert("total" in data and "page" in data and "page_size" in data, f"{name} missing pagination")


def _run_data_chain(limit: int, keyword: str) -> None:
    init_db()
    _ok("init database")

    sync_result = sync_media_to_raw_posts(
        platforms=["all"],
        limit=limit,
        dry_run=False,
        record_task=True,
        created_by="smoke",
    )
    _ok(
        "sync media to raw_posts: "
        f"scanned={sync_result.total_scanned}, inserted={sync_result.total_inserted}, "
        f"failed={sync_result.total_failed}"
    )

    _ensure_fixture_raw_post()
    _assert(_count(RawPost) > 0, "raw_posts must have rows after sync or fixture")

    process_result = process_raw_posts(
        limit=limit,
        dry_run=False,
        record_task=True,
        created_by="smoke",
    )
    _ok(
        "process raw_posts: "
        f"scanned={process_result.scanned}, inserted={process_result.inserted}, "
        f"failed={process_result.failed}"
    )
    _assert(_count(ProcessedPost) > 0, "processed_posts must have rows after processing")

    agent_result = generate_public_events(
        keyword=keyword,
        limit=limit,
        persist=True,
        created_by="smoke",
        allow_fallback=True,
    )
    _ok(
        "generate public_events: "
        f"input_count={agent_result.get('input_count')}, "
        f"event_count={agent_result.get('event_count')}, "
        f"run_log_id={agent_result.get('run_log_id')}"
    )
    _assert(_count(PublicEvent) > 0, "public_events must have rows after Agent analysis")

    db = SessionLocal()
    try:
        write_system_log(
            db,
            level="info",
            module="smoke",
            message="backend smoke test reached database checkpoint",
            detail={"limit": limit, "keyword": keyword},
            trace_id="wp10-smoke",
        )
        db.commit()
    finally:
        db.close()

    _assert(_count(CrawlTask) > 0, "crawl_tasks must have task records")
    _assert(_count(AgentRunLog) > 0, "agent_run_logs must have records")


def _run_http_chain(
    *,
    base_url: str,
    admin_username: str,
    admin_password: str,
    user_username: str,
    user_password: str,
) -> None:
    health = _http_get_json(base_url, "/health")
    _assert(health.get("status") == "ok", "/health status must be ok")
    _ok("GET /health")

    posts = _http_get_json(base_url, "/api/posts?page=1&page_size=5")
    _verify_response_shape("GET /api/posts", posts, expect_items=True)
    _ok("GET /api/posts")

    public_events = _http_get_json(base_url, "/api/events?page=1&page_size=5")
    _verify_response_shape("GET /api/events", public_events, expect_items=True)
    for item in (public_events.get("data") or {}).get("items", []):
        _assert(item.get("status") == "published", "public events endpoint exposed non-published event")
    _ok("GET /api/events")

    response = requests.get(f"{base_url}/api/admin/overview", timeout=20)
    _assert(response.status_code == 401, f"admin overview without token expected 401, got {response.status_code}")
    _ok("admin overview without token -> 401")

    user_login = _http_post_json(
        base_url,
        "/api/auth/login",
        {"username": user_username, "password": user_password},
    )
    user_token = ((user_login.get("data") or {}).get("access_token") or "")
    _assert(user_token, "normal user login must return token")
    response = requests.get(
        f"{base_url}/api/admin/overview",
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=20,
    )
    _assert(response.status_code == 403, f"admin overview with user token expected 403, got {response.status_code}")
    _ok("admin overview with normal user token -> 403")

    admin_login = _http_post_json(
        base_url,
        "/api/auth/login",
        {"username": admin_username, "password": admin_password},
    )
    admin_token = ((admin_login.get("data") or {}).get("access_token") or "")
    _assert(admin_token, "admin login must return token")
    headers = {"Authorization": f"Bearer {admin_token}"}
    _ok("POST /api/auth/login")

    overview = _http_get_json(base_url, "/api/admin/overview", headers=headers)
    _verify_response_shape("GET /api/admin/overview", overview)
    overview_data = overview.get("data") or {}
    for field in ("raw_posts_count", "processed_posts_count", "events", "crawl_tasks", "feedback"):
        _assert(field in overview_data, f"admin overview missing {field}")
    _ok("GET /api/admin/overview")

    event_id = _first_event_id()
    before_reviews = _count(EventReviewLog)
    before_ops = _count(AdminOperationLog)
    _http_patch_json(
        base_url,
        f"/api/admin/events/{event_id}/status",
        {"status": "published", "review_comment": "WP10 smoke test publish"},
        headers=headers,
    )
    _assert(_count(EventReviewLog) > before_reviews, "event_review_logs did not increase after publish")
    _assert(_count(AdminOperationLog) > before_ops, "admin_operation_logs did not increase after publish")
    _ok(f"PATCH /api/admin/events/{event_id}/status")

    public_events_after = _http_get_json(base_url, "/api/events?page=1&page_size=5")
    _verify_response_shape("GET /api/events after publish", public_events_after, expect_items=True)
    _assert((public_events_after.get("data") or {}).get("total", 0) > 0, "published events should be visible")
    for item in (public_events_after.get("data") or {}).get("items", []):
        _assert(item.get("status") == "published", "public events endpoint exposed non-published event")
    _ok("GET /api/events shows published events only")

    feedback = _http_post_json(
        base_url,
        "/api/feedback",
        {
            "feedback_type": "content_issue",
            "content": "WP10 smoke test feedback",
            "contact": "wp10@example.com",
        },
    )
    _verify_response_shape("POST /api/feedback", feedback)
    _assert((feedback.get("data") or {}).get("id"), "feedback response missing id")
    _ok("POST /api/feedback")

    feedback_list = _http_get_json(base_url, "/api/admin/feedback?page=1&page_size=5", headers=headers)
    _verify_response_shape("GET /api/admin/feedback", feedback_list, expect_items=True)
    _assert((feedback_list.get("data") or {}).get("total", 0) > 0, "admin feedback should have rows")
    _ok("GET /api/admin/feedback")

    system_logs = _http_get_json(base_url, "/api/admin/system-logs?page=1&page_size=5", headers=headers)
    _verify_response_shape("GET /api/admin/system-logs", system_logs, expect_items=True)
    _assert((system_logs.get("data") or {}).get("total", 0) > 0, "admin system logs should have rows")
    _ok("GET /api/admin/system-logs")

    operation_logs = _http_get_json(base_url, "/api/admin/operation-logs?page=1&page_size=5", headers=headers)
    _verify_response_shape("GET /api/admin/operation-logs", operation_logs, expect_items=True)
    _assert((operation_logs.get("data") or {}).get("total", 0) > 0, "admin operation logs should have rows")
    _ok("GET /api/admin/operation-logs")

    review_logs = _http_get_json(base_url, f"/api/admin/events/{event_id}/review-logs", headers=headers)
    _verify_response_shape("GET /api/admin/events/{event_id}/review-logs", review_logs, expect_items=True)
    _assert((review_logs.get("data") or {}).get("total", 0) > 0, "event review logs should have rows")
    _ok(f"GET /api/admin/events/{event_id}/review-logs")

    _assert(_count(UserFeedback) > 0, "user_feedback must have records")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Week2 backend smoke test")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--keyword", default="campus")
    parser.add_argument("--port", type=int, default=9010)
    parser.add_argument("--admin-username", default="smoke_admin")
    parser.add_argument("--admin-password", default="smoke_admin_password")
    parser.add_argument("--user-username", default="smoke_user")
    parser.add_argument("--user-password", default="smoke_user_password")
    args = parser.parse_args()

    server_process = None
    try:
        _run_data_chain(args.limit, args.keyword)
        _ensure_smoke_users(
            args.admin_username,
            args.admin_password,
            args.user_username,
            args.user_password,
        )
        server_process, base_url = _start_server_if_needed(args.port)
        _run_http_chain(
            base_url=base_url,
            admin_username=args.admin_username,
            admin_password=args.admin_password,
            user_username=args.user_username,
            user_password=args.user_password,
        )

        print(
            "[OK] database counts "
            f"raw_posts={_count(RawPost)} "
            f"processed_posts={_count(ProcessedPost)} "
            f"public_events={_count(PublicEvent)} "
            f"crawl_tasks={_count(CrawlTask)} "
            f"agent_run_logs={_count(AgentRunLog)} "
            f"event_review_logs={_count(EventReviewLog)} "
            f"admin_operation_logs={_count(AdminOperationLog)} "
            f"user_feedback={_count(UserFeedback)}"
        )
        print("[OK] Week2 backend smoke test PASSED")
        return 0
    except Exception as exc:
        _fail(str(exc))
        return 1
    finally:
        _stop_server(server_process)


if __name__ == "__main__":
    raise SystemExit(main())
