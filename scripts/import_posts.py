"""将爬虫 JSON 导入 raw_posts 表。用法: python scripts/import_posts.py data/samples/posts_xxx.json"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import RawPost  # noqa: E402


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None


def import_file(path: Path) -> int:
    init_db()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        print("no items in file")
        return 0

    db = SessionLocal()
    inserted = skipped = 0
    try:
        for item in items:
            ext_id = item.get("id", "")
            url = item.get("url", "")
            exists = db.query(RawPost).filter(RawPost.url == url).first() if url else None
            if exists:
                skipped += 1
                continue
            db.add(
                RawPost(
                    platform=item["platform"],
                    title=item.get("title") or ext_id,
                    content=item.get("content", ""),
                    author=item.get("author", ""),
                    publish_time=_parse_dt(item.get("publish_time")),
                    url=item.get("url", ""),
                    crawl_time=_parse_dt(item.get("crawl_time")) or datetime.utcnow(),
                )
            )
            inserted += 1
        db.commit()
    finally:
        db.close()
    print(f"  inserted: {inserted}, skipped (duplicate url): {skipped}, total in file: {len(items)}")
    return inserted


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_posts.py <json_path>")
        sys.exit(1)
    path = Path(sys.argv[1])
    n = import_file(path)
    print(f"imported {n} posts from {path}")


if __name__ == "__main__":
    main()
