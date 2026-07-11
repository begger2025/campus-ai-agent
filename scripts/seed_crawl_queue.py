"""分布式协同爬取：向 crawl_task_queue 播种任务（双来源：智能选题推荐 / 手动）。

用法：
  # 手动关键词，平台 × 关键词笛卡尔积
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks,zhihu --keywords "宿舍,食堂"
  # 从智能选题推荐取 top-N 灌单平台
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks --from-recommendations --top 20
  # 预览不写
  .venv/Scripts/python.exe scripts/seed_crawl_queue.py --platform ks --keywords "宿舍" --dry-run

去重：只跳过当前 status ∈ {pending, claimed} 的 (platform, keyword)；done/failed 过的可重入队。
设计见 docs/superpowers/specs/2026-07-11-distributed-crawl-design.md §5。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import SessionLocal, engine  # noqa: E402
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions  # noqa: E402

VALID_PLATFORMS = {"xhs", "wb", "tieba", "zhihu", "ks"}


def parse_platforms(raw: str) -> list[str]:
    items = [p.strip() for p in str(raw).split(",") if p.strip()]
    bad = [p for p in items if p not in VALID_PLATFORMS]
    if bad:
        raise ValueError(f"unsupported platform(s): {bad}; valid={sorted(VALID_PLATFORMS)}")
    # 去重保序
    seen: list[str] = []
    for p in items:
        if p not in seen:
            seen.append(p)
    return seen


def _clean_keywords(keywords: Iterable[str]) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        k = str(kw or "").strip()
        if k and k not in out:
            out.append(k)
    return out


def build_seed_rows(platforms: list[str], keywords: Iterable[str], priority: int, now_ms: int) -> list[dict[str, Any]]:
    """平台 × 关键词笛卡尔积 → pending 行（关键词内部去重）。纯逻辑。"""
    kws = _clean_keywords(keywords)
    rows: list[dict[str, Any]] = []
    for platform in platforms:
        for kw in kws:
            rows.append({
                "platform": platform,
                "keyword": kw,
                "status": "pending",
                "priority": int(priority),
                "created_at": int(now_ms),
            })
    return rows


def filter_new_rows(candidate_rows: list[dict[str, Any]], active_pairs: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """去重：跳过当前 pending/claimed 的 (platform, keyword)。纯逻辑。"""
    return [r for r in candidate_rows if (r["platform"], r["keyword"]) not in active_pairs]


def _load_active_pairs(conn) -> set[tuple[str, str]]:
    rows = conn.execute(text(
        "SELECT platform, keyword FROM crawl_task_queue WHERE status IN ('pending','claimed')"
    )).all()
    return {(r[0], r[1]) for r in rows}


def _recommendation_keywords(top: int) -> list[str]:
    db = SessionLocal()
    try:
        result = get_keyword_suggestions(db, days=30, top=top)
    finally:
        db.close()
    return [s.get("keyword") for s in result.get("suggestions", []) if s.get("keyword")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="向 crawl_task_queue 播种任务")
    parser.add_argument("--platform", required=True, help="平台码，逗号分隔（xhs,wb,tieba,zhihu,ks）")
    parser.add_argument("--keywords", default="", help="手动关键词，逗号分隔")
    parser.add_argument("--from-recommendations", action="store_true", help="从智能选题推荐取关键词")
    parser.add_argument("--top", type=int, default=10, help="推荐取 top-N（配合 --from-recommendations）")
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    platforms = parse_platforms(args.platform)
    keywords = _clean_keywords(args.keywords.split(",")) if args.keywords else []
    if args.from_recommendations:
        keywords += _recommendation_keywords(args.top)
    keywords = _clean_keywords(keywords)
    if not keywords:
        parser.error("no keywords (use --keywords and/or --from-recommendations)")

    now_ms = int(time.time() * 1000)
    candidate = build_seed_rows(platforms, keywords, args.priority, now_ms)

    with engine.begin() as conn:
        active = _load_active_pairs(conn)
        new_rows = filter_new_rows(candidate, active)
        skipped = len(candidate) - len(new_rows)
        print(f"候选 {len(candidate)} 条，跳过已在队列 {skipped} 条，待插入 {len(new_rows)} 条")
        if args.dry_run:
            for r in new_rows:
                print(f"  [dry-run] {r['platform']} / {r['keyword']} (priority={r['priority']})")
            return 0
        for r in new_rows:
            conn.execute(text(
                "INSERT INTO crawl_task_queue (platform, keyword, status, priority, created_at) "
                "VALUES (:platform, :keyword, :status, :priority, :created_at)"
            ), r)
    print(f"完成：插入 {len(new_rows)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
