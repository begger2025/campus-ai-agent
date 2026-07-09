"""把收集来的真实问题清单灌入 chat_query_log（开发期自举，激活需求/缺口信号）。

用法：
  .venv/Scripts/python.exe scripts/seed_query_log.py --file questions.txt [--user-id seed] [--dry-run] [--replace] [--no-llm]

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

# _route_by_rules 是私有函数；开发期 CLI 借它实现 --no-llm 离线路由，属可接受的取舍。
from backend.services.intent_router import _route_by_rules, route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402


def seed_questions(
    db,
    questions,
    *,
    user_id: str = "seed",
    route=route_intent,
    now: datetime | None = None,
    replace: bool = False,
) -> int:
    """逐条路由提取话题词、统计站内命中，写入提问日志。返回插入条数（不 commit）。

    replace=True 时先删除该 user_id 已有的记录，防止重复运行翻倍需求信号。
    """

    user_id = user_id[:64]  # 与列宽一致，保证 replace 删除与插入按同一 user_id 匹配
    if replace:
        db.query(ChatQueryLog).filter(ChatQueryLog.user_id == user_id).delete()

    now = now or datetime.utcnow()
    inserted = 0
    for question in questions:
        question = (question or "").strip()
        if not question or question.startswith("#"):
            continue
        routed = route(question)
        keyword = (routed.keyword or "").strip()
        # 有意的简化：这里 hit_count 数的是 processed_posts 命中（limit 10），聊天端点数的
        # 是展示的事件/笔记数；缺口信号只拿两者判断"数据是否 <3"，口径差异无碍。
        hit_count = len(query_agent_rows(db, keyword=keyword, platforms=None, limit=10)) if keyword else 0
        db.add(
            ChatQueryLog(
                user_id=user_id,
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
    parser.add_argument("--replace", action="store_true", help="先删除该 user-id 已有的种子记录再导入")
    parser.add_argument("--no-llm", action="store_true", help="只用规则路由，不发 LLM 调用")
    args = parser.parse_args()

    route = _route_by_rules if args.no_llm else route_intent
    print(f"路由方式：{'规则（离线）' if args.no_llm else 'LLM 优先（无 key 时自动规则兜底）'}")

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(ChatQueryLog).filter(ChatQueryLog.user_id == args.user_id[:64]).count()
        print(f"该 user-id 已有 {existing} 条记录" + ("（--replace 将先删除）" if args.replace else "（未加 --replace，将追加）"))
        inserted = seed_questions(db, questions, user_id=args.user_id, route=route, replace=args.replace)
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
