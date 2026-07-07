"""Verify DATABASE_URL (shared MySQL or local SQLite). Usage: python scripts/verify_db_connection.py"""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)


def _mask_url(url: str) -> str:
    return re.sub(r":([^:@/]+)@", ":****@", url)


def main() -> int:
    from backend.database import DATABASE_URL, engine
    from sqlalchemy import text

    parsed = urlparse(DATABASE_URL.replace("+pymysql", ""))
    driver = parsed.scheme.split("+")[0] if parsed.scheme else "unknown"
    host = parsed.hostname or "(file)"
    port = parsed.port or ""
    database = (parsed.path or "").lstrip("/") or "(default)"

    print("=" * 60)
    print("Campus DB connection check")
    print("=" * 60)
    print(f"DATABASE_URL (masked): {_mask_url(DATABASE_URL)}")
    print(f"driver:   {driver}")
    print(f"host:     {host}")
    print(f"port:     {port or '(default)'}")
    print(f"database: {database}")
    print()

    if driver == "sqlite":
        print("[WARN] Still using SQLite (local campus.db).")
        print("       For work package 0, set DATABASE_URL to shared MySQL in .env")
        print()

    if host in ("localhost", "127.0.0.1") and driver == "mysql":
        print("[WARN] MySQL host is localhost — OK only if DB runs on THIS machine.")
        print("       Other teammates must use the public IP of the shared server.")
        print()

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[OK] SELECT 1 succeeded — database is reachable.")
    except Exception as e:
        print(f"[FAIL] Cannot connect: {e}")
        if driver == "mysql":
            print("Tips: check password, cloud security group port 3306, user host '%'.")
        return 1

    try:
        from sqlalchemy import inspect

        from backend.database import SessionLocal
        from backend.models import RawPost

        insp = inspect(engine)
        names = set(insp.get_table_names())
        for t in ("users", "crawl_tasks", "system_logs"):
            if t in names:
                print(f"[OK] admin table present: {t}")
            elif driver == "mysql":
                print(f"[WARN] missing admin table {t} — run init_db.bat (work package 1)")

        db = SessionLocal()
        try:
            n = db.query(RawPost).count()
            print(f"[OK] raw_posts row count: {n}")
            if driver == "mysql" and n > 0:
                print("[WARN] WP1 expects raw_posts=0 on fresh shared MySQL (no SQLite migration)")
        finally:
            db.close()
    except Exception as e:
        print(f"[WARN] Connected but raw_posts query failed: {e}")
        print("       Backend lead may need to run: init_db.bat")

    print()
    if driver == "mysql" and host not in ("localhost", "127.0.0.1"):
        print("Looks configured for shared MySQL. Work package 0 network check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
