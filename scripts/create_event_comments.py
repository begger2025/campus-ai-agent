"""event_comments 建表（幂等，支持 --dry-run）。

用法：
  .venv/Scripts/python.exe scripts/create_event_comments.py --dry-run   # 只报告
  .venv/Scripts/python.exe scripts/create_event_comments.py             # 真正执行

站内评论表（参与感 V1）：登录用户对已发布事件的讨论。身份=平台第一方 UGC
（不进 raw/processed，不走事件审核闸门），管控=前置自动挡+后置举报/隐藏。
V1 刻意不进聚类/LLM 语料（防自产自销回路），语义见 backend/models.py::EventComment。

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
from backend.models import EventComment  # noqa: E402

TABLE = EventComment.__tablename__


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="event_comments 建表（幂等）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    existing = set(inspect(engine).get_table_names())
    if TABLE in existing:
        print(f"[跳过] {TABLE} 已存在（幂等）")
        return 0
    if args.dry_run:
        print(f"[dry-run] 将创建表 {TABLE}（含 event_id/status 两个索引），不动任何既有表")
        return 0
    EventComment.__table__.create(engine)
    print(f"已创建 {TABLE}")
    created = set(inspect(engine).get_table_names())
    print(f"复核：{TABLE} {'在库' if TABLE in created else '缺失！'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
