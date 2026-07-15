"""user_submissions 建表（幂等，支持 --dry-run）。

用户投稿表（参与感 V2）：投稿是线索，前置审核，通过后写 raw_posts(platform='campus')
进既有管线。语义见 backend/models.py::UserSubmission。
只建这一张表（存在即跳过），绝不 drop、绝不动别的表。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import inspect  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import UserSubmission  # noqa: E402

TABLE = UserSubmission.__tablename__


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="user_submissions 建表（幂等）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    existing = set(inspect(engine).get_table_names())
    if TABLE in existing:
        print(f"[跳过] {TABLE} 已存在（幂等）")
        return 0
    if args.dry_run:
        print(f"[dry-run] 将创建表 {TABLE}（含 status/user_id 索引），不动任何既有表")
        return 0
    UserSubmission.__table__.create(engine)
    created = set(inspect(engine).get_table_names())
    print(f"已创建 {TABLE}；复核：{'在库' if TABLE in created else '缺失！'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
