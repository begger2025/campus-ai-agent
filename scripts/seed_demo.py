"""Insert week-1 demo data into empty local DB. Do NOT run on shared MySQL."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.database import SessionLocal, uses_mysql  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402


def main() -> int:
    if uses_mysql():
        print("[ERROR] seed_demo is for local SQLite only. Shared MySQL must stay empty.")
        return 1
    db = SessionLocal()
    try:
        seed_if_empty(db)
        print("[OK] Demo data inserted if tables were empty.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
