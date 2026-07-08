"""
单次采集脚本（可重复执行）。轻量备用链路——主力采集请用 MediaCrawler
（直接写共享库原生表，再用 scripts/sync_media_to_raw_posts.py 入 raw_posts）。

用法:
  .venv\\Scripts\\python.exe crawler\\run_once.py
  .venv\\Scripts\\python.exe crawler\\run_once.py --keyword 校园 --limit 40
  .venv\\Scripts\\python.exe crawler\\run_once.py --demo                  # 纯演示样本
  .venv\\Scripts\\python.exe crawler\\run_once.py --allow-demo-fallback   # 采集不足时允许补 demo

注意：真实采集不足时默认**不再**补充 demo 假数据（防止 example.com 假帖
混入共享库），需要补充必须显式传 --allow-demo-fallback。
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import SAMPLES_DIR, TARGET_MAX, TARGET_MIN  # noqa: E402
from crawler.schema import CrawlPost  # noqa: E402
from crawler.sources import crawl_tieba, crawl_weibo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _demo_posts(count: int = 30) -> list[CrawlPost]:
    """网络受限或平台反爬时的结构化样本，字段与真实采集一致。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seeds = [
        ("weibo", "图书馆期末占座", "期末周图书馆晚七点后人满为患，建议早点占座。"),
        ("weibo", "校运会报名通知", "各学院本周五前完成运动员报名，项目含接力、跳远。"),
        ("weibo", "警惕刷单兼职", "近期有刷单私信，已有同学被骗，请勿轻信。"),
        ("weibo", "课间时间调整讨论", "课间缩短至5分钟后跨楼上课更紧张。"),
        ("weibo", "校园网夜间限速", "宿舍区23点后网速下降，影响提交作业。"),
        ("tieba", "食堂新窗口测评", "二楼轻食窗口排队约20分钟，价格偏高。"),
        ("tieba", "选修课抢课经验", "通识课建议优先选容量大的班，避免候补。"),
        ("tieba", "自习室空调温度", "A栋自习室下午偏冷，可自带外套。"),
        ("tieba", "共享单车停放", "教学楼门口乱停放现象增多，影响通行。"),
        ("tieba", "考研自习占座纠纷", "部分座位长期用书本占座引发讨论。"),
    ]
    posts: list[CrawlPost] = []
    for i in range(count):
        platform, title, content = seeds[i % len(seeds)]
        posts.append(
            CrawlPost(
                id=f"{platform}_demo_{i + 1}",
                platform=platform,
                title=title,
                content=content,
                author=f"user_{i % 5 + 1}",
                publish_time=now,
                url=f"https://example.com/{platform}/demo_{i + 1}",
            )
        )
    return posts


def merge_posts(*groups: list[CrawlPost]) -> list[CrawlPost]:
    seen: set[str] = set()
    merged: list[CrawlPost] = []
    for group in groups:
        for p in group:
            if p.id in seen:
                continue
            seen.add(p.id)
            merged.append(p)
            if len(merged) >= TARGET_MAX:
                return merged
    return merged


def run(keyword: str, limit: int, demo: bool, allow_demo_fallback: bool = False) -> Path:
    issues: list[dict] = []
    mode = "demo"
    weibo_count = tieba_count = 0

    if demo:
        posts = _demo_posts()[:limit]
        issues.append({"code": "E06", "message": "使用 --demo 模式生成结构化样本"})
        logger.info("使用 --demo 模式，生成 %s 条演示数据", len(posts))
    else:
        mode = "live"
        weibo_limit = min(limit, 30)
        tieba_limit = max(TARGET_MIN, limit - weibo_limit)
        weibo_posts = crawl_weibo(keyword=keyword, limit=weibo_limit)
        tieba_posts = crawl_tieba(limit=tieba_limit)
        weibo_count, tieba_count = len(weibo_posts), len(tieba_posts)
        if weibo_count == 0:
            issues.append({"code": "E01", "message": "微博采集 0 条，可能 432 或 Playwright 失败"})
        if tieba_count == 0:
            issues.append({"code": "E03", "message": "贴吧采集 0 条，可能超时或反爬"})
        posts = merge_posts(weibo_posts, tieba_posts)
        if len(posts) < TARGET_MIN:
            # 默认不补假数据：demo 帖（example.com）一旦导入会污染共享库的真实数据。
            if allow_demo_fallback:
                logger.warning("真实采集仅 %s 条，不足 %s，按 --allow-demo-fallback 补充 demo 数据", len(posts), TARGET_MIN)
                mode = "live+demo_fallback"
                issues.append({"code": "E06", "message": f"真实 {len(posts)} 条，已 demo 补足至 {TARGET_MIN}"})
                posts = merge_posts(posts, _demo_posts(TARGET_MIN))
            else:
                logger.warning(
                    "真实采集仅 %s 条（不足 %s）。未补充 demo；如需演示样本请显式使用 --allow-demo-fallback 或 --demo",
                    len(posts), TARGET_MIN,
                )
                issues.append({"code": "E06", "message": f"真实仅 {len(posts)} 条，未启用 demo 补充"})

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = SAMPLES_DIR / f"posts_{stamp}.json"
    crawl_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    payload = {
        "meta": {
            "crawl_time": crawl_time,
            "keyword": keyword,
            "total": len(posts),
            "sources": ["weibo", "tieba"],
            "mode": mode,
            "stats": {"weibo": weibo_count, "tieba": tieba_count},
        },
        "items": [p.to_dict() for p in posts],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = SAMPLES_DIR / f"crawl_report_{stamp}.json"
    report.write_text(
        json.dumps(
            {
                "crawl_time": crawl_time,
                "output": str(out.name),
                "mode": mode,
                "total": len(posts),
                "issues": issues,
                "see_also": "docs/crawl-issues.md",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("已导出 %s 条 -> %s", len(posts), out)
    logger.info("异常摘要 -> %s", report.name)
    return out


def main():
    parser = argparse.ArgumentParser(description="校园舆情单次采集")
    parser.add_argument("--keyword", default="校园", help="微博搜索关键词")
    parser.add_argument("--limit", type=int, default=40, help="目标条数上限")
    parser.add_argument("--demo", action="store_true", help="仅生成演示样本")
    parser.add_argument(
        "--allow-demo-fallback",
        action="store_true",
        help="真实采集不足时允许补充 demo 样本（默认不补，防止假数据入库）",
    )
    args = parser.parse_args()
    out = run(args.keyword, min(args.limit, TARGET_MAX), args.demo, args.allow_demo_fallback)
    print(out)


if __name__ == "__main__":
    main()
