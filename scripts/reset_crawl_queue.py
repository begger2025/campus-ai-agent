"""分布式协同爬取：重置 crawl_task_queue（回收卡死/失败任务、清完成行）。

用法：
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --requeue-claimed [--platform ks] [--dry-run]
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --requeue-failed
  .venv/Scripts/python.exe scripts/reset_crawl_queue.py --clear-done
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402


def select_target_ids(rows: list[dict[str, Any]], *, requeue_claimed: bool, requeue_failed: bool,
                      clear_done: bool, platform: str | None) -> list[int]:
    """纯逻辑：给定行快照与开关，选出目标 id 列表。"""
    targets: list[int] = []
    for row in rows:
        if platform and row["platform"] != platform:
            continue
        status = row["status"]
        if (requeue_claimed and status == "claimed") or \
           (requeue_failed and status == "failed") or \
           (clear_done and status == "done"):
            targets.append(int(row["id"]))
    return targets


def _load_rows(conn, platform: str | None) -> list[dict[str, Any]]:
    sql = "SELECT id, platform, status FROM crawl_task_queue"
    params: dict[str, Any] = {}
    if platform:
        sql += " WHERE platform=:p"
        params["p"] = platform
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重置 crawl_task_queue")
    parser.add_argument("--requeue-claimed", action="store_true", help="claimed → pending（回收卡死）")
    parser.add_argument("--requeue-failed", action="store_true", help="failed → pending")
    parser.add_argument("--clear-done", action="store_true", help="删除 done 行")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not (args.requeue_claimed or args.requeue_failed or args.clear_done):
        parser.error("需指定 --requeue-claimed / --requeue-failed / --clear-done 至少一个")

    with engine.begin() as conn:
        rows = _load_rows(conn, args.platform)
        target_ids = select_target_ids(
            rows, requeue_claimed=args.requeue_claimed, requeue_failed=args.requeue_failed,
            clear_done=args.clear_done, platform=args.platform,
        )
        print(f"将影响 {len(target_ids)} 行" + (" [dry-run]" if args.dry_run else ""))
        if args.dry_run or not target_ids:
            return 0
        ids_csv = ",".join(str(i) for i in target_ids)
        if args.clear_done:
            conn.execute(text(f"DELETE FROM crawl_task_queue WHERE id IN ({ids_csv})"))
        else:
            conn.execute(text(
                f"UPDATE crawl_task_queue SET status='pending', claimed_by=NULL, "
                f"lease_expires_at=NULL WHERE id IN ({ids_csv})"
            ))
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
