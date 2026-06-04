"""Work package 3 route acceptance (uses SQLite, ignores .env MySQL)."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = f"sqlite:///{ROOT / 'data' / 'wp3_test.db'}"
os.environ["SEED_DEMO_ON_START"] = "false"

with patch("dotenv.load_dotenv"):
    from fastapi.testclient import TestClient  # noqa: E402
    from backend.database import init_db  # noqa: E402
    from backend.main import app  # noqa: E402

init_db()
client = TestClient(app)


def check(path: str) -> int:
    r = client.get(path)
    ct = r.headers.get("content-type", "")
    is_json = "json" in ct
    print(f"{path}")
    print(f"  status={r.status_code} content-type={ct} json={is_json}")
    if is_json:
        body = r.json()
        print(f"  code={body.get('code')} message={body.get('message')}")
        data = body.get("data")
        if isinstance(data, dict):
            print(f"  data.keys={sorted(data.keys())}")
    elif "html" in ct:
        print(f"  html_snippet={r.text[:80]!r}")
    return r.status_code


def main() -> int:
    failed = 0
    if check("/api/ping") != 200:
        failed += 1
    if check("/api/posts?page=1&page_size=5") != 200:
        failed += 1
    r = client.get("/api/posts?page=1&page_size=5")
    body = r.json()
    data = body.get("data", {})
    for key in ("items", "total", "page", "page_size"):
        if key not in data:
            print(f"  FAIL missing data.{key}")
            failed += 1
    if "<div id=\"app\">" in r.text:
        print("  FAIL /api/posts returned HTML")
        failed += 1

    old = client.get("/posts?page=1&page_size=5")
    ct = old.headers.get("content-type", "")
    if "json" in ct and old.json().get("code") == 0:
        print("/posts old path still serves API — should use /api/posts")
        failed += 1
    else:
        print(f"/posts old path status={old.status_code} (no longer JSON API — OK)")

    spa = client.get("/events")
    if spa.status_code == 200 and "app" in spa.text.lower():
        print("/events SPA fallback OK")
    else:
        print("  FAIL SPA fallback")
        failed += 1

    print()
    if failed:
        print(f"FAILED {failed} check(s)")
        return 1
    print("ALL WP3 ROUTE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
