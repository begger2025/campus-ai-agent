"""Work package 1 acceptance checks. Usage: python scripts/check_wp1.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

BUSINESS_TABLES = [
    "raw_posts",
    "processed_posts",
    "public_events",
    "user_tasks",
    "user_schedules",
]
ADMIN_TABLES = [
    "users",
    "crawl_tasks",
    "agent_run_logs",
    "event_review_logs",
    "admin_operation_logs",
    "system_logs",
    "user_feedback",
]
MEDIACRAWLER_SAMPLES = [
    "xhs_note",
    "weibo_note",
    "tieba_note",
]


def main() -> int:
    from sqlalchemy import inspect, text

    from backend.database import DATABASE_URL, engine, uses_mysql

    print("=" * 60)
    print("Work package 1 acceptance check")
    print("=" * 60)

    ok = True

    if not uses_mysql():
        print("[FAIL] DATABASE_URL must be mysql+pymysql://... (not SQLite)")
        ok = False
    else:
        print("[OK] Using MySQL")

    if "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL:
        print("[WARN] Host is localhost — teammates must use shared public IP")

    insp = inspect(engine)
    tables = set(insp.get_table_names())

    for t in BUSINESS_TABLES + ADMIN_TABLES:
        if t not in tables:
            print(f"[FAIL] Missing table: {t}")
            ok = False
        else:
            print(f"[OK] Table exists: {t}")

    with engine.connect() as conn:
        for t in BUSINESS_TABLES:
            if t not in tables:
                continue
            n = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
            if n != 0:
                print(f"[FAIL] {t} must be 0 rows for WP1, got {n}")
                ok = False
            else:
                print(f"[OK] {t} = 0 rows")

        mc_found = [t for t in MEDIACRAWLER_SAMPLES if t in tables]
        if mc_found:
            for t in mc_found:
                n = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
                print(f"[INFO] MediaCrawler table {t}: {n} rows")
        else:
            print("[WARN] No MediaCrawler sample tables yet (xhs_note / weibo_note / tieba_note)")
            print("       Crawler lead should mysqldump media_crawler -> campus_ai_agent")

    print()
    if ok:
        print("WP1 backend checks PASSED (main project empty tables + schema).")
    else:
        print("WP1 backend checks FAILED — fix items above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
