"""联网证据采集：命令行入口（可直接读爬取队列里的关键词）。

爬虫拿到的是学生的声音（小红书/微博/知乎/快手），联网检索拿到的是**爬虫结构上够不着的
官方通知与新闻**（zwc.sysu.edu.cn、jwb.sysu.edu.cn、news.sysu.edu.cn…）。两者互补，
所以最自然的用法是：**每次爬取之前，用同一批关键词先跑一遍联网检索。**

用法：
  # 直接用 crawl_task_queue 里 pending 的关键词（与本轮爬取同题）
  .venv/Scripts/python.exe scripts/collect_evidence.py --from-queue --topic "校园舆情"
  # 手动关键词
  .venv/Scripts/python.exe scripts/collect_evidence.py --keywords "食堂,宿舍搬迁"
  # 预览：打印将要检索什么，零 LLM 调用、零数据库写入
  .venv/Scripts/python.exe scripts/collect_evidence.py --from-queue --dry-run

本脚本**只采集 + 抓取核验**，绝不自动审批、绝不写 raw_posts：交付到 raw_posts 需要
in_scope + verified + 人工 approved 三个条件，人工那一道闸门是这个功能的设计核心
（见 docs/evidence-collector.md §7）。审批请到后台管理 → 证据采集。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from sqlalchemy import text  # noqa: E402

from backend.services.evidence.schemas import (  # noqa: E402
    SCOPE_DECISIONS,
    VERIFICATION_STATUSES,
)

DEFAULT_TOPIC = "中山大学校园舆情（联网检索）"
DEFAULT_MAX_RESULTS = 10
ADMIN_PAGE_HINT = "后台管理 → 证据采集（AdminEvidenceView）"


@dataclass
class KeywordSummary:
    """一个关键词这一轮的战果；``citations == 0`` 本身就是结论，必须照实报出来。"""

    keyword: str
    citations: int
    scope: dict[str, int]
    verification: dict[str, int]
    rejection_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 纯逻辑


def load_pending_keywords(conn, platform: str | None = None) -> list[str]:
    """队列里 **pending** 任务的去重关键词（保持入队顺序）。

    只取 pending：claimed 的任务已经被某台机器领走开爬了，done/failed 是历史。
    多个平台同一个关键词只检索一次——联网检索不分平台。
    """

    sql = "SELECT keyword FROM crawl_task_queue WHERE status='pending'"
    params: dict[str, Any] = {}
    if platform:
        sql += " AND platform=:p"
        params["p"] = platform
    sql += " ORDER BY id ASC"
    rows = conn.execute(text(sql), params).all()
    return _dedup(row[0] for row in rows)


def _dedup(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def resolve_keywords(explicit: str, queue_keywords: Sequence[str]) -> list[str]:
    """手动关键词在前、队列关键词在后，去重保序；一个都没有是错误。"""

    keywords = _dedup([*str(explicit or "").split(","), *queue_keywords])
    if not keywords:
        raise ValueError("no keywords (use --keywords and/or --from-queue)")
    return keywords


def summarize(keywords: Sequence[str], items: Sequence[Mapping[str, Any]]) -> list[KeywordSummary]:
    """按关键词汇总引用数 / 范围判定 / 核验结论。零引用的关键词也会出现在结果里。"""

    summaries = {
        keyword: KeywordSummary(
            keyword=keyword,
            citations=0,
            scope={decision: 0 for decision in SCOPE_DECISIONS},
            verification={status: 0 for status in VERIFICATION_STATUSES},
        )
        for keyword in keywords
    }
    for item in items:
        keyword = str(item.get("keyword") or "")
        summary = summaries.get(keyword)
        if summary is None:
            # 文档级去重可能把一条引用记在另一个关键词名下（同一个 URL 只存一份）。
            summary = summaries.setdefault(
                keyword or "(未归属)",
                KeywordSummary(
                    keyword=keyword or "(未归属)",
                    citations=0,
                    scope={decision: 0 for decision in SCOPE_DECISIONS},
                    verification={status: 0 for status in VERIFICATION_STATUSES},
                ),
            )
        summary.citations += 1
        scope = str(item.get("scope_decision") or "")
        if scope in summary.scope:
            summary.scope[scope] += 1
        status = str(item.get("verification_status") or "")
        if status in summary.verification:
            summary.verification[status] += 1
        if status == "rejected":
            summary.rejection_reasons.extend(
                str(reason) for reason in (item.get("verification_reasons") or [])
            )
    return list(summaries.values())


def format_report(
    summaries: Sequence[KeywordSummary],
    *,
    run_id: int | None = None,
    run_status: str | None = None,
    query_failures: Sequence[Mapping[str, Any]] = (),
    items: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """把结果如实渲染成人能读的报告——包括「什么都没检索到」这种结论。"""

    lines = [f"=== 采集结果（run #{run_id}，状态 {run_status}）==="]
    by_url = {}
    for item in items:
        by_url.setdefault(str(item.get("keyword") or ""), []).append(item)

    for summary in summaries:
        if summary.citations == 0:
            lines.append(
                f"\n【{summary.keyword}】0 条引用 —— 官方网络上没有检索到与之相关的可引用页面。"
                "这本身是一条结论（例如：学校并未就此发布任何公开通知），不是故障。"
            )
            continue
        scope = summary.scope
        verification = summary.verification
        lines.append(
            f"\n【{summary.keyword}】{summary.citations} 条引用 | "
            f"范围：in_scope={scope['in_scope']} needs_review={scope['needs_review']} "
            f"out_of_scope={scope['out_of_scope']} | "
            f"核验：verified={verification['verified']} "
            f"needs_review={verification['needs_review']} rejected={verification['rejected']} "
            f"pending={verification['pending']} failed={verification['failed']}"
        )
        for item in by_url.get(summary.keyword, []):
            lines.append(
                f"  - [{item.get('scope_decision')}/{item.get('verification_status')}] "
                f"{item.get('url')}"
            )
            title = str(item.get("title") or "").strip()
            if title:
                lines.append(f"      标题：{title}")
            for reason in item.get("verification_reasons") or []:
                lines.append(f"      核验：{reason}")
        for reason in summary.rejection_reasons:
            lines.append(f"  ! 驳回原因：{reason}")

    for failure in query_failures:
        lines.append(
            f"\n[FAIL] 检索失败：{failure.get('query_text')} "
            f"（{failure.get('provider')}）：{failure.get('error')}"
        )

    lines.append("")
    lines.append(f"下一步：到 {ADMIN_PAGE_HINT} 逐条人工审核并交付。")
    lines.append(
        "本脚本只做「采集 + 抓取核验」，未写入 raw_posts —— 交付需要 in_scope + verified + 人工审批。"
    )
    return lines


# ---------------------------------------------------------------- 真正上网的部分


async def _collect_and_verify_async(
    *,
    topic: str,
    keywords: Sequence[str],
    providers: Sequence[str] | None,
    max_results: int,
    creator: str,
) -> dict[str, Any]:
    import httpx

    from backend.database import SessionLocal
    from backend.models_evidence import (
        EvidenceDocument,
        EvidenceItem,
        EvidenceQuery,
    )
    from backend.services.evidence.collector import EvidenceCollector
    from backend.services.evidence.config import http_trust_env
    from backend.services.evidence.http_transport import build_search_transports
    from backend.services.evidence.providers import create_provider_registry
    from backend.services.evidence.verification import (
        DEFAULT_TIMEOUT_SECONDS,
        DEFAULT_USER_AGENT,
        UrlFetchVerifier,
        verification_reasons,
        verify_item_by_fetch,
    )

    session = SessionLocal()
    try:
        # 采集：联网检索一次（每个关键词一条 query 行）。
        async with httpx.AsyncClient(timeout=120.0, trust_env=http_trust_env()) as client:
            registry = create_provider_registry(transports=build_search_transports(client=client))
            collector = EvidenceCollector(session, registry)
            run = await collector.collect(
                topic,
                list(keywords),
                provider_ids=list(providers) if providers else None,
                creator=creator,
                max_results=max_results,
            )

        # 核验：真的把每条引用的 URL 抓下来看一眼。
        # trust_env=False（http_trust_env 默认）：httpx 否则会读 Windows 注册表里的系统代理
        # （Clash），把真实可达的 sysu.edu.cn 页面报成 ConnectTimeout。
        items = (
            session.query(EvidenceItem)
            .filter(EvidenceItem.run_id == run.id)
            .order_by(EvidenceItem.id.asc())
            .all()
        )
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            trust_env=http_trust_env(),
        ) as client:
            verifier = UrlFetchVerifier(client=client)
            for item in items:
                await verify_item_by_fetch(session, item.id, verifier)
        session.commit()

        # 关键词归属：item → document.query_id → query.query_text（就是原始关键词）。
        queries = {
            query.id: query
            for query in session.query(EvidenceQuery).filter(EvidenceQuery.run_id == run.id).all()
        }
        documents = {
            document.id: document
            for document in session.query(EvidenceDocument).filter(
                EvidenceDocument.id.in_([item.document_id for item in items] or [0])
            )
        }
        rows: list[dict[str, Any]] = []
        for item in items:
            session.refresh(item)
            document = documents.get(item.document_id)
            query = queries.get(document.query_id) if document is not None else None
            latest = max(item.verifications, key=lambda row: row.id or 0) if item.verifications else None
            rows.append(
                {
                    "keyword": query.query_text if query is not None else "",
                    "url": item.canonical_url or item.source_url,
                    "domain": item.source_domain,
                    "title": document.title if document is not None else None,
                    "scope_decision": item.scope_decision,
                    "verification_status": item.verification_status,
                    "verification_reasons": (
                        verification_reasons(latest.reasons) if latest is not None else []
                    ),
                }
            )
        failures = [
            {"provider": query.provider, "query_text": query.query_text, "error": query.error}
            for query in queries.values()
            if query.status == "failed"
        ]
        return {
            "run_id": run.id,
            "run_status": run.status,
            "items": rows,
            "query_failures": failures,
        }
    finally:
        session.close()


def collect_and_verify(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(_collect_and_verify_async(**kwargs))


# ---------------------------------------------------------------- CLI


def main(
    argv: list[str] | None = None,
    *,
    engine: Any | None = None,
    runner: Callable[..., dict[str, Any]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="联网证据采集（采集 + 抓取核验，不自动审批）")
    parser.add_argument("--from-queue", action="store_true",
                        help="取 crawl_task_queue 中 pending 任务的关键词（与本轮爬取同题）")
    parser.add_argument("--platform", default=None, help="配合 --from-queue：只取该平台的关键词")
    parser.add_argument("--keywords", default="", help="手动关键词，逗号分隔")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="本次 run 的话题标签")
    parser.add_argument("--providers", default="", help="供应商 id，逗号分隔；默认用 .env 里启用的全部")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--creator", default="cli")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要检索什么：零 LLM 调用、零数据库写入")
    args = parser.parse_args(argv)

    queue_keywords: list[str] = []
    if args.from_queue:
        if engine is None:
            from backend.database import engine as default_engine

            engine = default_engine
        with engine.connect() as conn:
            queue_keywords = load_pending_keywords(conn, platform=args.platform)

    try:
        keywords = resolve_keywords(args.keywords, queue_keywords)
    except ValueError as error:
        parser.error(str(error))

    providers = _dedup(args.providers.split(",")) if args.providers else None
    print(f"话题：{args.topic}")
    print(f"关键词（{len(keywords)}）：{'、'.join(keywords)}")
    print(f"供应商：{'、'.join(providers) if providers else '.env 中已启用的全部'}")

    if args.dry_run:
        for keyword in keywords:
            print(f"  [dry-run] 将检索：{keyword}（max_results={args.max_results}）")
        print("[dry-run] 未调用任何大模型，未写入任何数据库表。")
        return 0

    run = runner or collect_and_verify
    result = run(
        topic=args.topic,
        keywords=keywords,
        providers=providers,
        max_results=args.max_results,
        creator=args.creator,
    )
    summaries = summarize(keywords, result.get("items") or [])
    for line in format_report(
        summaries,
        run_id=result.get("run_id"),
        run_status=result.get("run_status"),
        query_failures=result.get("query_failures") or [],
        items=result.get("items") or [],
    ):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
