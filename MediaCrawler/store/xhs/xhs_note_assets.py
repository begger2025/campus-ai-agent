# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

import config
from .xhs_publish_time import resolve_xhs_note_publish_time


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        for key in ("images", "image_list", "items", "data"):
            if value.get(key) is not None:
                return _ensure_list(value.get(key))
        return [value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return _ensure_list(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return [value]


def _to_posix_path(path: str) -> str:
    return path.replace("\\", "/") if path else ""


def normalize_xhs_image_entries(image_list: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in _ensure_list(image_list):
        if isinstance(item, dict):
            url = item.get("url") or item.get("url_default") or item.get("original_url") or item.get("final_url")
            if not url:
                continue
            normalized_item = dict(item)
            normalized_item["url"] = url
            normalized.append(normalized_item)
        else:
            url = str(item).strip()
            if url:
                normalized.append({"url": url})
    return normalized


def normalize_xhs_tag_list(tag_list: Any) -> List[str]:
    tags: List[str] = []
    for item in _ensure_list(tag_list):
        if isinstance(item, dict):
            name = item.get("name") or item.get("tag_name") or item.get("title")
            if not name:
                continue
            item_type = item.get("type")
            if item_type in (None, "", "topic"):
                tags.append(str(name).strip())
        else:
            text = str(item).strip()
            if text:
                tags.append(text)
    return list(dict.fromkeys(tag for tag in tags if tag))


def _build_xhs_note_url(note_item: Dict[str, Any]) -> str:
    note_url = note_item.get("note_url")
    if note_url:
        return str(note_url)

    note_id = note_item.get("note_id") or note_item.get("id")
    if not note_id:
        return ""

    domain = "https://www.rednote.com" if config.XHS_INTERNATIONAL else "https://www.xiaohongshu.com"
    xsec_token = note_item.get("xsec_token", "")
    xsec_source = note_item.get("xsec_source") or "pc_search"
    if xsec_token:
        return f"{domain}/explore/{note_id}?xsec_token={xsec_token}&xsec_source={xsec_source}"
    return f"{domain}/explore/{note_id}"


def normalize_local_image_meta(image_download_meta: Any) -> List[Dict[str, Any]]:
    normalized_meta: List[Dict[str, Any]] = []
    for item in _ensure_list(image_download_meta):
        if not isinstance(item, dict):
            continue
        normalized_item = {
            "index": item.get("index"),
            "original_url": item.get("original_url", ""),
            "final_url": item.get("final_url", ""),
            "local_path": _to_posix_path(str(item.get("local_path", ""))),
            "download_status": item.get("download_status", "unknown"),
        }
        if item.get("error"):
            normalized_item["error"] = item.get("error")
        normalized_meta.append(normalized_item)
    return normalized_meta


def build_xhs_enhanced_note_payload(
    note_item: Dict[str, Any],
    *,
    image_download_meta: Optional[List[Dict[str, Any]]] = None,
    source_keyword: Optional[str] = None,
) -> Dict[str, Any]:
    user_info = note_item.get("user") or {}
    interact_info = note_item.get("interact_info") or {}
    images = normalize_local_image_meta(image_download_meta or note_item.get("local_image_list", []))
    publish_fields = resolve_xhs_note_publish_time(note_item)

    return {
        "note_id": note_item.get("note_id") or note_item.get("id") or "",
        "title": note_item.get("title") or "",
        "desc": note_item.get("desc") or "",
        "source_keyword": source_keyword if source_keyword is not None else note_item.get("source_keyword", ""),
        "publish_time": note_item.get("time") or note_item.get("publish_time") or note_item.get("create_time"),
        "publish_time_raw": note_item.get("publish_time_raw") or publish_fields.get("publish_time_raw"),
        "publish_timestamp_ms": note_item.get("publish_timestamp_ms") or publish_fields.get("publish_timestamp_ms"),
        "publish_date": note_item.get("publish_date") or publish_fields.get("publish_date"),
        "publish_year": note_item.get("publish_year") or publish_fields.get("publish_year"),
        "publish_month": note_item.get("publish_month") or publish_fields.get("publish_month"),
        "publish_day": note_item.get("publish_day") or publish_fields.get("publish_day"),
        "publish_time_source": note_item.get("publish_time_source") or publish_fields.get("publish_time_source"),
        "author": {
            "user_id": user_info.get("user_id") or note_item.get("user_id") or "",
            "nickname": user_info.get("nickname") or note_item.get("nickname") or "",
        },
        "stats": {
            "liked_count": interact_info.get("liked_count") or note_item.get("liked_count") or "",
            "collected_count": interact_info.get("collected_count") or note_item.get("collected_count") or "",
            "comment_count": interact_info.get("comment_count") or note_item.get("comment_count") or "",
            "share_count": interact_info.get("share_count") or note_item.get("share_count") or "",
        },
        "tags": normalize_xhs_tag_list(note_item.get("tag_list", [])),
        "note_url": _build_xhs_note_url(note_item),
        "images": images,
    }


async def export_xhs_note_enhanced_json(
    note_item: Dict[str, Any],
    *,
    image_download_meta: Optional[List[Dict[str, Any]]] = None,
    source_keyword: Optional[str] = None,
) -> str:
    note_id = str(note_item.get("note_id") or note_item.get("id") or "").strip()
    if not note_id:
        raise ValueError("note_id is required to export xhs enhanced json")

    base_dir = Path(getattr(config, "XHS_ENHANCED_OUTPUT_DIR", "output/xhs_enhanced"))
    base_dir.mkdir(parents=True, exist_ok=True)
    file_path = base_dir / f"{note_id}.json"
    payload = build_xhs_enhanced_note_payload(
        note_item,
        image_download_meta=image_download_meta,
        source_keyword=source_keyword,
    )

    async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(payload, ensure_ascii=False, indent=2))

    return file_path.as_posix()
