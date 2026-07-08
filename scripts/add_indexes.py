"""把 backend 模型声明的索引补到已存在的数据库上（幂等）。

`Base.metadata.create_all` 只建新表，不给已存在的表补索引——本脚本对比
模型声明与库内实际索引，缺哪个建哪个。可重复执行，已存在的跳过。

用法：.venv\\Scripts\\python.exe scripts\\add_indexes.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect  # noqa: E402

from backend import admin_models, models  # noqa: E402,F401 —— 导入即注册表
from backend.database import Base, engine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    created = skipped = 0

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing = {idx["name"] for idx in insp.get_indexes(table.name)}
        # 唯一约束在 MySQL 里也占用索引名
        existing |= {uc["name"] for uc in insp.get_unique_constraints(table.name) if uc.get("name")}
        for index in table.indexes:
            if index.name in existing:
                skipped += 1
                continue
            cols = ", ".join(col.name for col in index.columns)
            print(f"CREATE INDEX {index.name} ON {table.name} ({cols})")
            if not args.dry_run:
                index.create(bind=engine)
            created += 1

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}created={created} skipped(existing)={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
