"""将爬虫 JSON 导入 raw_posts 表。用法: python scripts/import_posts.py <json_path>

历史说明：旧实现只写 8 个字段（丢 external_id/计数/关键词），且按 url 去重——
小红书 URL 里的 xsec_token 每次爬取都变，同一帖子会重复入库。现在统一委托给
sync_media_to_raw_posts.sync_json_to_raw_posts：字段映射完备（_map_json 兼容
简化 JSON 和 enhanced JSON），按 (platform, external_id) 去重，与主链路口径一致，
并自动记录 crawl_tasks 任务（后台"运维中心 → 采集任务"可见）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.sync_media_to_raw_posts import sync_json_to_raw_posts  # noqa: E402


def import_file(path: Path) -> int:
    result = sync_json_to_raw_posts(json_path=path, platform="json", created_by="import_posts")
    stats = result.results[0]
    print(
        f"  inserted: {stats.inserted}, skipped (duplicate external_id): {stats.skipped_duplicate}, "
        f"failed: {stats.failed}, total in file: {stats.scanned}"
    )
    for error in stats.errors[:5]:
        print(f"  error: {error}")
    return stats.inserted


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_posts.py <json_path>")
        sys.exit(1)
    path = Path(sys.argv[1])
    n = import_file(path)
    print(f"imported {n} posts from {path}")


if __name__ == "__main__":
    main()
