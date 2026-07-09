"""把收集来的真实问题清单灌入 chat_query_log（开发期自举，激活需求/缺口信号）。

用法：
  .venv/Scripts/python.exe scripts/seed_query_log.py --file questions.txt [--user-id seed] [--dry-run]

questions.txt 每行一个问题；空行与 # 开头的行跳过。
设计见 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md 第 7.3 节。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import ChatQueryLog  # noqa: E402
from backend.services.intent_router import route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402


def seed_questions(db, questions, *, user_id: str = "seed", route=route_intent, now: datetime | None = None) -> int:
    """逐条路由提取话题词、统计站内命中，写入提问日志。返回插入条数（不 commit）。"""

    now = now or datetime.utcnow()
    inserted = 0
    for question in questions:
        question = (question or "").strip()
        if not question or question.startswith("#"):
            continue
        routed = route(question)
        keyword = (routed.keyword or "").strip()
        hit_count = len(query_agent_rows(db, keyword=keyword, platforms=None, limit=10)) if keyword else 0
        db.add(
            ChatQueryLog(
                user_id=user_id[:64],
                message=question[:500],
                intent=(routed.intent or "")[:32],
                keyword=keyword[:64],
                hit_count=hit_count,
                created_at=now,
            )
        )
        inserted += 1
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="导入问题清单到 chat_query_log")
    parser.add_argument("--file", required=True, help="问题清单文件，每行一个问题")
    parser.add_argument("--user-id", default="seed")
    parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
    args = parser.parse_args()

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        inserted = seed_questions(db, questions, user_id=args.user_id)
        if args.dry_run:
            db.rollback()
            print(f"[dry-run] 将导入 {inserted} 条提问")
        else:
            db.commit()
            print(f"已导入 {inserted} 条提问到 chat_query_log")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
