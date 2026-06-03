"""Initialize tables. Shared MySQL: tables only, no demo data.

Usage:
  python scripts/init_db.py              # create empty tables (work package 1)
  python scripts/init_db.py --seed-demo # local SQLite dev only
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.database import DATABASE_URL, SessionLocal, init_db, uses_mysql  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402


def _mask_url(url: str) -> str:
    return re.sub(r":([^:@/]+)@", ":****@", url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create campus_ai_agent tables")
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Insert week-1 demo rows (local dev only, NOT for shared MySQL)",
    )
    args = parser.parse_args()

    print("DATABASE_URL:", _mask_url(DATABASE_URL))

    if args.seed_demo and uses_mysql():
        print("[ERROR] Do not use --seed-demo on shared MySQL (work package 1).")
        sys.exit(1)

    init_db()
    print("[OK] Tables created.")

    if args.seed_demo:
        db = SessionLocal()
        try:
            seed_if_empty(db)
            print("[OK] Demo data seeded (local only).")
        finally:
            db.close()
    else:
        print("[OK] Business tables left empty (no demo seed).")
        if uses_mysql():
            print("     MediaCrawler tables: migrate separately (see docs/work-package-1-shared-mysql.md).")


if __name__ == "__main__":
    main()
