"""初始化数据库并写入示例数据。用法: python scripts/init_db.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402


def main():
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        print("DB ready:", ROOT / "data" / "campus.db")
    finally:
        db.close()


if __name__ == "__main__":
    main()
