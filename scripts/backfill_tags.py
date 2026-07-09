"""存量 tags_json 回填/归一化：xhs 字典标签转名字数组、微博补 #话题#、贴吧补吧名。

用法：
  .venv/Scripts/python.exe scripts/backfill_tags.py [--dry-run]

幂等：已是目标格式的行不会重复更新。raw_posts 与 processed_posts 双表同步更新。
设计见 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md 第 9 节。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import ProcessedPost, RawPost  # noqa: E402
from scripts.sync_media_to_raw_posts import extract_weibo_topics, normalize_xhs_tag_list  # noqa: E402


@dataclass
class BackfillResult:
    scanned: int = 0
    updated: int = 0


def _target_tags(raw: RawPost) -> list[str]:
    if raw.platform == "xhs":
        return normalize_xhs_tag_list(raw.tags_json)
    if raw.platform == "weibo":
        return extract_weibo_topics(raw.content)
    if raw.platform == "tieba":
        try:
            raw_row = json.loads(raw.raw_json or "{}")
        except (TypeError, ValueError):
            raw_row = {}
        name = str(raw_row.get("tieba_name") or "").strip()
        return [name] if name else []
    return []


def backfill_tags(db) -> BackfillResult:
    """逐行计算目标 tags_json，与现值不同才更新（含对应 processed_posts 行）。"""

    result = BackfillResult()
    processed_by_raw_id = {
        p.raw_post_id: p for p in db.query(ProcessedPost).all()
    }
    for raw in db.query(RawPost).filter(RawPost.platform.in_(["xhs", "weibo", "tieba"])).all():
        result.scanned += 1
        tags = _target_tags(raw)
        target = json.dumps(tags, ensure_ascii=False) if tags else ""
        if (raw.tags_json or "") == target:
            continue
        raw.tags_json = target
        processed = processed_by_raw_id.get(raw.id)
        if processed is not None:
            processed.tags_json = target
        result.updated += 1
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="存量 tags_json 回填/归一化")
    parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        result = backfill_tags(db)
        if args.dry_run:
            db.rollback()
            print(f"[dry-run] 扫描 {result.scanned} 行，将更新 {result.updated} 行")
        else:
            db.commit()
            print(f"扫描 {result.scanned} 行，已更新 {result.updated} 行（raw_posts + processed_posts）")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
