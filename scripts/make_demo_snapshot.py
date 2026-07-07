"""把共享 MySQL 的业务数据导出成本地 SQLite 快照（答辩演示降级预案）。

用法（项目根目录）：
    .venv\\Scripts\\python.exe scripts\\make_demo_snapshot.py

生成 data/campus_demo.db；之后运行 demo.bat 即可脱离 MySQL 演示。
只复制 backend 模型声明的表（业务表 + 账号/日志表），不含 MediaCrawler 原生表。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402

from backend import admin_models, models  # noqa: E402,F401 —— 导入即注册表到 Base.metadata
from backend.database import Base, engine as source_engine  # noqa: E402

SNAPSHOT_PATH = ROOT / "data" / "campus_demo.db"


def main() -> int:
    if source_engine.url.get_backend_name() == "sqlite":
        print("当前 DATABASE_URL 已是 SQLite，没有可导出的远端数据源。")
        return 1

    if SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.unlink()
    dest_engine = create_engine(f"sqlite:///{SNAPSHOT_PATH}")
    Base.metadata.create_all(dest_engine)

    total_rows = 0
    with source_engine.connect() as source, dest_engine.begin() as dest:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row._mapping) for row in source.execute(table.select())]
            if rows:
                dest.execute(table.insert(), rows)
            print(f"  {table.name}: {len(rows)} 行")
            total_rows += len(rows)

    print(f"快照完成：{SNAPSHOT_PATH}（共 {total_rows} 行）")
    print("演示时运行 demo.bat 即可脱离共享 MySQL。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
