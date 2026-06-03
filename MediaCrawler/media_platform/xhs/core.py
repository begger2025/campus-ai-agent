# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import json
import os
import random
import uuid
from asyncio import Task
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
import config
from base.base_crawler import AbstractCrawler
from model.m_xiaohongshu import NoteUrlInfo, CreatorUrlInfo
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import xhs as xhs_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import XiaoHongShuClient
from .exception import CaptchaBlockError, DataFetchError, NoteNotFoundError
from .field import SearchSortType
from .help import parse_note_info_from_note_url, parse_creator_info_from_url, get_search_id
from .login import XiaoHongShuLogin


class XiaoHongShuCrawler(AbstractCrawler):
    context_page: Page
    xhs_client: XiaoHongShuClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.rednote.com" if config.XHS_INTERNATIONAL else "https://www.xiaohongshu.com"
        self.cookie_urls = [self.index_url]
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self.prefer_html_note_detail = False
        self.risk_control_triggered = False
        self.detail_stop_requested = False
        self.detail_stop_reason = ""
        self.consecutive_detail_failures = 0

    def _reset_detail_run_state(self) -> None:
        self.prefer_html_note_detail = False
        self.risk_control_triggered = False
        self.detail_stop_requested = False
        self.detail_stop_reason = ""
        self.consecutive_detail_failures = 0

    def _is_conservative_detail_mode(self) -> bool:
        return bool(getattr(config, "XHS_CONSERVATIVE_DETAIL_MODE", False))

    def _get_effective_detail_fetch_limit(self) -> int:
        crawler_limit = max(0, int(getattr(config, "CRAWLER_MAX_NOTES_COUNT", 0)))
        if crawler_limit <= 0:
            return 0

        configured_run_limit = max(
            1,
            int(getattr(config, "XHS_MAX_DETAIL_FETCH_PER_RUN", crawler_limit)),
        )
        if self._is_conservative_detail_mode():
            return min(crawler_limit, configured_run_limit)
        return crawler_limit

    def _get_max_consecutive_detail_failures(self) -> int:
        return max(1, int(getattr(config, "XHS_MAX_CONSECUTIVE_DETAIL_FAILURES", 1)))

    async def _sleep_random_range(
        self,
        min_sec: int,
        max_sec: int,
        *,
        label: str,
        note_id: str = "",
    ) -> None:
        sleep_min = max(0, int(min_sec))
        sleep_max = max(sleep_min, int(max_sec))
        sleep_sec = random.randint(sleep_min, sleep_max) if sleep_max > sleep_min else sleep_min
        suffix = f", note_id={note_id}" if note_id else ""
        utils.logger.info(f"[detail throttle] Sleeping {sleep_sec} seconds {label}{suffix}")
        if sleep_sec > 0:
            await asyncio.sleep(sleep_sec)

    def _mark_detail_run_stop(
        self,
        *,
        reason: str,
        note_id: str = "",
        risk_control: bool = False,
    ) -> None:
        already_stopped = self.detail_stop_requested
        self.detail_stop_requested = True
        if risk_control:
            self.risk_control_triggered = True
        if reason and not self.detail_stop_reason:
            self.detail_stop_reason = reason

        if already_stopped:
            return

        reason_suffix = f", reason: {reason}" if reason else ""
        note_suffix = f", note_id: {note_id}" if note_id else ""
        if risk_control:
            utils.logger.warning(
                "[XiaoHongShuCrawler] Risk control triggered, stop current run. "
                f"Remaining note details will be skipped{note_suffix}{reason_suffix}"
            )
        else:
            utils.logger.warning(
                "[XiaoHongShuCrawler] Detail crawl stop triggered, stop current run. "
                f"Remaining note details will be skipped{note_suffix}{reason_suffix}"
            )

    def _build_crawl_history_state(self, keyword: str) -> Dict[str, Any]:
        started_at = int(utils.get_current_timestamp())
        return {
            "run_id": f"xhs_{started_at}_{uuid.uuid4().hex[:8]}",
            "platform": "xhs",
            "source_keyword": keyword,
            "started_at": started_at,
            "finished_at": 0,
            "planned_detail_count": 0,
            "success_detail_count": 0,
            "failed_detail_count": 0,
            "risk_control_triggered": 0,
            "stop_reason": "",
            "failed_note_ids_json": "[]",
            "extra_json": "{}",
        }

    async def _create_crawl_history_record(self, history_state: Dict[str, Any]) -> None:
        try:
            await xhs_store.create_xhs_crawl_history(history_state)
            utils.logger.info(
                f"[XiaoHongShuCrawler] Crawl history record created, run_id={history_state.get('run_id')}, "
                f"keyword={history_state.get('source_keyword')}"
            )
        except Exception as ex:
            utils.logger.error(
                f"[XiaoHongShuCrawler] Failed to create crawl history record, "
                f"run_id={history_state.get('run_id')}, keyword={history_state.get('source_keyword')}, error: {ex}"
            )

    async def _finalize_crawl_history_record(
        self,
        history_state: Dict[str, Any],
        *,
        failed_note_ids: List[str],
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        history_state["finished_at"] = int(utils.get_current_timestamp())
        history_state["risk_control_triggered"] = int(self.risk_control_triggered)
        history_state["stop_reason"] = self.detail_stop_reason or history_state.get("stop_reason") or "completed"
        history_state["failed_note_ids_json"] = json.dumps(failed_note_ids, ensure_ascii=False)
        history_state["extra_json"] = json.dumps(extra_payload or {}, ensure_ascii=False)

        try:
            await xhs_store.update_xhs_crawl_history(history_state.get("run_id", ""), history_state)
            utils.logger.info(
                "[XiaoHongShuCrawler] Crawl history saved, "
                f"run_id={history_state.get('run_id')}, keyword={history_state.get('source_keyword')}, "
                f"planned={history_state.get('planned_detail_count')}, "
                f"success={history_state.get('success_detail_count')}, "
                f"failed={history_state.get('failed_detail_count')}, "
                f"risk_control_triggered={bool(history_state.get('risk_control_triggered'))}"
            )
        except Exception as ex:
            utils.logger.error(
                f"[XiaoHongShuCrawler] Failed to save crawl history, run_id={history_state.get('run_id')}, "
                f"keyword={history_state.get('source_keyword')}, error: {ex}"
            )

    async def _crawl_note_details_serially(
        self,
        note_items: List[Dict],
        *,
        note_id_key: str,
        xsec_source_key: str,
        xsec_token_key: str,
        context: str,
        before_detail_batch_sleep: bool = False,
    ) -> Tuple[List[Dict], List[str]]:
        success_note_details: List[Dict] = []
        failed_note_ids: List[str] = []
        scheduled_note_ids: List[str] = []

        if not note_items:
            return success_note_details, failed_note_ids

        if before_detail_batch_sleep and self._is_conservative_detail_mode():
            await self._sleep_random_range(
                getattr(config, "XHS_SEARCH_TO_DETAIL_SLEEP_MIN_SEC", 30),
                getattr(config, "XHS_SEARCH_TO_DETAIL_SLEEP_MAX_SEC", 60),
                label="after search results before detail crawl",
            )

        semaphore = asyncio.Semaphore(1 if self._is_conservative_detail_mode() else max(1, config.MAX_CONCURRENCY_NUM))
        for post_item in note_items:
            if self.detail_stop_requested:
                utils.logger.warning(
                    f"[{context}] Detail stop flag is set, remaining note details will be skipped"
                )
                break

            note_id = post_item.get(note_id_key, "")
            scheduled_note_ids.append(note_id)
            note_detail = await self.get_note_detail_async_task(
                note_id=note_id,
                xsec_source=post_item.get(xsec_source_key, ""),
                xsec_token=post_item.get(xsec_token_key, ""),
                semaphore=semaphore,
            )
            if note_detail:
                self.consecutive_detail_failures = 0
                success_note_details.append(note_detail)
                continue

            failed_note_ids.append(note_id)
            self.consecutive_detail_failures += 1
            utils.logger.warning(
                f"[{context}] Detail fetch failed, note_id: {note_id}, "
                f"consecutive detail failures: {self.consecutive_detail_failures}"
            )

            if self.risk_control_triggered:
                break

            if self.consecutive_detail_failures >= self._get_max_consecutive_detail_failures():
                self._mark_detail_run_stop(
                    reason="consecutive_detail_failures",
                    note_id=note_id,
                    risk_control=False,
                )
                utils.logger.warning(f"[{context}] consecutive detail failures reached threshold, stop current run")
                break

        utils.logger.info(
            f"[{context}] Detail crawl summary - scheduled: {len(scheduled_note_ids)}, "
            f"success: {len(success_note_details)}, failed: {len(failed_note_ids)}, "
            f"failed note_ids: {failed_note_ids}"
        )
        return success_note_details, failed_note_ids

    async def _filter_new_note_items_before_detail(
        self,
        items: List[Dict],
        *,
        remaining_quota: int,
        context: str,
    ) -> List[Dict]:
        total_candidates = len(items)
        note_candidates: List[Dict] = []
        deduplicated_note_items: List[Dict] = []
        seen_note_ids_in_batch = set()
        duplicate_note_ids_in_batch = 0
        skipped_missing_note_id = 0
        duplicate_note_id_samples: List[str] = []

        for post_item in items:
            if post_item.get("model_type") != "note":
                continue

            note_candidates.append(post_item)
            note_id = str(post_item.get("id") or "").strip()
            if not note_id:
                skipped_missing_note_id += 1
                continue

            if note_id in seen_note_ids_in_batch:
                duplicate_note_ids_in_batch += 1
                if len(duplicate_note_id_samples) < 10:
                    duplicate_note_id_samples.append(note_id)
                continue

            seen_note_ids_in_batch.add(note_id)
            deduplicated_note_items.append(post_item)

        skip_existing_enabled = bool(getattr(config, "XHS_SKIP_EXISTING_NOTE_DETAILS", True))
        existing_note_ids = set()
        if skip_existing_enabled:
            existing_note_ids = await xhs_store.batch_get_existing_note_ids(
                [str(post_item.get("id") or "").strip() for post_item in deduplicated_note_items]
            )

        skipped_existing_note_ids = sum(
            1
            for post_item in deduplicated_note_items
            if str(post_item.get("id") or "").strip() in existing_note_ids
        )
        skipped_existing_note_id_samples = [
            str(post_item.get("id") or "").strip()
            for post_item in deduplicated_note_items
            if str(post_item.get("id") or "").strip() in existing_note_ids
        ][:10]

        new_note_items: List[Dict] = []
        for post_item in deduplicated_note_items:
            note_id = str(post_item.get("id") or "").strip()
            if not note_id:
                continue

            if skip_existing_enabled and note_id in existing_note_ids:
                continue

            new_note_items.append(post_item)

        sorted_new_note_items = self._sort_new_note_items_by_publish_time(
            new_note_items,
            context=context,
        )
        selected_note_items = sorted_new_note_items[:remaining_quota]

        utils.logger.info(f"[{context}] Skip existing note details enabled: {skip_existing_enabled}")
        utils.logger.info(f"[{context}] Search candidates total: {total_candidates}")
        utils.logger.info(f"[{context}] Candidate notes after model_type filter: {len(note_candidates)}")
        utils.logger.info(f"[{context}] Duplicate note ids within current batch: {duplicate_note_ids_in_batch}")
        utils.logger.info(f"[{context}] Missing note ids within current batch: {skipped_missing_note_id}")
        utils.logger.info(f"[{context}] Existing note ids in DB: {len(existing_note_ids)}")
        utils.logger.info(f"[{context}] Selected new note items for detail crawl: {len(selected_note_items)}")
        utils.logger.info(f"[{context}] Skipped existing note ids in DB: {skipped_existing_note_ids}")

        if duplicate_note_id_samples:
            utils.logger.info(
                f"[{context}] Sample duplicate note_ids within current batch: {duplicate_note_id_samples}"
            )
        if skipped_existing_note_id_samples:
            utils.logger.info(
                f"[{context}] Sample skipped existing note_ids in DB: {skipped_existing_note_id_samples}"
            )

        return selected_note_items

    def _extract_search_candidate_publish_time_raw(self, post_item: Dict) -> str:
        raw_text = xhs_store.extract_xhs_search_publish_time_text(post_item)
        if raw_text:
            return raw_text

        note_card = post_item.get("note_card")
        if isinstance(note_card, dict):
            raw_text = xhs_store.extract_xhs_search_publish_time_text(note_card)
            if raw_text:
                return raw_text

        return ""

    def _sort_new_note_items_by_publish_time(
        self,
        note_items: List[Dict],
        *,
        context: str,
    ) -> List[Dict]:
        utils.logger.info(f"[{context}] New note candidates before publish-time sort: {len(note_items)}")
        if not note_items:
            utils.logger.info(f"[{context}] New note candidates with resolved publish time: 0")
            return []

        crawl_ts_ms = utils.get_current_timestamp()
        sortable_candidates: List[Dict[str, Any]] = []
        resolved_publish_time_count = 0

        for original_index, post_item in enumerate(note_items):
            note_id = str(post_item.get("id") or "").strip()
            publish_time_raw = self._extract_search_candidate_publish_time_raw(post_item)
            normalized_publish_fields = xhs_store.resolve_xhs_note_publish_time(
                {"_search_publish_time_raw": publish_time_raw},
                crawl_ts_ms=crawl_ts_ms,
            )
            publish_timestamp_ms = normalized_publish_fields.get("publish_timestamp_ms")
            publish_date = normalized_publish_fields.get("publish_date")
            has_resolved_publish_time = bool(publish_timestamp_ms is not None or publish_date)
            if has_resolved_publish_time:
                resolved_publish_time_count += 1

            sortable_candidates.append(
                {
                    "item": post_item,
                    "note_id": note_id,
                    "publish_time_raw": publish_time_raw,
                    "publish_timestamp_ms": publish_timestamp_ms,
                    "publish_date": publish_date,
                    "original_index": original_index,
                    "has_resolved_publish_time": has_resolved_publish_time,
                }
            )

        sorted_candidates = sorted(
            sortable_candidates,
            key=lambda candidate: (
                0 if candidate["has_resolved_publish_time"] else 1,
                -(candidate["publish_timestamp_ms"] or 0) if candidate["has_resolved_publish_time"] else 0,
                candidate["original_index"],
            ),
        )

        preview_payload = [
            {
                "note_id": candidate["note_id"],
                "publish_time_raw": candidate["publish_time_raw"],
                "resolved_publish_date": candidate["publish_date"],
                "resolved_publish_timestamp_ms": candidate["publish_timestamp_ms"],
                "original_index": candidate["original_index"],
            }
            for candidate in sorted_candidates[:5]
        ]
        utils.logger.info(f"[{context}] New note candidates with resolved publish time: {resolved_publish_time_count}")
        utils.logger.info(f"[{context}] Publish-time sorted candidate preview: {preview_payload}")
        return [candidate["item"] for candidate in sorted_candidates]

    def _is_xhs_related_url(self, url: str) -> bool:
        normalized_url = str(url or "").strip().lower()
        if not normalized_url:
            return False
        return "xiaohongshu.com" in normalized_url or "rednote.com" in normalized_url

    def _classify_xhs_page_issue(
        self,
        *,
        url: str,
        title: str,
        body_text: str,
    ) -> str:
        normalized_text = " ".join(
            part for part in (url, title, body_text[:1000]) if part
        ).lower()

        risk_keywords = (
            "\u8bf7\u6c42\u592a\u9891\u7e41",
            "\u8bf7\u7a0d\u540e\u518d\u8bd5",
            "\u5b89\u5168\u9a8c\u8bc1",
            "\u9a8c\u8bc1\u7801",
            "\u98ce\u63a7",
            "captcha",
            "verify",
            "risk",
            "security verification",
            "request too frequent",
            "too frequent",
        )
        if any(keyword in normalized_text for keyword in risk_keywords):
            return "risk_page"

        login_keywords = (
            "\u767b\u5f55",
            "\u626b\u7801\u767b\u5f55",
            "\u767b\u5f55\u540e\u7ee7\u7eed",
            "\u8bf7\u5148\u767b\u5f55",
            "login",
            "sign in",
            "scan code",
        )
        if any(keyword in normalized_text for keyword in login_keywords):
            return "login_page"

        abnormal_keywords = (
            "about:blank",
            "\u5f02\u5e38",
            "\u7cfb\u7edf\u5f02\u5e38",
            "\u51fa\u9519",
            "\u7f51\u9875\u8d70\u4e22",
            "error",
            "found .",
        )
        if any(keyword in normalized_text for keyword in abnormal_keywords):
            return "abnormal_page"

        return ""

    async def _is_xhs_risk_or_login_page(self, page: Page) -> bool:
        healthy, reason, _ = await self._inspect_xhs_page_health(page)
        return not healthy and reason in {"risk_page", "login_page"}

    async def _inspect_xhs_page_health(self, page: Page) -> Tuple[bool, str, Dict[str, str]]:
        info: Dict[str, str] = {
            "url": "",
            "title": "",
            "body_preview": "",
            "ready_state": "",
        }

        if page.is_closed():
            return False, "page_closed", info

        try:
            info["url"] = str(page.url or "").strip()
        except Exception:
            return False, "page_unavailable", info

        if not info["url"] or info["url"] == "about:blank":
            return False, "about_blank", info

        if not self._is_xhs_related_url(info["url"]):
            return False, "non_xhs_url", info

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

        try:
            info["ready_state"] = await page.evaluate("() => document.readyState")
        except Exception:
            return False, "page_eval_failed", info

        if info["ready_state"] != "complete":
            return False, "document_not_ready", info

        try:
            info["title"] = str((await page.title()) or "").strip()
        except Exception:
            info["title"] = ""

        try:
            info["body_preview"] = await page.evaluate(
                """() => {
                    const text = ((document.body && document.body.innerText) || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                    return text.slice(0, 500);
                }"""
            )
        except Exception:
            info["body_preview"] = ""

        if not info["body_preview"]:
            return False, "empty_body", info

        page_issue = self._classify_xhs_page_issue(
            url=info["url"],
            title=info["title"],
            body_text=info["body_preview"],
        )
        if page_issue:
            return False, page_issue, info

        if not info["title"]:
            return False, "empty_title", info

        return True, "", info

    async def _is_page_healthy_for_xhs(self, page: Page) -> bool:
        healthy, _, _ = await self._inspect_xhs_page_health(page)
        return healthy

    async def _pick_best_xhs_page_or_none(self) -> Optional[Page]:
        xhs_pages = [
            page for page in self.browser_context.pages
            if self._is_xhs_related_url(getattr(page, "url", ""))
        ]
        utils.logger.info(
            f"[XiaoHongShuCrawler] Found {len(xhs_pages)} existing XHS-related pages in current browser context"
        )

        best_page: Optional[Page] = None
        best_score = -1
        for page in xhs_pages:
            healthy, reason, info = await self._inspect_xhs_page_health(page)
            if not healthy:
                utils.logger.info(
                    f"[XiaoHongShuCrawler] Existing XHS page is unhealthy, reason: {reason}, "
                    f"url: {info.get('url', '')}, title: {info.get('title', '')}, "
                    f"body_preview: {info.get('body_preview', '')}"
                )
                continue

            score = 0
            page_url = info.get("url", "")
            if "/explore" in page_url:
                score += 20
            if "/search" in page_url:
                score += 10
            score += min(len(info.get("body_preview", "")), 500) // 50

            if score > best_score:
                best_score = score
                best_page = page

        return best_page

    async def _pick_unhealthy_xhs_page_for_cleanup_or_none(self) -> Tuple[Optional[Page], str, Dict[str, str]]:
        xhs_pages = [
            page for page in self.browser_context.pages
            if self._is_xhs_related_url(getattr(page, "url", ""))
        ]

        selected_page: Optional[Page] = None
        selected_reason = ""
        selected_info: Dict[str, str] = {}
        best_score = -1

        for page in xhs_pages:
            healthy, reason, info = await self._inspect_xhs_page_health(page)
            if healthy:
                continue

            page_url = info.get("url", "")
            score = 0
            if "/explore" in page_url:
                score += 20
            if "/search" in page_url:
                score += 10
            if reason in {"risk_page", "login_page"}:
                score += 5

            if score > best_score:
                best_score = score
                selected_page = page
                selected_reason = reason
                selected_info = info

        return selected_page, selected_reason, selected_info

    async def _get_or_create_healthy_xhs_page(self, *, force_fresh: bool = False) -> Page:
        if not force_fresh:
            best_existing_page = await self._pick_best_xhs_page_or_none()
            if best_existing_page:
                utils.logger.info(
                    f"[XiaoHongShuCrawler] Reusing healthy existing XHS page: {best_existing_page.url}"
                )
                try:
                    await best_existing_page.bring_to_front()
                except Exception:
                    pass
                return best_existing_page

        unhealthy_page, unhealthy_reason, unhealthy_info = await self._pick_unhealthy_xhs_page_for_cleanup_or_none()
        if unhealthy_page is not None:
            utils.logger.warning(
                f"[XiaoHongShuCrawler] Existing XHS page is unhealthy, closing it. "
                f"reason={unhealthy_reason}, url={unhealthy_info.get('url', '')}, "
                f"title={unhealthy_info.get('title', '')}, body_preview={unhealthy_info.get('body_preview', '')}"
            )
            try:
                await unhealthy_page.close()
                utils.logger.info("[XiaoHongShuCrawler] Closed unhealthy XHS page successfully")
            except Exception as ex:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler] Failed to close unhealthy XHS page, continue with fresh page creation: {ex}"
                )

        utils.logger.info("[XiaoHongShuCrawler] No healthy existing XHS page found, creating a new page")
        try:
            page = await self.browser_context.new_page()
        except Exception as ex:
            utils.logger.error(f"[XiaoHongShuCrawler] Failed to create fresh XHS page: {ex}")
            raise

        utils.logger.info("[XiaoHongShuCrawler] Created fresh XHS page after unhealthy page cleanup")
        utils.logger.info("[XiaoHongShuCrawler] Created fresh XHS page and navigating to explore")
        try:
            await page.goto(self.index_url, wait_until="domcontentloaded")
        except Exception as ex:
            utils.logger.warning(
                f"[XiaoHongShuCrawler] Failed to navigate fresh XHS page to explore: {ex}"
            )

        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        healthy, reason, info = await self._inspect_xhs_page_health(page)
        if healthy:
            utils.logger.info(
                f"[XiaoHongShuCrawler] Fresh XHS page is healthy and ready: {info.get('url', page.url)}"
            )
        else:
            utils.logger.warning(
                f"[XiaoHongShuCrawler] Fresh XHS page is not fully healthy, reason: {reason}, "
                f"url: {info.get('url', page.url)}, title: {info.get('title', '')}, "
                f"body_preview: {info.get('body_preview', '')}"
            )
        return page

    def _collect_successful_note_details(
        self,
        scheduled_note_ids: List[str],
        gather_results: List[Any],
        *,
        context: str,
    ) -> Tuple[List[Dict], List[str]]:
        success_note_details: List[Dict] = []
        failed_note_ids: List[str] = []

        for index, result in enumerate(gather_results):
            note_id = scheduled_note_ids[index] if index < len(scheduled_note_ids) else "unknown"
            if isinstance(result, Exception):
                failed_note_ids.append(note_id)
                utils.logger.error(
                    f"[{context}] Note detail task raised unexpected exception, note_id: {note_id}, error: {result}"
                )
                continue
            if not result:
                failed_note_ids.append(note_id)
                continue
            success_note_details.append(result)

        utils.logger.info(
            f"[{context}] Detail crawl summary - scheduled: {len(scheduled_note_ids)}, "
            f"success: {len(success_note_details)}, failed: {len(failed_note_ids)}, "
            f"failed note_ids: {failed_note_ids}"
        )
        return success_note_details, failed_note_ids

    async def _get_context_page(self) -> Page:
        return await self._get_or_create_healthy_xhs_page()

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[XiaoHongShuCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self._get_context_page()

            # Create a client to interact with the Xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
            login_state_ok = await self.xhs_client.pong()
            if not login_state_ok:
                utils.logger.info("[XiaoHongShuCrawler.start] Re-check login state on fresh page")
                self.context_page = await self._get_or_create_healthy_xhs_page(force_fresh=True)
                self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
                login_state_ok = await self.xhs_client.pong()
                if login_state_ok:
                    utils.logger.info("[XiaoHongShuCrawler.start] Skip QR login because page recovery succeeded")

            if not login_state_ok:
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass

            utils.logger.info("[XiaoHongShuCrawler.start] Xhs Crawler finished ...")

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.search] Begin search Xiaohongshu keywords")
        max_notes_count = self._get_effective_detail_fetch_limit()
        if max_notes_count <= 0:
            utils.logger.info("[XiaoHongShuCrawler.search] CRAWLER_MAX_NOTES_COUNT <= 0, skip search")
            return
        utils.logger.info(
            f"[XiaoHongShuCrawler.search] Conservative detail mode: {self._is_conservative_detail_mode()}, "
            f"effective detail scheduling limit: {max_notes_count}"
        )
        start_page = config.START_PAGE
        for keyword in config.KEYWORDS.split(","):
            self._reset_detail_run_state()
            keyword = keyword.strip()
            if not keyword:
                continue

            source_keyword_var.set(keyword)
            utils.logger.info(f"[XiaoHongShuCrawler.search] Current search keyword: {keyword}")
            page = 1
            search_id = get_search_id()
            scheduled_note_count = 0
            history_state = self._build_crawl_history_state(keyword)
            history_failed_note_ids: List[str] = []
            history_store_failed_note_ids: List[str] = []
            history_stored_note_ids: List[str] = []
            await self._create_crawl_history_record(history_state)

            try:
                while scheduled_note_count < max_notes_count and not self.detail_stop_requested:
                    if page < start_page:
                        utils.logger.info(f"[XiaoHongShuCrawler.search] Skip page {page}")
                        page += 1
                        continue

                    try:
                        utils.logger.info(f"[XiaoHongShuCrawler.search] search Xiaohongshu keyword: {keyword}, page: {page}")
                        note_ids: List[str] = []
                        xsec_tokens: List[str] = []
                        notes_res = await self.xhs_client.get_note_by_keyword(
                            keyword=keyword,
                            search_id=search_id,
                            page=page,
                            sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE != "" else SearchSortType.GENERAL),
                        )
                        utils.logger.info(f"[XiaoHongShuCrawler.search] Search notes response: {notes_res}")
                        if not notes_res:
                            utils.logger.info("[XiaoHongShuCrawler.search] Empty search response, stop current keyword")
                            history_state["stop_reason"] = history_state.get("stop_reason") or "empty_search_response"
                            break

                        remaining_quota = max_notes_count - scheduled_note_count
                        items = notes_res.get("items", [])
                        selected_note_items = await self._filter_new_note_items_before_detail(
                            items,
                            remaining_quota=remaining_quota,
                            context="XiaoHongShuCrawler.search",
                        )
                        history_state["planned_detail_count"] += len(selected_note_items)
                        utils.logger.info(
                            f"[XiaoHongShuCrawler.search] Selected {len(selected_note_items)} note items for detail crawl "
                            f"(filtered from {len(items)} search items, remaining quota before scheduling: {remaining_quota})"
                        )
                        search_publish_time_hints = {
                            str(post_item.get("id") or "").strip(): self._extract_search_candidate_publish_time_raw(post_item)
                            for post_item in selected_note_items
                        }

                        if not selected_note_items:
                            if not notes_res.get("has_more", False):
                                utils.logger.info("[XiaoHongShuCrawler.search] No more new note content!")
                                history_state["stop_reason"] = history_state.get("stop_reason") or "no_more_new_note_content"
                                break

                            page += 1
                            utils.logger.info(
                                "[XiaoHongShuCrawler.search] No new note items selected on current page, continue to next page"
                            )
                            continue

                        if self._is_conservative_detail_mode():
                            note_details, failed_note_ids = await self._crawl_note_details_serially(
                                selected_note_items,
                                note_id_key="id",
                                xsec_source_key="xsec_source",
                                xsec_token_key="xsec_token",
                                context="XiaoHongShuCrawler.search",
                                before_detail_batch_sleep=True,
                            )
                            scheduled_note_count += len(note_details) + len(failed_note_ids)
                        else:
                            semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                            scheduled_note_ids = [post_item.get("id", "") for post_item in selected_note_items]
                            task_list = [
                                self.get_note_detail_async_task(
                                    note_id=post_item.get("id"),
                                    xsec_source=post_item.get("xsec_source"),
                                    xsec_token=post_item.get("xsec_token"),
                                    semaphore=semaphore,
                                ) for post_item in selected_note_items
                            ]
                            scheduled_note_count += len(selected_note_items)
                            note_details_results = await asyncio.gather(*task_list, return_exceptions=True)
                            note_details, failed_note_ids = self._collect_successful_note_details(
                                scheduled_note_ids,
                                note_details_results,
                                context="XiaoHongShuCrawler.search",
                            )

                        history_state["success_detail_count"] += len(note_details)
                        history_state["failed_detail_count"] += len(failed_note_ids)
                        history_failed_note_ids.extend([note_id for note_id in failed_note_ids if note_id])

                        stored_note_ids: List[str] = []
                        store_failed_note_ids: List[str] = []
                        for note_detail in note_details:
                            if note_detail:
                                note_id = note_detail.get("note_id", "")
                                if note_id:
                                    note_detail["_search_publish_time_raw"] = search_publish_time_hints.get(note_id, "")
                                try:
                                    await xhs_store.update_xhs_note(note_detail)
                                    stored_note_ids.append(note_id)
                                    history_stored_note_ids.append(note_id)
                                    note_ids.append(note_id)
                                    xsec_tokens.append(note_detail.get("xsec_token"))
                                except Exception as ex:
                                    store_failed_note_ids.append(note_id)
                                    history_store_failed_note_ids.append(note_id)
                                    utils.logger.error(
                                        f"[XiaoHongShuCrawler.search] Failed to store note detail, note_id: {note_id}, error: {ex}"
                                    )
                                    continue

                                try:
                                    await self.get_notice_media(note_detail)
                                except Exception as ex:
                                    utils.logger.error(
                                        f"[XiaoHongShuCrawler.search] Failed to process note media/export, "
                                        f"note_id: {note_id}, error: {ex}"
                                    )

                        utils.logger.info(
                            f"[XiaoHongShuCrawler.search] Note persistence summary - "
                            f"stored: {len(stored_note_ids)}, store_failed: {len(store_failed_note_ids)}, "
                            f"stored note_ids: {stored_note_ids}, store_failed note_ids: {store_failed_note_ids}"
                        )
                        page += 1
                        utils.logger.info(
                            f"[XiaoHongShuCrawler.search] Successful note details count: {len(note_details)}, "
                            f"failed note ids in current batch: {failed_note_ids}"
                        )
                        await self.batch_get_note_comments(note_ids, xsec_tokens)

                        if scheduled_note_count >= max_notes_count:
                            utils.logger.info(
                                f"[XiaoHongShuCrawler.search] Reached detail scheduling limit: {scheduled_note_count}/{max_notes_count}"
                            )
                            history_state["stop_reason"] = history_state.get("stop_reason") or "detail_limit_reached"
                            break
                        if self.detail_stop_requested:
                            utils.logger.warning(
                                f"[XiaoHongShuCrawler.search] Stop current keyword due to: "
                                f"{self.detail_stop_reason or 'detail_stop_requested'}"
                            )
                            break
                        if not notes_res.get("has_more", False):
                            utils.logger.info("[XiaoHongShuCrawler.search] No more content!")
                            history_state["stop_reason"] = history_state.get("stop_reason") or "no_more_content"
                            break

                        if self._is_conservative_detail_mode():
                            utils.logger.info(
                                "[XiaoHongShuCrawler.search] Conservative detail mode enabled, "
                                "skip fixed page sleep because detail throttle is handled before each detail fetch"
                            )
                        else:
                            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                            utils.logger.info(
                                f"[XiaoHongShuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}"
                            )
                    except DataFetchError:
                        utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")
                        if not self.detail_stop_reason:
                            self.detail_stop_reason = "data_fetch_error"
                        break
                    except Exception as ex:
                        utils.logger.error(f"[XiaoHongShuCrawler.search] Unexpected error: {ex}")
                        if not self.detail_stop_reason:
                            self.detail_stop_reason = "unknown_error"
                        break
            finally:
                await self._finalize_crawl_history_record(
                    history_state,
                    failed_note_ids=history_failed_note_ids,
                    extra_payload={
                        "conservative_detail_mode": self._is_conservative_detail_mode(),
                        "effective_detail_fetch_limit": max_notes_count,
                        "scheduled_detail_count": scheduled_note_count,
                        "stored_note_ids": history_stored_note_ids,
                        "store_failed_note_ids": history_store_failed_note_ids,
                        "skip_existing_note_details": bool(getattr(config, "XHS_SKIP_EXISTING_NOTE_DETAILS", True)),
                    },
                )

            if self.detail_stop_requested:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.search] Stop remaining keywords for current run due to: "
                    f"{self.detail_stop_reason or 'detail_stop_requested'}"
                )
                break

    async def get_creators_and_notes(self) -> None:
        """Get creator's notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] Begin get Xiaohongshu creators")
        for creator_url in config.XHS_CREATOR_ID_LIST:
            self._reset_detail_run_state()
            try:
                # Parse creator URL to get user_id and security tokens
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                # get creator detail info from web html content
                createor_info: Dict = await self.xhs_client.get_creator_info(
                    user_id=user_id,
                    xsec_token=creator_info.xsec_token,
                    xsec_source=creator_info.xsec_source
                )
                if createor_info:
                    await xhs_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[XiaoHongShuCrawler.get_creators_and_notes] Failed to parse creator URL: {e}")
                continue

            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            # Get all note information of the creator
            all_notes_list = await self.xhs_client.get_all_notes_by_creator(
                user_id=user_id,
                crawl_interval=crawl_interval,
                callback=self.fetch_creator_notes_detail,
                xsec_token=creator_info.xsec_token,
                xsec_source=creator_info.xsec_source,
            )

            if self.detail_stop_requested:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_creators_and_notes] Stop current creator run due to: "
                    f"{self.detail_stop_reason or 'detail_stop_requested'}"
                )

            note_ids = []
            xsec_tokens = []
            for note_item in all_notes_list:
                note_ids.append(note_item.get("note_id"))
                xsec_tokens.append(note_item.get("xsec_token"))
            await self.batch_get_note_comments(note_ids, xsec_tokens)

            if self.detail_stop_requested:
                break

    async def fetch_creator_notes_detail(self, note_list: List[Dict]):
        """Serially obtain the specified post list and save the data"""
        if self.detail_stop_requested:
            utils.logger.warning(
                "[XiaoHongShuCrawler.fetch_creator_notes_detail] Detail stop flag is already set, skip creator note details"
            )
            return

        selected_note_list = note_list[: self._get_effective_detail_fetch_limit()] if self._is_conservative_detail_mode() else note_list
        utils.logger.info(
            f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Selected {len(selected_note_list)} creator note items for detail crawl"
        )
        if self._is_conservative_detail_mode():
            note_details, _ = await self._crawl_note_details_serially(
                selected_note_list,
                note_id_key="note_id",
                xsec_source_key="xsec_source",
                xsec_token_key="xsec_token",
                context="XiaoHongShuCrawler.fetch_creator_notes_detail",
            )
        else:
            semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
            task_list = [
                self.get_note_detail_async_task(
                    note_id=post_item.get("note_id"),
                    xsec_source=post_item.get("xsec_source"),
                    xsec_token=post_item.get("xsec_token"),
                    semaphore=semaphore,
                ) for post_item in selected_note_list
            ]

            scheduled_note_ids = [post_item.get("note_id", "") for post_item in selected_note_list]
            note_details_results = await asyncio.gather(*task_list, return_exceptions=True)
            note_details, _ = self._collect_successful_note_details(
                scheduled_note_ids,
                note_details_results,
                context="XiaoHongShuCrawler.fetch_creator_notes_detail",
            )
        for note_detail in note_details:
            if note_detail:
                note_id = note_detail.get("note_id", "")
                try:
                    await xhs_store.update_xhs_note(note_detail)
                except Exception as ex:
                    utils.logger.error(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Failed to store note detail, "
                        f"note_id: {note_id}, error: {ex}"
                    )
                    continue

                try:
                    await self.get_notice_media(note_detail)
                except Exception as ex:
                    utils.logger.error(
                        f"[XiaoHongShuCrawler.fetch_creator_notes_detail] Failed to process note media/export, "
                        f"note_id: {note_id}, error: {ex}"
                    )

    async def get_specified_notes(self):
        """Get the information and comments of the specified post

        Note: Must specify note_id, xsec_source, xsec_token
        """
        self._reset_detail_run_state()
        note_url_items: List[Dict[str, str]] = []
        for full_note_url in config.XHS_SPECIFIED_NOTE_URL_LIST:
            note_url_info: NoteUrlInfo = parse_note_info_from_note_url(full_note_url)
            utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Parse note url info: {note_url_info}")
            note_url_items.append(
                {
                    "note_id": note_url_info.note_id,
                    "xsec_source": note_url_info.xsec_source,
                    "xsec_token": note_url_info.xsec_token,
                }
            )

        selected_note_url_items = (
            note_url_items[: self._get_effective_detail_fetch_limit()]
            if self._is_conservative_detail_mode()
            else note_url_items
        )
        utils.logger.info(
            f"[XiaoHongShuCrawler.get_specified_notes] Selected {len(selected_note_url_items)} note items for detail crawl"
        )

        need_get_comment_note_ids = []
        xsec_tokens = []
        if self._is_conservative_detail_mode():
            note_details, _ = await self._crawl_note_details_serially(
                selected_note_url_items,
                note_id_key="note_id",
                xsec_source_key="xsec_source",
                xsec_token_key="xsec_token",
                context="XiaoHongShuCrawler.get_specified_notes",
            )
        else:
            get_note_detail_task_list = [
                self.get_note_detail_async_task(
                    note_id=post_item.get("note_id"),
                    xsec_source=post_item.get("xsec_source"),
                    xsec_token=post_item.get("xsec_token"),
                    semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
                ) for post_item in selected_note_url_items
            ]
            scheduled_note_ids = [post_item.get("note_id", "") for post_item in selected_note_url_items]
            note_details_results = await asyncio.gather(*get_note_detail_task_list, return_exceptions=True)
            note_details, _ = self._collect_successful_note_details(
                scheduled_note_ids,
                note_details_results,
                context="XiaoHongShuCrawler.get_specified_notes",
            )
        for note_detail in note_details:
            if note_detail:
                note_id = note_detail.get("note_id", "")
                try:
                    await xhs_store.update_xhs_note(note_detail)
                    need_get_comment_note_ids.append(note_id)
                    xsec_tokens.append(note_detail.get("xsec_token", ""))
                except Exception as ex:
                    utils.logger.error(
                        f"[XiaoHongShuCrawler.get_specified_notes] Failed to store note detail, "
                        f"note_id: {note_id}, error: {ex}"
                    )
                    continue

                try:
                    await self.get_notice_media(note_detail)
                except Exception as ex:
                    utils.logger.error(
                        f"[XiaoHongShuCrawler.get_specified_notes] Failed to process note media/export, "
                        f"note_id: {note_id}, error: {ex}"
                    )
        await self.batch_get_note_comments(need_get_comment_note_ids, xsec_tokens)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        semaphore: asyncio.Semaphore,
    ) -> Optional[Dict]:
        """Get note detail

        Args:
            note_id:
            xsec_source:
            xsec_token:
            semaphore:

        Returns:
            Dict: note detail
        """
        note_detail = None
        utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")
        async with semaphore:
            try:
                if self._is_conservative_detail_mode():
                    await self._sleep_random_range(
                        getattr(config, "XHS_DETAIL_PRE_SLEEP_MIN_SEC", 60),
                        getattr(config, "XHS_DETAIL_PRE_SLEEP_MAX_SEC", 120),
                        label="before detail fetch",
                        note_id=note_id,
                    )

                api_hit_captcha = False
                if not self.prefer_html_note_detail:
                    try:
                        note_detail = await self.xhs_client.get_note_by_id(note_id, xsec_source, xsec_token)
                    except CaptchaBlockError as ex:
                        api_hit_captcha = True
                        utils.logger.warning(
                            f"[XiaoHongShuCrawler.get_note_detail_async_task] API detail request hit CAPTCHA for note {note_id}: {ex}"
                        )
                        if self._is_conservative_detail_mode():
                            self._mark_detail_run_stop(
                                reason="api_detail_captcha",
                                note_id=note_id,
                                risk_control=True,
                            )
                            utils.logger.warning(
                                "[XiaoHongShuCrawler.get_note_detail_async_task] Conservative detail mode enabled, "
                                f"skip HTML fallback after API CAPTCHA for note {note_id}"
                            )
                            return None

                        self.prefer_html_note_detail = True
                        utils.logger.info(
                            "[XiaoHongShuCrawler.get_note_detail_async_task] Switching remaining detail requests to HTML-first mode"
                        )
                    except DataFetchError as ex:
                        utils.logger.warning(
                            f"[XiaoHongShuCrawler.get_note_detail_async_task] API detail request failed for note {note_id}, "
                            f"switching to HTML fallback: {ex}"
                        )
                else:
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_note_detail_async_task] HTML-first mode enabled, skip API detail for note {note_id}"
                    )

                if not note_detail:
                    if api_hit_captcha:
                        captcha_backoff_sec = max(config.CRAWLER_MAX_SLEEP_SEC * 2, 15)
                        utils.logger.info(
                            f"[XiaoHongShuCrawler.get_note_detail_async_task] Sleeping for {captcha_backoff_sec} seconds "
                            f"before HTML fallback after CAPTCHA for note {note_id}"
                        )
                        await asyncio.sleep(captcha_backoff_sec)

                    note_detail = await self.xhs_client.get_note_by_id_from_html(
                        note_id,
                        xsec_source,
                        xsec_token,
                        enable_cookie=True,
                    )
                    if not note_detail:
                        html_failure_type = getattr(self.xhs_client, "last_html_fallback_failure_type", "")
                        if html_failure_type == "html_fallback_risk_page":
                            self._mark_detail_run_stop(
                                reason=html_failure_type,
                                note_id=note_id,
                                risk_control=True,
                            )
                        utils.logger.error(
                            f"[XiaoHongShuCrawler.get_note_detail_async_task] Failed to get note detail after API + HTML fallback, "
                            f"note_id: {note_id}, failure_type: {html_failure_type or 'unknown'}"
                        )
                        return None

                note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})
                html_fallback_status = note_detail.get("_html_fallback_status")
                if html_fallback_status:
                    utils.logger.info(
                        f"[XiaoHongShuCrawler.get_note_detail_async_task] HTML fallback status for note {note_id}: "
                        f"{html_fallback_status}, source: {note_detail.get('_html_fallback_source', '')}"
                    )

                if self._is_conservative_detail_mode():
                    await self._sleep_random_range(
                        getattr(config, "XHS_DETAIL_POST_SLEEP_MIN_SEC", 120),
                        getattr(config, "XHS_DETAIL_POST_SLEEP_MAX_SEC", 180),
                        label="after detail success",
                        note_id=note_id,
                    )
                else:
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(
                        f"[get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note {note_id}"
                    )

                return note_detail

            except NoteNotFoundError as ex:
                utils.logger.warning(f"[XiaoHongShuCrawler.get_note_detail_async_task] Note not found: {note_id}, {ex}")
                return None
            except CaptchaBlockError as ex:
                self._mark_detail_run_stop(
                    reason="html_fallback_captcha",
                    note_id=note_id,
                    risk_control=True,
                )
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_note_detail_async_task] HTML fallback also hit CAPTCHA for note {note_id}: {ex}"
                )
                return None
            except DataFetchError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None
            except Exception as ex:
                utils.logger.error(
                    f"[XiaoHongShuCrawler.get_note_detail_async_task] Unexpected error when getting note detail, "
                    f"note_id: {note_id}, error: {ex}"
                )
                return None

    async def batch_get_note_comments(self, note_list: List[str], xsec_tokens: List[str]):
        """Batch get note comments"""
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Begin batch get note comments, note list: {note_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for index, note_id in enumerate(note_list):
            task = asyncio.create_task(
                self.get_comments(note_id=note_id, xsec_token=xsec_tokens[index], semaphore=semaphore),
                name=note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, note_id: str, xsec_token: str, semaphore: asyncio.Semaphore):
        """Get note comments with keyword filtering and quantity limitation"""
        async with semaphore:
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Begin get note id comments {note_id}")
            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            await self.xhs_client.get_note_all_comments(
                note_id=note_id,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=xhs_store.batch_update_xhs_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

            # Sleep after fetching comments
            await asyncio.sleep(crawl_interval)
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for note {note_id}")

    async def create_xhs_client(self, httpx_proxy: Optional[str]) -> XiaoHongShuClient:
        """Create Xiaohongshu client"""
        utils.logger.info("[XiaoHongShuCrawler.create_xhs_client] Begin create Xiaohongshu API client ...")
        cookie_urls = list(self.cookie_urls)
        if self.context_page and self._is_xhs_related_url(self.context_page.url):
            cookie_urls.append(self.context_page.url)

        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=list(dict.fromkeys(cookie_urls)),
        )
        if not cookie_dict.get("web_session") or not cookie_dict.get("a1"):
            utils.logger.info(
                "[XiaoHongShuCrawler.create_xhs_client] XHS cookie extraction from filtered URLs is incomplete, retrying with full context cookies"
            )
            fallback_cookie_str, fallback_cookie_dict = await utils.convert_browser_context_cookies(
                self.browser_context,
            )
            if fallback_cookie_dict.get("web_session") or fallback_cookie_dict.get("a1"):
                cookie_str, cookie_dict = fallback_cookie_str, fallback_cookie_dict

        xhs_client_obj = XiaoHongShuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": self.index_url,
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": f"{self.index_url}/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return xhs_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[XiaoHongShuCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser using CDP mode"""
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[XiaoHongShuCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[XiaoHongShuCrawler.close] Browser context closed ...")

    async def get_notice_media(self, note_detail: Dict):
        should_download_images = getattr(config, "XHS_DOWNLOAD_NOTE_IMAGES", False)
        should_download_videos = config.ENABLE_GET_MEIDAS
        should_export_enhanced = getattr(config, "XHS_EXPORT_ENHANCED_JSON", False)

        if not should_download_images and not should_download_videos and not should_export_enhanced:
            utils.logger.info(
                "[XiaoHongShuCrawler.get_notice_media] Image download, video download and enhanced JSON export are all disabled"
            )
            return

        image_download_meta: List[Dict] = []
        if should_download_images:
            try:
                image_download_meta = await self.get_note_images(note_detail)
            except Exception as ex:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_notice_media] Failed to download note images for note "
                    f"{note_detail.get('note_id')}: {ex}"
                )
        else:
            note_detail["local_image_list"] = image_download_meta

        if should_download_videos:
            try:
                await self.get_notice_video(note_detail)
            except Exception as ex:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_notice_media] Failed to download note video for note "
                    f"{note_detail.get('note_id')}: {ex}"
                )

        if should_export_enhanced:
            try:
                json_path = await xhs_store.export_xhs_note_enhanced(
                    note_detail,
                    image_download_meta=image_download_meta,
                )
                utils.logger.info(
                    f"[XiaoHongShuCrawler.get_notice_media] Exported enhanced note json to {json_path}"
                )
            except Exception as ex:
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_notice_media] Failed to export enhanced json for note "
                    f"{note_detail.get('note_id')}: {ex}"
                )

    async def get_note_images(self, note_item: Dict):
        """Get note images. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        image_download_meta: List[Dict] = []
        note_item["local_image_list"] = image_download_meta
        if not getattr(config, "XHS_DOWNLOAD_NOTE_IMAGES", False):
            return image_download_meta

        note_id = note_item.get("note_id")
        image_list: List[Dict] = xhs_store.normalize_xhs_image_entries(note_item.get("image_list", []))
        if not note_id or not image_list:
            return image_download_meta

        referer = note_item.get("note_url") or f"{self.index_url}/explore/{note_id}"
        download_sleep_sec = max(0.0, getattr(config, "XHS_MEDIA_DOWNLOAD_SLEEP_SEC", 1))

        for index, pic in enumerate(image_list, start=1):
            url = pic.get("url", "")
            image_meta = {
                "index": index,
                "original_url": url,
                "final_url": "",
                "local_path": "",
                "download_status": "skipped",
            }
            if not url:
                image_meta["download_status"] = "missing_url"
                image_download_meta.append(image_meta)
                continue

            existing_local_path = xhs_store.find_existing_xhs_note_image(note_id, index)
            if existing_local_path:
                image_meta.update(
                    {
                        "final_url": url,
                        "local_path": existing_local_path,
                        "download_status": "skipped_existing",
                    }
                )
                image_download_meta.append(image_meta)
                continue

            try:
                download_result = await self.xhs_client.download_note_media(url, referer=referer)
                if not download_result.get("success"):
                    image_meta.update(
                        {
                            "final_url": download_result.get("final_url", ""),
                            "download_status": "failed",
                            "error": download_result.get("error", "download failed"),
                        }
                    )
                    utils.logger.warning(
                        f"[XiaoHongShuCrawler.get_note_images] Failed to download image {index} for note "
                        f"{note_id}: {image_meta['error']}"
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
                        "final_url": download_result.get("final_url") or url,
                        "local_path": (store_result or {}).get("local_path", ""),
                        "download_status": "skipped_existing" if (store_result or {}).get("skipped") else "success",
                    }
                )
                image_download_meta.append(image_meta)
            except Exception as ex:
                image_meta.update({"download_status": "failed", "error": str(ex)})
                image_download_meta.append(image_meta)
                utils.logger.warning(
                    f"[XiaoHongShuCrawler.get_note_images] Unexpected error when downloading image {index} "
                    f"for note {note_id}: {ex}"
                )
            finally:
                if download_sleep_sec > 0:
                    await asyncio.sleep(download_sleep_sec)

        note_item["local_image_list"] = image_download_meta
        return image_download_meta

    async def get_notice_video(self, note_item: Dict):
        """Get note videos. Please use get_notice_media

        Args:
            note_item: Note item dictionary
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")

        videos = xhs_store.get_video_url_arr(note_item)

        if not videos:
            return
        videoNum = 0
        for url in videos:
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{videoNum}.mp4"
            videoNum += 1
            await xhs_store.update_xhs_note_video(note_id, content, extension_file_name)
