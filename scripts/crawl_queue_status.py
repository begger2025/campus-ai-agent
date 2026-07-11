"""分布式协同爬取：监控 crawl_task_queue（按平台汇总 + claimed 明细 + 卡死提示）。

用法：.venv/Scripts/python.exe scripts/crawl_queue_status.py [--platform ks]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.database import engine  # noqa: E402

_STATUSES = ("pending", "claimed", "done", "failed")


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """按平台聚合各状态计数。纯逻辑。"""
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        platform = row["platform"]
        bucket = summary.setdefault(platform, {s: 0 for s in _STATUSES})
        status = row["status"]
        if status in bucket:
            bucket[status] += 1
    return summary


def _load_rows(conn, platform: str | None) -> list[dict[str, Any]]:
    sql = "SELECT id, platform, keyword, status, claimed_by, lease_expires_at FROM crawl_task_queue"
    params: dict[str, Any] = {}
    if platform:
        sql += " WHERE platform=:p"
        params["p"] = platform
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="监控 crawl_task_queue")
    parser.add_argument("--platform", default=None)
    args = parser.parse_args(argv)

    now_ms = int(time.time() * 1000)
    with engine.connect() as conn:
        rows = _load_rows(conn, args.platform)

    summary = summarize(rows)
    print("=== 队列汇总（按平台）===")
    for platform in sorted(summary):
        c = summary[platform]
        print(f"  {platform}: pending={c['pending']} claimed={c['claimed']} done={c['done']} failed={c['failed']}")

    claimed = [r for r in rows if r["status"] == "claimed"]
    if claimed:
        print("\n=== 认领中（claimed）===")
        for r in claimed:
            stuck = " [卡死待回收]" if (r["lease_expires_at"] or 0) < now_ms else ""
            print(f"  #{r['id']} {r['platform']} / {r['keyword']} by {r['claimed_by']}{stuck}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
