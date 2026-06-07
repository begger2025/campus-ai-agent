"""Work package 10 acceptance checks.

This validates the backend smoke-test handoff:
fixed smoke command, generated public events command, docs, and regression
checks for the public-opinion backend chain.
"""

from __future__ import annotations

import argparse
import subprocess
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _run_smoke(limit: int, port: int) -> bool:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "smoke_backend.py"),
        "--limit",
        str(limit),
        "--port",
        str(port),
        "--admin-username",
        "wp10_admin",
        "--admin-password",
        "wp10_admin_password",
        "--user-username",
        "wp10_user",
        "--user-password",
        "wp10_user_password",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check WP10 backend smoke test handoff")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--port", type=int, default=9010)
    args = parser.parse_args()

    print("=" * 60)
    print("Work package 10 backend smoke test acceptance check")
    print("=" * 60)

    ok = True
    required_files = [
        ROOT / "scripts" / "smoke_backend.py",
        ROOT / "scripts" / "smoke_backend.ps1",
        ROOT / "scripts" / "generate_public_events.py",
        ROOT / "docs" / "backend-smoke-test.md",
        ROOT / "docs" / "api.md",
        ROOT / "docs" / "database.md",
        ROOT / "README.md",
    ]
    for path in required_files:
        ok &= _check(path.exists(), f"file exists: {path.name}", f"missing file: {path}")

    smoke_doc = _read_text(ROOT / "docs" / "backend-smoke-test.md")
    api_doc = _read_text(ROOT / "docs" / "api.md")
    database_doc = _read_text(ROOT / "docs" / "database.md")
    readme = _read_text(ROOT / "README.md")

    ok &= _check(
        "scripts\\smoke_backend.ps1" in smoke_doc
        and "scripts\\generate_public_events.py" in smoke_doc
        and "/api/admin/overview" in smoke_doc,
        "backend smoke doc contains fixed commands and API checks",
        "backend smoke doc is missing fixed commands or API checks",
    )
    ok &= _check(
        "/api/auth/login" in api_doc
        and "/api/feedback" in api_doc
        and "/api/admin/system-logs" in api_doc,
        "api.md documents auth, feedback, and admin log APIs",
        "api.md missing Week2 auth/feedback/admin log APIs",
    )
    ok &= _check(
        "crawl_tasks" in database_doc
        and "system_logs" in database_doc
        and "admin_operation_logs" in database_doc,
        "database.md documents Week2 operational tables",
        "database.md missing Week2 operational tables",
    )
    ok &= _check(
        "第二周后端 Smoke Test" in readme and "smoke_backend.ps1" in readme,
        "README includes Week2 backend smoke test entry",
        "README missing Week2 backend smoke test entry",
    )

    if not ok:
        print()
        print("WP10 static checks FAILED.")
        return 1

    ok &= _check(
        _run_smoke(args.limit, args.port),
        "backend smoke script completed successfully",
        "backend smoke script failed",
    )

    print()
    if ok:
        print("WP10 backend smoke test checks PASSED.")
        return 0
    print("WP10 backend smoke test checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
