import argparse
import asyncio
import random
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from playwright.async_api import Playwright, async_playwright
from sqlalchemy import and_, case, func, or_, select, update

load_dotenv(override=True)

import config
from database.db_session import get_session
from database.models import XhsNote
from media_platform.xhs.core import XiaoHongShuCrawler
from media_platform.xhs.exception import CaptchaBlockError, DataFetchError, NoteNotFoundError
from media_platform.xhs.help import parse_note_info_from_note_url
from media_platform.xhs.login import XiaoHongShuLogin
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store.xhs.xhs_publish_time import resolve_xhs_note_publish_time
from tools import utils


PUBLISH_FIELDS = (
    "publish_time_raw",
    "publish_timestamp_ms",
    "publish_date",
    "publish_year",
    "publish_month",
    "publish_day",
)

CRAWL_FIELDS = (
    "first_crawled_at",
    "last_crawled_at",
    "crawl_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Xiaohongshu note publish-time fields for historical rows."
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of notes to process.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Backfill worker count. Actual detail-fetch concurrency is forced to 1 for safety.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only process notes within the recent N days, based on first_crawled_at/add_ts/last_modify_ts fallback.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print which notes would be processed. Do not fetch detail or update database.",
    )
    return parser.parse_args()


def has_complete_publish_fields(note: XhsNote) -> bool:
    return bool(
        getattr(note, "publish_date", None)
        and getattr(note, "publish_timestamp_ms", None)
        and getattr(note, "publish_year", None) is not None
        and getattr(note, "publish_month", None) is not None
        and getattr(note, "publish_day", None) is not None
    )


def get_valid_crawl_count(note: XhsNote) -> Optional[int]:
    crawl_count = getattr(note, "crawl_count", None)
    if crawl_count in (None, ""):
        return None
    try:
        return int(crawl_count)
    except (TypeError, ValueError):
        return None


def has_complete_crawl_fields(note: XhsNote) -> bool:
    crawl_count = get_valid_crawl_count(note)
    return bool(
        getattr(note, "first_crawled_at", None)
        and getattr(note, "last_crawled_at", None)
        and crawl_count is not None
        and crawl_count > 0
    )


def needs_publish_backfill(note: XhsNote) -> bool:
    return not has_complete_publish_fields(note)


def needs_crawl_backfill(note: XhsNote) -> bool:
    crawl_count = get_valid_crawl_count(note)
    return bool(
        not getattr(note, "first_crawled_at", None)
        or not getattr(note, "last_crawled_at", None)
        or crawl_count is None
        or crawl_count <= 0
    )


def build_publish_update_payload(note: XhsNote, normalized: Dict[str, Any]) -> Dict[str, Any]:
    update_payload: Dict[str, Any] = {}
    for field_name in PUBLISH_FIELDS:
        new_value = normalized.get(field_name)
        old_value = getattr(note, field_name, None)
        if new_value in (None, ""):
            continue
        if old_value in (None, "") or old_value != new_value:
            update_payload[field_name] = new_value
    return update_payload


def build_crawl_field_update_payload(note: XhsNote, current_ts_ms: int) -> Dict[str, Any]:
    update_payload: Dict[str, Any] = {}
    existing_first_crawled_at = getattr(note, "first_crawled_at", None)
    existing_last_crawled_at = getattr(note, "last_crawled_at", None)
    existing_crawl_count = get_valid_crawl_count(note)

    if not existing_first_crawled_at:
        fallback_first_crawled_at = (
            getattr(note, "add_ts", None)
            or getattr(note, "last_modify_ts", None)
            or current_ts_ms
        )
        if fallback_first_crawled_at:
            update_payload["first_crawled_at"] = int(fallback_first_crawled_at)

    if not existing_last_crawled_at:
        update_payload["last_crawled_at"] = int(current_ts_ms)

    if existing_crawl_count is None or existing_crawl_count <= 0:
        update_payload["crawl_count"] = 1

    return update_payload


def extract_note_request_info(note: XhsNote) -> Tuple[str, str, str]:
    note_id = str(note.note_id or "").strip()
    note_url = str(getattr(note, "note_url", "") or "").strip()
    xsec_token = str(getattr(note, "xsec_token", "") or "").strip()
    xsec_source = "pc_search"

    if note_url:
        try:
            note_info = parse_note_info_from_note_url(note_url)
            xsec_token = note_info.xsec_token or xsec_token
            xsec_source = note_info.xsec_source or xsec_source
        except Exception:
            pass

    return note_id, xsec_token, xsec_source


async def throttle_sleep(min_sec: int, max_sec: int, phase: str, note_id: str) -> None:
    sleep_seconds = random.randint(min_sec, max_sec)
    utils.logger.info(
        f"[backfill_publish_time] Sleeping {sleep_seconds} seconds {phase}, note_id={note_id}"
    )
    await asyncio.sleep(sleep_seconds)


async def query_candidate_notes(limit: int, days: Optional[int]) -> List[XhsNote]:
    normalized_limit = max(1, int(limit or 20))
    effective_ts = func.coalesce(XhsNote.first_crawled_at, XhsNote.add_ts, XhsNote.last_modify_ts)
    missing_publish_expr = or_(
        XhsNote.publish_date.is_(None),
        XhsNote.publish_date == "",
        XhsNote.publish_timestamp_ms.is_(None),
        XhsNote.publish_year.is_(None),
        XhsNote.publish_month.is_(None),
        XhsNote.publish_day.is_(None),
    )
    missing_crawl_expr = or_(
        XhsNote.first_crawled_at.is_(None),
        XhsNote.last_crawled_at.is_(None),
        XhsNote.crawl_count.is_(None),
        XhsNote.crawl_count <= 0,
    )
    priority_expr = case(
        (and_(missing_publish_expr, missing_crawl_expr), 0),
        (missing_publish_expr, 1),
        (missing_crawl_expr, 2),
        else_=3,
    )

    async with get_session() as session:
        stmt = select(XhsNote).where(
            and_(
                XhsNote.note_id.is_not(None),
                XhsNote.note_id != "",
                or_(missing_publish_expr, missing_crawl_expr),
            )
        )
        if days is not None and days > 0:
            cutoff_ms = int(utils.get_current_timestamp()) - days * 24 * 60 * 60 * 1000
            stmt = stmt.where(effective_ts >= cutoff_ms)
        stmt = stmt.order_by(priority_expr.asc(), effective_ts.desc(), XhsNote.id.desc()).limit(normalized_limit)
        result = await session.execute(stmt)
        return result.scalars().all()


async def load_note_by_id(note_id: str) -> Optional[XhsNote]:
    async with get_session() as session:
        stmt = select(XhsNote).where(XhsNote.note_id == note_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def update_note_publish_fields(note_id: str, update_payload: Dict[str, Any]) -> None:
    if not update_payload:
        return
    async with get_session() as session:
        stmt = update(XhsNote).where(XhsNote.note_id == note_id).values(**update_payload)
        await session.execute(stmt)


async def init_xhs_crawler_for_backfill(playwright: Playwright) -> XiaoHongShuCrawler:
    crawler = XiaoHongShuCrawler()
    playwright_proxy_format, httpx_proxy_format = None, None

    if config.ENABLE_IP_PROXY:
        crawler.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
        ip_proxy_info: IpInfoModel = await crawler.ip_proxy_pool.get_proxy()
        playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

    if config.ENABLE_CDP_MODE:
        utils.logger.info("[backfill_publish_time] Launching browser using CDP mode")
        crawler.browser_context = await crawler.launch_browser_with_cdp(
            playwright,
            playwright_proxy_format,
            crawler.user_agent,
            headless=config.CDP_HEADLESS,
        )
    else:
        utils.logger.info("[backfill_publish_time] Launching browser using standard mode")
        chromium = playwright.chromium
        crawler.browser_context = await crawler.launch_browser(
            chromium,
            playwright_proxy_format,
            crawler.user_agent,
            headless=config.HEADLESS,
        )
        await crawler.browser_context.add_init_script(path="libs/stealth.min.js")

    crawler.context_page = await crawler._get_context_page()
    crawler.xhs_client = await crawler.create_xhs_client(httpx_proxy_format)

    login_state_ok = await crawler.xhs_client.pong()
    if not login_state_ok:
        utils.logger.info("[backfill_publish_time] Re-check login state on fresh page")
        crawler.context_page = await crawler._get_or_create_healthy_xhs_page(force_fresh=True)
        crawler.xhs_client = await crawler.create_xhs_client(httpx_proxy_format)
        login_state_ok = await crawler.xhs_client.pong()
        if login_state_ok:
            utils.logger.info("[backfill_publish_time] Fresh page recovery succeeded, skip QR login")

    if not login_state_ok:
        utils.logger.info("[backfill_publish_time] Login state still invalid, entering existing login flow")
        login_obj = XiaoHongShuLogin(
            login_type=config.LOGIN_TYPE,
            login_phone="",
            browser_context=crawler.browser_context,
            context_page=crawler.context_page,
            cookie_str=config.COOKIES,
        )
        await login_obj.begin()
        await crawler.xhs_client.update_cookies(
            browser_context=crawler.browser_context,
            urls=crawler.cookie_urls,
        )

    return crawler


async def fetch_note_detail_for_backfill(crawler: XiaoHongShuCrawler, note: XhsNote) -> Optional[Dict[str, Any]]:
    note_id, xsec_token, xsec_source = extract_note_request_info(note)
    if not note_id:
        utils.logger.warning("[backfill_publish_time] Missing note_id, skip detail fetch")
        return None

    note_detail: Optional[Dict[str, Any]] = None
    try:
        note_detail = await crawler.xhs_client.get_note_by_id(note_id, xsec_source, xsec_token)
    except (CaptchaBlockError, DataFetchError, NoteNotFoundError) as ex:
        utils.logger.warning(
            f"[backfill_publish_time] API detail fetch failed, note_id={note_id}, "
            f"xsec_source={xsec_source}, error={ex}, fallback=html"
        )
    except Exception as ex:
        utils.logger.warning(
            f"[backfill_publish_time] Unexpected API detail fetch error, note_id={note_id}, "
            f"xsec_source={xsec_source}, error={ex}, fallback=html"
        )

    if note_detail:
        return note_detail

    try:
        note_detail = await crawler.xhs_client.get_note_by_id_from_html(
            note_id,
            xsec_source,
            xsec_token,
            enable_cookie=True,
        )
    except (CaptchaBlockError, DataFetchError, NoteNotFoundError) as ex:
        utils.logger.warning(
            f"[backfill_publish_time] HTML fallback failed, note_id={note_id}, "
            f"xsec_source={xsec_source}, error={ex}"
        )
        return None
    except Exception as ex:
        utils.logger.warning(
            f"[backfill_publish_time] Unexpected HTML fallback error, note_id={note_id}, "
            f"xsec_source={xsec_source}, error={ex}"
        )
        return None

    return note_detail


async def process_note(
    note_id: str,
    crawler: Optional[XiaoHongShuCrawler],
    dry_run: bool,
) -> Dict[str, Any]:
    utils.logger.info(f"[backfill_publish_time] Begin processing note, note_id={note_id}")
    current_note = await load_note_by_id(note_id)
    if current_note is None:
        utils.logger.info(f"[backfill_publish_time] Skip missing note row, note_id={note_id}")
        return {"status": "skipped", "note_id": note_id, "reason": "missing_row"}

    missing_publish = needs_publish_backfill(current_note)
    missing_crawl = needs_crawl_backfill(current_note)
    if not missing_publish and not missing_crawl:
        utils.logger.info(
            f"[backfill_publish_time] Skip already-complete publish/crawl fields, note_id={note_id}"
        )
        return {"status": "skipped", "note_id": note_id, "reason": "already_complete", "attempted_fetch": False}

    if dry_run:
        utils.logger.info(
            f"[backfill_publish_time] DRY-RUN candidate, note_id={note_id}, "
            f"missing_publish={missing_publish}, missing_crawl={missing_crawl}, "
            f"first_crawled_at={current_note.first_crawled_at}, last_crawled_at={current_note.last_crawled_at}, "
            f"crawl_count={current_note.crawl_count}, add_ts={current_note.add_ts}, "
            f"last_modify_ts={current_note.last_modify_ts}"
        )
        return {"status": "dry_run", "note_id": note_id, "attempted_fetch": False}

    if crawler is None:
        utils.logger.error(f"[backfill_publish_time] Missing crawler instance for live backfill, note_id={note_id}")
        return {"status": "failed", "note_id": note_id, "reason": "missing_crawler", "attempted_fetch": False}

    await throttle_sleep(20, 40, "before detail fetch", note_id)

    detail = await fetch_note_detail_for_backfill(crawler, current_note)
    if not detail:
        utils.logger.error(f"[backfill_publish_time] Failed to fetch detail, note_id={note_id}")
        await throttle_sleep(10, 20, "after detail fetch failure", note_id)
        return {"status": "failed", "note_id": note_id, "reason": "detail_fetch_failed", "attempted_fetch": True}

    utils.logger.info(f"[backfill_publish_time] Detail fetch succeeded, note_id={note_id}")
    current_ts_ms = int(utils.get_current_timestamp())
    normalized = resolve_xhs_note_publish_time(detail, crawl_ts_ms=current_ts_ms)
    publish_time_raw = normalized.get("publish_time_raw", "")
    publish_date = normalized.get("publish_date")
    utils.logger.info(
        f"[backfill_publish_time] Publish time normalized, note_id={note_id}, "
        f"publish_time_raw={publish_time_raw}, publish_date={publish_date}"
    )
    publish_update_payload = build_publish_update_payload(current_note, normalized)
    crawl_update_payload = build_crawl_field_update_payload(current_note, current_ts_ms)
    update_payload = {**publish_update_payload, **crawl_update_payload}

    if not update_payload:
        utils.logger.info(
            f"[backfill_publish_time] No database update needed, note_id={note_id}, "
            f"publish_time_raw={publish_time_raw}, publish_date={publish_date}, "
            f"updated_publish_fields=[], updated_crawl_fields=[]"
        )
        await throttle_sleep(10, 20, "after no-op backfill", note_id)
        return {
            "status": "skipped",
            "note_id": note_id,
            "reason": "no_publish_fields_resolved",
            "publish_time_raw": publish_time_raw,
            "publish_date": publish_date,
            "attempted_fetch": True,
            "db_updated": False,
            "updated_publish_fields": [],
            "updated_crawl_fields": [],
        }

    await update_note_publish_fields(note_id, update_payload)
    utils.logger.info(
        f"[backfill_publish_time] Updated fields for note_id={note_id}, "
        f"publish_time_raw={publish_time_raw}, publish_date={publish_date}, "
        f"updated_publish_fields={list(publish_update_payload.keys())}, "
        f"updated_crawl_fields={list(crawl_update_payload.keys())}, db_updated=True"
    )
    await throttle_sleep(40, 80, "after detail success", note_id)
    return {
        "status": "success",
        "note_id": note_id,
        "publish_time_raw": publish_time_raw,
        "publish_date": publish_date,
        "updated_fields": list(update_payload.keys()),
        "updated_publish_fields": list(publish_update_payload.keys()),
        "updated_crawl_fields": list(crawl_update_payload.keys()),
        "attempted_fetch": True,
        "db_updated": True,
    }


async def async_main() -> None:
    args = parse_args()
    if args.concurrency > 1:
        utils.logger.warning(
            f"[backfill_publish_time] Concurrency {args.concurrency} requested, "
            f"but detail backfill is forced to serial mode. Using concurrency=1."
        )
        args.concurrency = 1

    candidates = await query_candidate_notes(limit=args.limit, days=args.days)
    missing_publish_count = sum(1 for note in candidates if needs_publish_backfill(note))
    missing_crawl_count = sum(1 for note in candidates if needs_crawl_backfill(note))
    utils.logger.info(
        f"[backfill_publish_time] Candidate notes scanned: {len(candidates)}, "
        f"missing_publish_fields={missing_publish_count}, missing_crawl_fields={missing_crawl_count}, "
        f"limit={args.limit}, concurrency={args.concurrency}, days={args.days}, dry_run={args.dry_run}"
    )

    if not candidates:
        utils.logger.info("[backfill_publish_time] No candidate notes need publish-time backfill")
        return

    if args.dry_run:
        for note in candidates:
            await process_note(str(note.note_id), crawler=None, dry_run=True)
        utils.logger.info(
            f"[backfill_publish_time] Summary - scanned={len(candidates)}, attempted=0, success=0, skipped=0, failed=0"
        )
        return

    crawler: Optional[XiaoHongShuCrawler] = None
    results: List[Dict[str, Any]] = []

    async with async_playwright() as playwright:
        try:
            crawler = await init_xhs_crawler_for_backfill(playwright)
            for note in candidates:
                result = await process_note(str(note.note_id), crawler, dry_run=False)
                results.append(result)
        finally:
            if crawler:
                try:
                    await crawler.close()
                except Exception as ex:
                    utils.logger.warning(f"[backfill_publish_time] Failed to close crawler cleanly: {ex}")

    attempted = sum(1 for item in results if item.get("attempted_fetch"))
    success_count = sum(1 for item in results if item.get("status") == "success")
    skipped_count = sum(1 for item in results if item.get("status") == "skipped")
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    publish_updated_count = sum(1 for item in results if item.get("updated_publish_fields"))
    crawl_updated_count = sum(1 for item in results if item.get("updated_crawl_fields"))

    utils.logger.info(
        f"[backfill_publish_time] Summary - scanned={len(candidates)}, attempted={attempted}, "
        f"success={success_count}, skipped={skipped_count}, failed={failed_count}, "
        f"publish_field_updates={publish_updated_count}, crawl_field_updates={crawl_updated_count}"
    )


if __name__ == "__main__":
    asyncio.run(async_main())
