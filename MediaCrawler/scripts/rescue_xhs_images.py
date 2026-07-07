# -*- coding: utf-8 -*-
import argparse
import asyncio
from datetime import datetime, time
from typing import Dict, List, Optional

from sqlalchemy import case, desc, select

import config
from database.db_session import get_session
from database.models import XhsNote
from media_platform.xhs.media_downloader import build_media_request_headers, download_media_bytes
from store import xhs as xhs_store
from store.xhs.xhs_note_assets import export_xhs_note_enhanced_json, normalize_xhs_image_entries
from tools import utils


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rescue historical Xiaohongshu note images from database records")
    parser.add_argument("--source-keyword", dest="source_keyword", default="", help="Filter by source_keyword")
    parser.add_argument("--note-id", dest="note_id", default="", help="Filter by note_id")
    parser.add_argument("--start-date", dest="start_date", default="", help="Filter publish time >= YYYY-MM-DD")
    parser.add_argument("--end-date", dest="end_date", default="", help="Filter publish time <= YYYY-MM-DD")
    parser.add_argument("--limit", dest="limit", type=int, default=20, help="Maximum number of notes to process")
    return parser.parse_args()


def _parse_date_to_timestamp(date_text: str, *, end_of_day: bool = False) -> Optional[int]:
    if not date_text:
        return None
    parsed = datetime.strptime(date_text, "%Y-%m-%d")
    target_dt = datetime.combine(parsed.date(), time.max if end_of_day else time.min)
    return int(target_dt.timestamp())


def _row_to_note_item(row: XhsNote) -> Dict:
    return {
        "note_id": row.note_id,
        "title": row.title or "",
        "desc": row.desc or "",
        "time": row.time,
        "user_id": row.user_id or "",
        "nickname": row.nickname or "",
        "liked_count": row.liked_count or "",
        "collected_count": row.collected_count or "",
        "comment_count": row.comment_count or "",
        "share_count": row.share_count or "",
        "image_list": row.image_list or "",
        "tag_list": row.tag_list or "",
        "note_url": row.note_url or "",
        "source_keyword": row.source_keyword or "",
        "xsec_token": row.xsec_token or "",
    }


async def fetch_target_notes(args: argparse.Namespace) -> List[Dict]:
    normalized_time = case((XhsNote.time > 9999999999, XhsNote.time / 1000), else_=XhsNote.time)
    query = select(XhsNote).order_by(desc(XhsNote.time))

    if args.note_id:
        query = query.where(XhsNote.note_id == args.note_id)
    if args.source_keyword:
        query = query.where(XhsNote.source_keyword == args.source_keyword)

    start_ts = _parse_date_to_timestamp(args.start_date)
    end_ts = _parse_date_to_timestamp(args.end_date, end_of_day=True)
    if start_ts is not None:
        query = query.where(normalized_time >= start_ts)
    if end_ts is not None:
        query = query.where(normalized_time <= end_ts)

    query = query.limit(max(1, args.limit))

    async with get_session() as session:
        result = await session.execute(query)
        rows = result.scalars().all()

    return [_row_to_note_item(row) for row in rows]


async def rescue_note_images(note_item: Dict) -> List[Dict]:
    note_id = str(note_item.get("note_id", "")).strip()
    image_entries = normalize_xhs_image_entries(note_item.get("image_list", []))
    if not note_id or not image_entries:
        note_item["local_image_list"] = []
        return []

    referer = note_item.get("note_url") or f"https://www.xiaohongshu.com/explore/{note_id}"
    headers = build_media_request_headers(referer=referer)
    download_sleep_sec = max(0.0, getattr(config, "XHS_MEDIA_DOWNLOAD_SLEEP_SEC", 1))

    image_download_meta: List[Dict] = []
    for index, image_item in enumerate(image_entries, start=1):
        original_url = image_item.get("url", "")
        image_meta = {
            "index": index,
            "original_url": original_url,
            "final_url": "",
            "local_path": "",
            "download_status": "skipped",
        }
        if not original_url:
            image_meta["download_status"] = "missing_url"
            image_download_meta.append(image_meta)
            continue

        existing_local_path = xhs_store.find_existing_xhs_note_image(note_id, index)
        if existing_local_path:
            image_meta.update(
                {
                    "final_url": original_url,
                    "local_path": existing_local_path,
                    "download_status": "skipped_existing",
                }
            )
            image_download_meta.append(image_meta)
            continue

        try:
            download_result = await download_media_bytes(
                original_url,
                headers=headers,
                timeout_sec=getattr(config, "XHS_MEDIA_DOWNLOAD_TIMEOUT_SEC", 20),
                retry_count=getattr(config, "XHS_MEDIA_DOWNLOAD_RETRY_COUNT", 2),
                sleep_sec=download_sleep_sec,
            )
            if not download_result.get("success"):
                image_meta.update(
                    {
                        "download_status": "failed",
                        "final_url": download_result.get("final_url", ""),
                        "error": download_result.get("error", "download failed"),
                    }
                )
                utils.logger.warning(
                    f"[rescue_xhs_images] Failed to download image {index} for note {note_id}: "
                    f"{image_meta['error']}"
                )
                image_download_meta.append(image_meta)
                continue

            extension_file_name = f"{index}{download_result.get('file_extension', '.jpg')}"
            store_result = await xhs_store.update_xhs_note_image(
                note_id,
                download_result.get("content"),
                extension_file_name,
            )
            image_meta.update(
                {
                    "final_url": download_result.get("final_url") or original_url,
                    "local_path": (store_result or {}).get("local_path", ""),
                    "download_status": "skipped_existing" if (store_result or {}).get("skipped") else "success",
                }
            )
            image_download_meta.append(image_meta)
        except Exception as ex:
            image_meta.update({"download_status": "failed", "error": str(ex)})
            image_download_meta.append(image_meta)
            utils.logger.warning(
                f"[rescue_xhs_images] Unexpected error when rescuing image {index} for note {note_id}: {ex}"
            )
        finally:
            if download_sleep_sec > 0:
                await asyncio.sleep(download_sleep_sec)

    note_item["local_image_list"] = image_download_meta
    return image_download_meta


async def main():
    args = parse_args()
    note_items = await fetch_target_notes(args)
    if not note_items:
        utils.logger.info("[rescue_xhs_images] No xhs_note records matched the current filters")
        return

    utils.logger.info(f"[rescue_xhs_images] Found {len(note_items)} xhs_note records to process")
    for note_item in note_items:
        image_download_meta = await rescue_note_images(note_item)
        json_path = await export_xhs_note_enhanced_json(
            note_item,
            image_download_meta=image_download_meta,
            source_keyword=note_item.get("source_keyword", ""),
        )
        utils.logger.info(
            f"[rescue_xhs_images] Exported enhanced json for note {note_item.get('note_id')} to {json_path}"
        )


if __name__ == "__main__":
    asyncio.run(main())
