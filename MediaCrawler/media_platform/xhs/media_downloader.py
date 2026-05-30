# -*- coding: utf-8 -*-
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

import config
from tools import utils
from tools.httpx_util import make_async_client


def build_media_candidate_urls(url: str) -> List[str]:
    url = (url or "").strip()
    if not url:
        return []

    candidates = [url]
    if url.startswith("http://"):
        candidates.append(url.replace("http://", "https://", 1))

    deduplicated: List[str] = []
    for candidate in candidates:
        if candidate not in deduplicated:
            deduplicated.append(candidate)
    return deduplicated


def build_media_request_headers(
    *,
    user_agent: Optional[str] = None,
    referer: Optional[str] = None,
    cookie: str = "",
) -> Dict[str, str]:
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
        "User-Agent": user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    return headers


def guess_media_extension(url: str, content_type: str = "") -> str:
    content_type = (content_type or "").split(";")[0].strip().lower()
    content_type_mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "video/mp4": ".mp4",
    }
    if content_type in content_type_mapping:
        return content_type_mapping[content_type]

    lower_url = (url or "").lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp", ".mp4"):
        if urlparse(lower_url).path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext

    for marker, ext in (
        ("format=jpg", ".jpg"),
        ("format=jpeg", ".jpg"),
        ("format=png", ".png"),
        ("format=webp", ".webp"),
        ("format=avif", ".avif"),
        ("format=gif", ".gif"),
        ("format=mp4", ".mp4"),
    ):
        if marker in lower_url:
            return ext

    return ".jpg"


async def download_media_bytes(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    proxy: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    retry_count: Optional[int] = None,
    sleep_sec: Optional[float] = None,
) -> Dict[str, Any]:
    timeout_sec = timeout_sec or getattr(config, "XHS_MEDIA_DOWNLOAD_TIMEOUT_SEC", 20)
    retry_count = max(1, retry_count or getattr(config, "XHS_MEDIA_DOWNLOAD_RETRY_COUNT", 2))
    sleep_sec = max(0.0, getattr(config, "XHS_MEDIA_DOWNLOAD_SLEEP_SEC", 1) if sleep_sec is None else sleep_sec)
    candidates = build_media_candidate_urls(url)

    if not candidates:
        return {
            "success": False,
            "content": None,
            "original_url": url,
            "final_url": "",
            "content_type": "",
            "file_extension": ".jpg",
            "error": "empty media url",
        }

    last_error = ""
    for candidate_index, candidate_url in enumerate(candidates, start=1):
        for attempt in range(1, retry_count + 1):
            try:
                async with make_async_client(proxy=proxy, follow_redirects=True) as client:
                    response = await client.get(candidate_url, headers=headers, timeout=timeout_sec)
                response.raise_for_status()
                if not response.content:
                    raise ValueError("empty response content")

                final_url = str(response.url)
                content_type = response.headers.get("content-type", "")
                return {
                    "success": True,
                    "content": response.content,
                    "original_url": url,
                    "final_url": final_url,
                    "content_type": content_type,
                    "file_extension": guess_media_extension(final_url, content_type),
                    "error": "",
                }
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
                utils.logger.warning(
                    f"[xhs.media_downloader] Failed to download media {candidate_url} "
                    f"(candidate {candidate_index}/{len(candidates)}, attempt {attempt}/{retry_count}): {last_error}"
                )
                if attempt < retry_count:
                    await asyncio.sleep(sleep_sec)

        if candidate_index < len(candidates):
            await asyncio.sleep(sleep_sec)

    return {
        "success": False,
        "content": None,
        "original_url": url,
        "final_url": "",
        "content_type": "",
        "file_extension": guess_media_extension(url),
        "error": last_error or "download failed",
    }
