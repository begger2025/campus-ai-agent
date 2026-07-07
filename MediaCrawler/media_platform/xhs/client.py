# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/client.py
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
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union
from urllib.parse import quote, urlencode

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_not_exception_type
from tools.httpx_util import make_async_client

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import CaptchaBlockError, DataFetchError, IPBlockError, NoteNotFoundError
from .field import SearchNoteType, SearchSortType
from .help import get_search_id
from .extractor import XiaoHongShuExtractor
from .media_downloader import build_media_request_headers, download_media_bytes
from .playwright_sign import sign_with_xhshow


class XiaoHongShuClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # If media crawling is enabled, Xiaohongshu long videos need longer timeout
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        if config.XHS_INTERNATIONAL:
            self._host = "https://webapi.rednote.com"
            self._domain = "https://www.rednote.com"
        else:
            self._host = "https://edith.xiaohongshu.com"
            self._domain = "https://www.xiaohongshu.com"
        self.cookie_urls = [self._domain]
        self.IP_ERROR_STR = "Network connection error, please check network settings or restart"
        self.IP_ERROR_CODE = 300012
        self.NOTE_NOT_FOUND_CODE = -510000
        self.NOTE_ABNORMAL_STR = "Note status abnormal, please check later"
        self.NOTE_ABNORMAL_CODE = -510001
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._extractor = XiaoHongShuExtractor()
        self.last_html_fallback_failure_type = ""
        self.last_html_fallback_debug: Dict[str, str] = {}
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)

    def _build_note_url(self, note_id: str, xsec_source: str, xsec_token: str) -> str:
        return (
            f"{self._domain}/explore/"
            + note_id
            + f"?xsec_token={xsec_token}&xsec_source={xsec_source}"
        )

    @staticmethod
    def _normalize_preview_text(value: str, max_len: int = 500) -> str:
        if not value:
            return ""
        normalized = re.sub(r"\s+", " ", value).strip()
        return normalized[:max_len]

    def _classify_html_fallback_failure(
        self,
        *,
        final_url: str,
        title: str,
        body_preview: str,
        html: str,
    ) -> str:
        normalized_text = " ".join(
            text for text in (final_url, title, body_preview, html[:1000]) if text
        ).lower()

        if not html.strip() and not body_preview.strip():
            return "html_fallback_empty_content"

        if any(
            keyword in normalized_text
            for keyword in (
                "\u8bf7\u6c42\u592a\u9891\u7e41",
                "\u8bf7\u7a0d\u540e\u518d\u8bd5",
                "\u5b89\u5168\u9a8c\u8bc1",
                "\u9a8c\u8bc1\u7801",
                "\u98ce\u63a7",
                "security verification",
                "request too frequent",
                "too frequent",
            )
        ):
            return "html_fallback_risk_page"

        if any(
            keyword in normalized_text
            for keyword in (
                "\u767b\u5f55",
                "\u8bf7\u5148\u767b\u5f55",
            )
        ):
            return "html_fallback_login_page"

        if "found ." in normalized_text:
            return "html_fallback_404"

        risk_keywords = (
            "captcha",
            "verify",
            "risk",
            "风控",
            "验证",
            "访问异常",
            "异常访问",
            "请求过于频繁",
            "请完成验证",
            "安全验证",
        )
        if any(keyword in normalized_text for keyword in risk_keywords):
            return "html_fallback_risk_page"

        login_keywords = (
            "登录",
            "扫码登录",
            "手机号登录",
            "login",
            "sign in",
            "注册登录",
        )
        if any(keyword in normalized_text for keyword in login_keywords):
            return "html_fallback_login_page"

        not_found_keywords = (
            "404",
            "not found",
            "页面不存在",
            "内容不存在",
            "笔记不存在",
            "无法查看",
            "已被删除",
        )
        if any(keyword in normalized_text for keyword in not_found_keywords):
            return "html_fallback_404"

        return ""

    async def _extract_dom_snapshot_from_page(self, page: Page) -> Dict[str, Any]:
        script = """
        () => {
            const clean = (value) => typeof value === "string"
                ? value.replace(/\\s+/g, " ").trim()
                : "";
            const pickContent = (selector, attr = "content") => {
                const el = document.querySelector(selector);
                if (!el) return "";
                return clean(el.getAttribute(attr) || el[attr] || el.textContent || "");
            };
            const bodyText = clean((document.body && document.body.innerText) || "").slice(0, 5000);
            const title = clean(
                pickContent('meta[property="og:title"]') ||
                pickContent('meta[name="title"]') ||
                ((document.querySelector("h1") || {}).innerText || "") ||
                document.title
            );
            const desc = clean(
                pickContent('meta[name="description"]') ||
                pickContent('meta[property="og:description"]') ||
                ((document.querySelector("article") || {}).innerText || "") ||
                bodyText
            );
            const authorLink = Array.from(document.querySelectorAll('a[href*="/user/profile/"]'))
                .map((el) => el.getAttribute("href") || "")
                .find(Boolean) || "";
            const authorUserIdMatch = authorLink.match(/user\\/profile\\/([^/?]+)/);
            const authorUserId = authorUserIdMatch ? authorUserIdMatch[1] : "";
            const authorNickname = clean(
                pickContent('meta[name="author"]') ||
                ((document.querySelector('[class*="author"]') || {}).textContent || "") ||
                ((document.querySelector('[class*="user"] [class*="name"]') || {}).textContent || "") ||
                ""
            );
            const hashtagMatches = Array.from(bodyText.matchAll(/#([^#\\[\\]\\s]+)/g)).map((match) => clean(match[1]));
            const imageUrls = Array.from(document.images)
                .map((img) => img.currentSrc || img.src || "")
                .filter(Boolean)
                .filter((url) => /xhscdn|xiaohongshu|rednote/i.test(url));
            const publishTime = clean(
                pickContent('meta[property="article:published_time"]') ||
                pickContent('meta[name="article:published_time"]') ||
                ((document.querySelector("time") || {}).getAttribute?.("datetime") || "") ||
                ((document.querySelector("time") || {}).textContent || "")
            );
            return {
                page_title: clean(document.title || ""),
                title,
                desc,
                author_nickname: authorNickname,
                author_user_id: authorUserId,
                tags: Array.from(new Set(hashtagMatches.filter(Boolean))),
                image_urls: Array.from(new Set(imageUrls)),
                body_text: bodyText,
                publish_time: publishTime,
            };
        }
        """
        try:
            dom_snapshot = await page.evaluate(script)
            if isinstance(dom_snapshot, dict):
                return dom_snapshot
        except Exception as ex:
            utils.logger.warning(
                f"[XiaoHongShuClient._extract_dom_snapshot_from_page] Failed to extract DOM snapshot: {ex}"
            )
        return {
            "page_title": "",
            "title": "",
            "desc": "",
            "author_nickname": "",
            "author_user_id": "",
            "tags": [],
            "image_urls": [],
            "body_text": "",
            "publish_time": "",
        }

    async def _extract_window_state_json_candidates(self, page: Page) -> List[tuple[str, str]]:
        script = """
        () => {
            const dump = (key) => {
                try {
                    const value = window[key];
                    if (!value) return "";
                    return JSON.stringify(value);
                } catch (e) {
                    return "";
                }
            };
            return {
                "__INITIAL_STATE__": dump("__INITIAL_STATE__"),
                "__PRELOADED_STATE__": dump("__PRELOADED_STATE__"),
                "__INITIAL_PROPS__": dump("__INITIAL_PROPS__"),
            };
        }
        """
        try:
            state_map = await page.evaluate(script)
        except Exception as ex:
            utils.logger.warning(
                f"[XiaoHongShuClient._extract_window_state_json_candidates] Failed to inspect page state: {ex}"
            )
            return []

        candidates: List[tuple[str, str]] = []
        if not isinstance(state_map, dict):
            return candidates
        for key, value in state_map.items():
            if isinstance(value, str) and value.strip():
                candidates.append((f"window.{key}", value))
        return candidates

    async def _log_html_fallback_debug(
        self,
        *,
        note_id: str,
        note_url: str,
        before_url: str,
        final_url: str,
        title: str,
        body_preview: str,
        failure_type: str,
        goto_error: str = "",
    ) -> None:
        self.last_html_fallback_failure_type = failure_type or ""
        self.last_html_fallback_debug = {
            "note_id": note_id,
            "note_url": note_url,
            "before_url": before_url,
            "final_url": final_url,
            "title": title,
            "body_preview": body_preview,
            "failure_type": failure_type or "",
            "goto_error": goto_error,
        }
        utils.logger.warning(
            f"[XiaoHongShuClient.get_note_by_id_from_html] HTML fallback debug - "
            f"note_id: {note_id}, note_url: {note_url}, before_url: {before_url}, final_url: {final_url}, "
            f"title: {title}, failure_type: {failure_type or 'success'}, goto_error: {goto_error}, "
            f"body_preview: {body_preview}"
        )

    async def _get_note_by_id_from_html_via_browser(
        self,
        note_id: str,
        note_url: str,
    ) -> Optional[Dict]:
        if not self.playwright_page:
            return None

        page: Optional[Page] = None
        before_url = ""
        final_url = ""
        title = ""
        body_preview = ""
        goto_error = ""

        try:
            browser_context = self.playwright_page.context
            page = await browser_context.new_page()
            before_url = page.url
            utils.logger.info(
                f"[XiaoHongShuClient.get_note_by_id_from_html] Begin browser HTML fallback, "
                f"note_id: {note_id}, note_url: {note_url}, before_url: {before_url}"
            )

            try:
                await page.goto(note_url, wait_until="domcontentloaded", timeout=max(30000, int(self.timeout * 1000)))
            except Exception as ex:
                goto_error = str(ex)
                utils.logger.warning(
                    f"[XiaoHongShuClient.get_note_by_id_from_html] page.goto failed for note_id: {note_id}, error: {ex}"
                )

            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            try:
                await page.wait_for_function(
                    """() => {
                        const html = document.documentElement?.innerHTML || "";
                        const bodyText = document.body?.innerText || "";
                        return html.includes("__INITIAL_STATE__")
                            || html.includes("noteDetailMap")
                            || bodyText.length > 120
                            || document.images.length > 0;
                    }""",
                    timeout=8000,
                )
            except Exception:
                pass

            try:
                await page.wait_for_timeout(1500)
            except Exception:
                pass

            final_url = page.url
            try:
                title = await page.title()
            except Exception:
                title = ""

            try:
                html = await page.content()
            except Exception:
                html = ""

            dom_snapshot = await self._extract_dom_snapshot_from_page(page)
            body_preview = self._normalize_preview_text(
                (dom_snapshot.get("body_text") if isinstance(dom_snapshot, dict) else "") or re.sub(r"<[^>]+>", " ", html)
            )
            failure_type = self._classify_html_fallback_failure(
                final_url=final_url,
                title=title,
                body_preview=body_preview,
                html=html,
            )

            if failure_type in ("html_fallback_404", "html_fallback_risk_page", "html_fallback_login_page", "html_fallback_empty_content"):
                await self._log_html_fallback_debug(
                    note_id=note_id,
                    note_url=note_url,
                    before_url=before_url,
                    final_url=final_url,
                    title=title,
                    body_preview=body_preview,
                    failure_type=failure_type,
                    goto_error=goto_error,
                )
                return None

            state_candidates = await self._extract_window_state_json_candidates(page)
            state_candidates.extend(self._extractor.extract_state_json_candidates_from_html(html))

            for source_name, raw_state_json in state_candidates:
                try:
                    note_detail = self._extractor.extract_note_detail_from_state_json(
                        note_id,
                        raw_state_json,
                        note_url=note_url,
                    )
                    if note_detail:
                        note_detail = self._extractor.fill_note_detail_from_dom_snapshot(
                            note_detail,
                            dom_snapshot,
                            note_url=note_url,
                        )
                        self.last_html_fallback_failure_type = ""
                        self.last_html_fallback_debug = {}
                        note_detail["_html_fallback_status"] = "success"
                        note_detail["_html_fallback_source"] = source_name
                        utils.logger.info(
                            f"[XiaoHongShuClient.get_note_by_id_from_html] HTML fallback success via structured state, "
                            f"note_id: {note_id}, source: {source_name}, final_url: {final_url}, title: {title}"
                        )
                        return note_detail
                except Exception as ex:
                    utils.logger.warning(
                        f"[XiaoHongShuClient.get_note_by_id_from_html] Failed to parse structured state, "
                        f"note_id: {note_id}, source: {source_name}, error: {ex}"
                    )

            try:
                note_detail = self._extractor.extract_note_detail_from_html(
                    note_id,
                    html,
                    note_url=note_url,
                )
                if note_detail:
                    note_detail = self._extractor.fill_note_detail_from_dom_snapshot(
                        note_detail,
                        dom_snapshot,
                        note_url=note_url,
                    )
                    self.last_html_fallback_failure_type = ""
                    self.last_html_fallback_debug = {}
                    note_detail["_html_fallback_status"] = "success"
                    note_detail["_html_fallback_source"] = "html_script_or_ld_json"
                    utils.logger.info(
                        f"[XiaoHongShuClient.get_note_by_id_from_html] HTML fallback success via HTML parsing, "
                        f"note_id: {note_id}, final_url: {final_url}, title: {title}"
                    )
                    return note_detail
            except Exception as ex:
                utils.logger.warning(
                    f"[XiaoHongShuClient.get_note_by_id_from_html] Failed to parse note detail from html, "
                    f"note_id: {note_id}, error: {ex}"
                )

            minimal_note_detail = self._extractor.build_note_detail_from_dom_snapshot(
                note_id,
                dom_snapshot,
                note_url=note_url,
            )
            if minimal_note_detail:
                self.last_html_fallback_failure_type = ""
                self.last_html_fallback_debug = {}
                minimal_note_detail["_html_fallback_status"] = "minimal_success"
                minimal_note_detail["_html_fallback_source"] = "dom_snapshot"
                utils.logger.info(
                    f"[XiaoHongShuClient.get_note_by_id_from_html] HTML fallback minimal success, "
                    f"note_id: {note_id}, final_url: {final_url}, title: {title}, body_preview: {body_preview}"
                )
                return minimal_note_detail

            failure_type = "html_fallback_no_state_json"
            if state_candidates:
                failure_type = "html_fallback_parse_error"

            await self._log_html_fallback_debug(
                note_id=note_id,
                note_url=note_url,
                before_url=before_url,
                final_url=final_url,
                title=title,
                body_preview=body_preview,
                failure_type=failure_type,
                goto_error=goto_error,
            )
            return None
        except Exception as ex:
            utils.logger.warning(
                f"[XiaoHongShuClient.get_note_by_id_from_html] Browser HTML fallback failed unexpectedly, "
                f"note_id: {note_id}, note_url: {note_url}, error: {ex}"
            )
            return None
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _pre_headers(self, url: str, params: Optional[Dict] = None, payload: Optional[Dict] = None) -> Dict:
        """请求头参数签名 (使用 xhshow 纯算法)

        Args:
            url: 请求 URI path
            params: GET 请求参数
            payload: POST 请求参数

        Returns:
            Dict: 签名后的请求头参数
        """
        if params is not None:
            data = params
            method = "GET"
        elif payload is not None:
            data = payload
            method = "POST"
        else:
            raise ValueError("params or payload is required")

        # 使用 xhshow 纯算法生成签名
        signs = sign_with_xhshow(
            uri=url,
            data=data,
            cookie_str=self.headers.get("Cookie", ""),
            method=method,
        )

        headers = {
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
        }
        self.headers.update(headers)
        return self.headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_not_exception_type((NoteNotFoundError, CaptchaBlockError)),
        reraise=True,
    )
    async def request(self, method, url, **kwargs) -> Union[str, Any]:
        """
        Wrapper for httpx common request method, processes request response
        Args:
            method: Request method
            url: Request URL
            **kwargs: Other request parameters, such as headers, body, etc.

        Returns:

        """
        # Check if proxy is expired before each request
        await self._refresh_proxy_if_expired()

        # return response.text
        return_response = kwargs.pop("return_response", False)
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)

        if response.status_code == 471 or response.status_code == 461:
            verify_type = response.headers.get("Verifytype", "unknown")
            verify_uuid = response.headers.get("Verifyuuid", "unknown")
            msg = (
                f"CAPTCHA/risk-control encountered, Verifytype: {verify_type}, "
                f"Verifyuuid: {verify_uuid}, Response: {response}"
            )
            utils.logger.warning(msg)
            raise CaptchaBlockError(msg)

        if return_response:
            return response.text
        data: Dict = response.json()
        if data["success"]:
            return data.get("data", data.get("success", {}))
        elif data["code"] == self.IP_ERROR_CODE:
            raise IPBlockError(self.IP_ERROR_STR)
        elif data["code"] in (self.NOTE_NOT_FOUND_CODE, self.NOTE_ABNORMAL_CODE):
            raise NoteNotFoundError(f"Note not found or abnormal, code: {data['code']}")
        else:
            err_msg = data.get("msg", None) or f"{response.text}"
            raise DataFetchError(err_msg)

    @staticmethod
    def _build_query_string(params: Dict) -> str:
        """Build URL query string with encoding matching browser behavior (commas not encoded)"""
        parts = []
        for key, value in params.items():
            value_str = str(value) if value is not None else ""
            parts.append(f"{key}={quote(value_str, safe=',')}")
        return "&".join(parts)

    async def get(self, uri: str, params: Optional[Dict] = None) -> Dict:
        """
        GET request, signs request headers
        Args:
            uri: Request route
            params: Request parameters

        Returns:

        """
        headers = await self._pre_headers(uri, params)
        # Build URL manually to ensure query string encoding matches the sign string
        # (httpx's default params encoding differs from browser/XHS frontend behavior)
        if params:
            full_url = f"{self._host}{uri}?{self._build_query_string(params)}"
        else:
            full_url = f"{self._host}{uri}"

        return await self.request(
            method="GET", url=full_url, headers=headers
        )

    async def post(self, uri: str, data: dict, **kwargs) -> Dict:
        """
        POST request, signs request headers
        Args:
            uri: Request route
            data: Request body parameters

        Returns:

        """
        headers = await self._pre_headers(uri, payload=data)
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return await self.request(
            method="POST",
            url=f"{self._host}{uri}",
            data=json_str,
            headers=headers,
            **kwargs,
        )

    async def download_note_media(
        self,
        url: str,
        *,
        referer: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Check if proxy is expired before request
        await self._refresh_proxy_if_expired()
        user_agent = self.headers.get("user-agent") or self.headers.get("User-Agent")
        cookie = self.headers.get("Cookie", "")
        return await download_media_bytes(
            url,
            headers=build_media_request_headers(
                user_agent=user_agent,
                referer=referer or self.headers.get("referer") or self._domain,
                cookie=cookie,
            ),
            proxy=self.proxy,
            timeout_sec=getattr(config, "XHS_MEDIA_DOWNLOAD_TIMEOUT_SEC", self.timeout),
            retry_count=getattr(config, "XHS_MEDIA_DOWNLOAD_RETRY_COUNT", 2),
            sleep_sec=getattr(config, "XHS_MEDIA_DOWNLOAD_SLEEP_SEC", 1),
        )

    async def get_note_media(self, url: str) -> Union[bytes, None]:
        result = await self.download_note_media(url)
        if result.get("success"):
            return result.get("content")
        return None

    async def query_self(self) -> Optional[Dict]:
        """
        Query self user info to check login state
        Returns:
            Dict: User info if logged in, None otherwise
        """
        uri = "/api/sns/web/v1/user/selfinfo"
        headers = await self._pre_headers(uri, params={})
        async with make_async_client(proxy=self.proxy) as client:
            response = await client.get(f"{self._host}{uri}", headers=headers)
            if response.status_code == 200:
                return response.json()
        return None

    async def pong(self) -> bool:
        """
        Check if login state is still valid by querying self user info
        Returns:
            bool: True if logged in, False otherwise
        """
        utils.logger.info("[XiaoHongShuClient.pong] Begin to check login state...")
        ping_flag = False
        try:
            self_info: Dict = await self.query_self()
            if self_info and self_info.get("data", {}).get("result", {}).get("success"):
                ping_flag = True
        except Exception as e:
            utils.logger.error(
                f"[XiaoHongShuClient.pong] Check login state failed: {e}, and try to login again..."
            )
            ping_flag = False
        utils.logger.info(f"[XiaoHongShuClient.pong] Login state result: {ping_flag}")
        return ping_flag

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[list[str]] = None):
        """
        Update cookies method provided by API client, usually called after successful login
        Args:
            browser_context: Browser context object

        Returns:

        """
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=urls or self.cookie_urls,
        )
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def get_note_by_keyword(
        self,
        keyword: str,
        search_id: str = get_search_id(),
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
    ) -> Dict:
        """
        Search notes by keyword
        Args:
            keyword: Keyword parameter
            page: Page number
            page_size: Page data length
            sort: Search result sorting specification
            note_type: Type of note to search

        Returns:

        """
        uri = "/api/sns/web/v1/search/notes"
        data = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id,
            "sort": sort.value,
            "note_type": note_type.value,
        }
        return await self.post(uri, data)

    async def get_note_by_id(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
    ) -> Dict:
        """
        Get note detail API
        Args:
            note_id: Note ID
            xsec_source: Channel source
            xsec_token: Token returned from search keyword result list

        Returns:

        """
        if xsec_source == "":
            xsec_source = "pc_search"

        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        uri = "/api/sns/web/v1/feed"
        res = await self.post(uri, data)
        if res and res.get("items"):
            res_dict: Dict = res["items"][0]["note_card"]
            return res_dict
        # When crawling frequently, some notes may have results while others don't
        utils.logger.error(
            f"[XiaoHongShuClient.get_note_by_id] get note id:{note_id} empty and res:{res}"
        )
        return dict()

    async def get_note_comments(
        self,
        note_id: str,
        xsec_token: str,
        cursor: str = "",
    ) -> Dict:
        """
        Get first-level comments API
        Args:
            note_id: Note ID
            xsec_token: Verification token
            cursor: Pagination cursor

        Returns:

        """
        uri = "/api/sns/web/v2/comment/page"
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        num: int = 10,
        cursor: str = "",
    ):
        """
        Get sub-comments under specified parent comment API
        Args:
            note_id: Post ID of sub-comments
            root_comment_id: Root comment ID
            xsec_token: Verification token
            num: Pagination quantity
            cursor: Pagination cursor

        Returns:

        """
        uri = "/api/sns/web/v2/comment/sub/page"
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": str(num),
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "top_comment_id": "",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_all_comments(
        self,
        note_id: str,
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ) -> List[Dict]:
        """
        Get all first-level comments under specified note, this method will continuously find all comment information under a post
        Args:
            note_id: Note ID
            xsec_token: Verification token
            crawl_interval: Crawl delay per note (seconds)
            callback: Callback after one note crawl ends
            max_count: Maximum number of comments to crawl per note
        Returns:

        """
        result = []
        comments_has_more = True
        comments_cursor = ""
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_note_comments(
                note_id=note_id, xsec_token=xsec_token, cursor=comments_cursor
            )
            comments_has_more = comments_res.get("has_more", False)
            comments_cursor = comments_res.get("cursor", "")
            if "comments" not in comments_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_note_all_comments] No 'comments' key found in response: {comments_res}"
                )
                break
            comments = comments_res["comments"]
            if len(result) + len(comments) > max_count:
                comments = comments[: max_count - len(result)]
            if callback:
                await callback(note_id, comments)
            await asyncio.sleep(crawl_interval)
            result.extend(comments)
            sub_comments = await self.get_comments_all_sub_comments(
                comments=comments,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=callback,
            )
            result.extend(sub_comments)
        return result

    async def get_comments_all_sub_comments(
        self,
        comments: List[Dict],
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Get all second-level comments under specified first-level comments, this method will continuously find all second-level comment information under first-level comments
        Args:
            comments: Comment list
            xsec_token: Verification token
            crawl_interval: Crawl delay per comment (seconds)
            callback: Callback after one comment crawl ends

        Returns:

        """
        if not config.ENABLE_GET_SUB_COMMENTS:
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_comments_all_sub_comments] Crawling sub_comment mode is not enabled"
            )
            return []

        result = []
        for comment in comments:
            try:
                note_id = comment.get("note_id")
                sub_comments = comment.get("sub_comments")
                if sub_comments and callback:
                    await callback(note_id, sub_comments)

                sub_comment_has_more = comment.get("sub_comment_has_more")
                if not sub_comment_has_more:
                    continue

                root_comment_id = comment.get("id")
                sub_comment_cursor = comment.get("sub_comment_cursor")

                while sub_comment_has_more:
                    try:
                        comments_res = await self.get_note_sub_comments(
                            note_id=note_id,
                            root_comment_id=root_comment_id,
                            xsec_token=xsec_token,
                            num=10,
                            cursor=sub_comment_cursor,
                        )

                        if comments_res is None:
                            utils.logger.info(
                                f"[XiaoHongShuClient.get_comments_all_sub_comments] No response found for note_id: {note_id}"
                            )
                            break
                        sub_comment_has_more = comments_res.get("has_more", False)
                        sub_comment_cursor = comments_res.get("cursor", "")
                        if "comments" not in comments_res:
                            utils.logger.info(
                                f"[XiaoHongShuClient.get_comments_all_sub_comments] No 'comments' key found in response: {comments_res}"
                            )
                            break
                        comments = comments_res["comments"]
                        if callback:
                            await callback(note_id, comments)
                        await asyncio.sleep(crawl_interval)
                        result.extend(comments)
                    except DataFetchError as e:
                        utils.logger.warning(
                            f"[XiaoHongShuClient.get_comments_all_sub_comments] Failed to get sub-comments for note_id: {note_id}, root_comment_id: {root_comment_id}, error: {e}. Skipping this comment's sub-comments."
                        )
                        break  # Break out of the sub-comment acquisition loop of the current comment and continue processing the next comment
                    except Exception as e:
                        utils.logger.error(
                            f"[XiaoHongShuClient.get_comments_all_sub_comments] Unexpected error when getting sub-comments for note_id: {note_id}, root_comment_id: {root_comment_id}, error: {e}"
                        )
                        break
            except Exception as e:
                utils.logger.error(
                    f"[XiaoHongShuClient.get_comments_all_sub_comments] Error processing comment: {comment.get('id', 'unknown')}, error: {e}. Continuing with next comment."
                )
                continue  # Continue to next comment
        return result

    async def get_creator_info(
        self, user_id: str, xsec_token: str = "", xsec_source: str = ""
    ) -> Dict:
        """
        Get user profile brief information by parsing user homepage HTML
        The PC user homepage has window.__INITIAL_STATE__ variable, just parse it

        Args:
            user_id: User ID
            xsec_token: Verification token (optional, pass if included in URL)
            xsec_source: Channel source (optional, pass if included in URL)

        Returns:
            Dict: Creator information
        """
        # Build URI, add xsec parameters to URL if available
        uri = f"/user/profile/{user_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"

        html_content = await self.request(
            "GET", self._domain + uri, return_response=True, headers=self.headers
        )
        return self._extractor.extract_creator_info_from_html(html_content)

    async def get_notes_by_creator(
        self,
        creator: str,
        cursor: str,
        page_size: int = 30,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> Dict:
        """
        Get creator's notes
        Args:
            creator: Creator ID
            cursor: Last note ID from previous page
            page_size: Page data length
            xsec_token: Verification token
            xsec_source: Channel source

        Returns:

        """
        uri = f"/api/sns/web/v1/user_posted"
        params = {
            "num": page_size,
            "cursor": cursor,
            "user_id": creator,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        return await self.get(uri, params)

    async def get_all_notes_by_creator(
        self,
        user_id: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> List[Dict]:
        """
        Get all posts published by specified user, this method will continuously find all post information under a user
        Args:
            user_id: User ID
            crawl_interval: Crawl delay (seconds)
            callback: Update callback function after one pagination crawl ends
            xsec_token: Verification token
            xsec_source: Channel source

        Returns:

        """
        result = []
        notes_has_more = True
        notes_cursor = ""
        while notes_has_more and len(result) < config.CRAWLER_MAX_NOTES_COUNT:
            notes_res = await self.get_notes_by_creator(
                user_id, notes_cursor, xsec_token=xsec_token, xsec_source=xsec_source
            )
            if not notes_res:
                utils.logger.error(
                    f"[XiaoHongShuClient.get_notes_by_creator] The current creator may have been banned by xhs, so they cannot access the data."
                )
                break

            notes_has_more = notes_res.get("has_more", False)
            notes_cursor = notes_res.get("cursor", "")
            if "notes" not in notes_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_all_notes_by_creator] No 'notes' key found in response: {notes_res}"
                )
                break

            notes = notes_res["notes"]
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] got user_id:{user_id} notes len : {len(notes)}"
            )

            remaining = config.CRAWLER_MAX_NOTES_COUNT - len(result)
            if remaining <= 0:
                break

            notes_to_add = notes[:remaining]
            if callback:
                await callback(notes_to_add)

            result.extend(notes_to_add)
            await asyncio.sleep(crawl_interval)

        utils.logger.info(
            f"[XiaoHongShuClient.get_all_notes_by_creator] Finished getting notes for user {user_id}, total: {len(result)}"
        )
        return result

    async def get_note_short_url(self, note_id: str) -> Dict:
        """
        Get note short URL
        Args:
            note_id: Note ID

        Returns:

        """
        uri = f"/api/sns/web/short_url"
        data = {"original_url": f"{self._domain}/discovery/item/{note_id}"}
        return await self.post(uri, data=data, return_response=True)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(1),
        retry=retry_if_not_exception_type(CaptchaBlockError),
        reraise=True,
    )
    async def get_note_by_id_from_html(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        enable_cookie: bool = False,
    ) -> Optional[Dict]:
        """
        Get note details by parsing note detail page HTML, this interface may fail, retry 3 times here
        copy from https://github.com/ReaJason/xhs/blob/eb1c5a0213f6fbb592f0a2897ee552847c69ea2d/xhs/core.py#L217-L259
        thanks for ReaJason
        Args:
            note_id:
            xsec_source:
            xsec_token:
            enable_cookie:

        Returns:

        """
        self.last_html_fallback_failure_type = ""
        self.last_html_fallback_debug = {}
        url = self._build_note_url(note_id, xsec_source, xsec_token)

        browser_note_detail = await self._get_note_by_id_from_html_via_browser(note_id, url)
        if browser_note_detail:
            return browser_note_detail

        copy_headers = self.headers.copy()
        if not enable_cookie:
            copy_headers.pop("Cookie", None)

        html = await self.request(
            method="GET", url=url, return_response=True, headers=copy_headers
        )
        note_detail = self._extractor.extract_note_detail_from_html(note_id, html, note_url=url)
        if note_detail:
            self.last_html_fallback_failure_type = ""
            self.last_html_fallback_debug = {}
            note_detail["_html_fallback_status"] = "success"
            note_detail["_html_fallback_source"] = "httpx_html"
            utils.logger.info(
                f"[XiaoHongShuClient.get_note_by_id_from_html] HTML fallback success via httpx html, note_id: {note_id}"
            )
            return note_detail

        body_preview = self._normalize_preview_text(re.sub(r"<[^>]+>", " ", html))
        failure_type = self._classify_html_fallback_failure(
            final_url=url,
            title="",
            body_preview=body_preview,
            html=html,
        )
        if not failure_type:
            failure_type = "html_fallback_no_state_json"
        await self._log_html_fallback_debug(
            note_id=note_id,
            note_url=url,
            before_url="httpx_request",
            final_url=url,
            title="",
            body_preview=body_preview,
            failure_type=failure_type,
        )
        return None
