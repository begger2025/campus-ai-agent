"""Small additive schema migration needed by work package 4."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import inspect, text

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import engine, uses_mysql  # noqa: E402


def ensure_wp4_schema() -> list[str]:
    """Ensure additive columns required by the WP4 pipeline exist."""

    changed: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "raw_posts" not in tables:
        return changed

    raw_cols = {col["name"] for col in insp.get_columns("raw_posts")}
    if "source_raw_id" in raw_cols:
        return changed

    with engine.begin() as conn:
        if uses_mysql():
            conn.execute(
                text(
                    "ALTER TABLE raw_posts "
                    "ADD COLUMN source_raw_id VARCHAR(255) NOT NULL DEFAULT '' "
                    "AFTER source_table"
                )
            )
        else:
            conn.execute(
                text("ALTER TABLE raw_posts ADD COLUMN source_raw_id VARCHAR(255) DEFAULT ''")
            )
    changed.append("raw_posts.source_raw_id")
    return changed


def main() -> int:
    changed = ensure_wp4_schema()
    if changed:
        print("[OK] added: " + ", ".join(changed))
    else:
        print("[OK] WP4 schema already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
