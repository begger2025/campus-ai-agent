# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/kuaishou/core.py
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
import os
import random
import time
from asyncio import Task
from typing import Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from model.m_kuaishou import VideoUrlInfo, CreatorUrlInfo
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import kuaishou as kuaishou_store
from store import run_history as run_history_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.crawl_quota import should_fetch_next_page
from tools.publish_time_window import is_within_window, parse_window
from tools.run_history import STOP_EMPTY_PAGE, STOP_EXCEPTION, STOP_QUOTA_REACHED, RunState
from tools.topic_scope import compose_topic_keyword, is_broad_keyword, is_marketing_noise, matches_topic
from var import comment_tasks_var, crawler_type_var, source_keyword_var

from .client import KuaiShouClient
from .exception import DataFetchError
from .help import parse_video_info_from_url, parse_creator_info_from_url, resolve_next_pcursor
from .login import KuaishouLogin


class KuaishouCrawler(AbstractCrawler):
    context_page: Page
    ks_client: KuaiShouClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self):
        self.index_url = "https://www.kuaishou.com"
        self.cookie_urls = [self.index_url]
        self.user_agent = utils.get_user_agent()
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool, used for automatic proxy refresh

    async def start(self):
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(
                config.IP_PROXY_POOL_COUNT, enable_validate_ip=True
            )
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(
                ip_proxy_info
            )

        async with async_playwright() as playwright:
            # Select startup mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[KuaishouCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[KuaishouCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium, None, self.user_agent, headless=config.HEADLESS
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")


            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(f"{self.index_url}?isHome=1")

            # Create a client to interact with the kuaishou website.
            self.ks_client = await self.create_ks_client(httpx_proxy_format)
            if not await self.ks_client.pong():
                login_obj = KuaishouLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone=httpx_proxy_format,
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.ks_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for videos and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_videos()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their videos and comments
                await self.get_creators_and_videos()
            else:
                pass

            utils.logger.info("[KuaishouCrawler.start] Kuaishou Crawler finished ...")

    async def _filter_and_store_page(
        self,
        feeds: List[Dict],
        window_lo: Optional[int],
        window_hi: Optional[int],
        window_enabled: bool,
        run_state: RunState,
    ) -> Tuple[List[str], List[int]]:
        """单页搜索结果的过滤与入库：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 逐条入库计数。

        返回（本页实际入库成功的 video_id 列表, page_resolved_ts）；page_resolved_ts 在一切
        跳过/过滤决策之外收集（快手结果非时间序，无整页早停，仅用于日志观测与口径一致）。
        """
        page_resolved_ts: List[int] = []
        kept: List[Dict] = []
        window_filtered = topic_filtered = marketing_filtered = 0
        topic_terms = getattr(config, "TOPIC_RELEVANCE_TERMS", [])
        for feed in feeds:
            photo: Dict = feed.get("photo") or {}
            if not photo.get("id"):
                continue
            # photo.timestamp 为毫秒 epoch（缺失/0 视为 unknown，按 PUBLISH_TIME_KEEP_UNKNOWN 处理）
            try:
                ts_ms = int(photo.get("timestamp") or 0) or None
            except (TypeError, ValueError):
                # 异常形状的时间戳按 unknown 处理（与微博同构），一条坏数据不中断整场爬取
                ts_ms = None
            if ts_ms is not None:
                page_resolved_ts.append(ts_ms)
            if window_enabled and not is_within_window(
                ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN
            ):
                window_filtered += 1
                continue
            # 快手搜索结果自带全文文案，主题/营销过滤共用同组文本
            texts = [photo.get("caption", ""), photo.get("originCaption", "")]
            if getattr(config, "ENABLE_TOPIC_RELEVANCE_FILTER", False) and not matches_topic(texts, topic_terms):
                topic_filtered += 1
                continue
            # 营销内容负面词表（第三道防线）：命中负面词且无救回词的推广内容不入库
            if getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False) and is_marketing_noise(
                texts,
                getattr(config, "TOPIC_NEGATIVE_TERMS", []),
                getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", []),
            ):
                marketing_filtered += 1
                continue
            kept.append(feed)

        if window_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 时间窗口过滤：跳过 {window_filtered} 条窗口外内容")
        if topic_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 主题过滤：跳过 {topic_filtered} 条与主题无关的内容")
        if marketing_filtered:
            utils.logger.info(f"[KuaishouCrawler.search] 营销内容过滤：跳过 {marketing_filtered} 条")

        # 爬取阶段跳过已入库视频（省请求额度）：必须在过滤后、入库与评论抓取之前
        if kept and bool(getattr(config, "KS_SKIP_EXISTING_NOTES", True)):
            existing = await kuaishou_store.batch_get_existing_note_ids(
                [str((feed.get("photo") or {}).get("id") or "").strip() for feed in kept]
            )
            if existing:
                before = len(kept)
                kept = [
                    feed for feed in kept
                    if str((feed.get("photo") or {}).get("id") or "").strip() not in existing
                ]
                if before - len(kept):
                    utils.logger.info(f"[KuaishouCrawler.search] 跳过已入库 {before - len(kept)} 条")

        stored_ids: List[str] = []
        for feed in kept:
            video_id = str((feed.get("photo") or {}).get("id"))
            try:
                await kuaishou_store.update_kuaishou_video(video_item=feed)
                stored_ids.append(video_id)
                run_state.add_stored(1)  # 真正入库条数（过滤/跳过后）
            except Exception as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.search] store failed video_id={video_id}: {ex}"
                )
        return stored_ids, page_resolved_ts

    async def search(self):
        utils.logger.info("[KuaishouCrawler.search] Begin search kuaishou keywords")
        ks_limit_count = 20  # kuaishou limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < ks_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = ks_limit_count
        start_page = config.START_PAGE
        window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
        window_enabled = window_lo is not None or window_hi is not None

        for keyword in config.KEYWORDS.split(","):
            # 宽泛词拦截（用原始词判定，需在主题限定组合之前）：裸主题词对过滤零区分力
            if is_broad_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            ) and not getattr(config, "ALLOW_BROAD_KEYWORDS", False):
                utils.logger.warning(
                    f"[KuaishouCrawler.search] 宽泛词已跳过：{keyword.strip()}（设 ALLOW_BROAD_KEYWORDS=True 可放行）"
                )
                continue
            composed_keyword = compose_topic_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            )
            if composed_keyword != keyword.strip():
                utils.logger.info(f"[KuaishouCrawler.search] 主题限定：{keyword} → {composed_keyword}")
            keyword = composed_keyword
            source_keyword_var.set(keyword)
            utils.logger.info(f"[KuaishouCrawler.search] Current search keyword: {keyword}")

            # 防饥饿：快手无排序参数（恒定综合排序），无条件参与起始页随机偏移；
            # 游标兼容数字页码，偏移直接从偏移后的页码起步（跳过的页不发请求、不计数）
            keyword_start_page = start_page
            if random.random() < float(getattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0)):
                jitter = random.randint(1, int(getattr(config, "SEARCH_START_PAGE_JITTER_MAX", 1)))
                keyword_start_page += jitter
                utils.logger.info(f"[KuaishouCrawler.search] 防饥饿起始页偏移 +{jitter} → 从第 {keyword_start_page} 页开始")

            # 通用爬取历史：本关键词一轮搜索写一行，try/except/finally 保证异常路径也落一行
            run_state = RunState(
                platform="ks",
                source_keyword=keyword,
                started_at=int(utils.get_current_timestamp()),
            )
            search_session_id = ""
            page = keyword_start_page
            pcursor: Optional[str] = str(keyword_start_page)
            try:
                # 配额按"新增入库条数"计（不再按页数），被过滤/跳过已入库的内容不烧配额；
                # 页数保护上限防止贫瘠词无限翻页
                while should_fetch_next_page(
                    run_state.items_stored,
                    run_state.pages_fetched,
                    config.CRAWLER_MAX_NOTES_COUNT,
                    int(getattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10)),
                ):
                    utils.logger.info(
                        f"[KuaishouCrawler.search] search kuaishou keyword: {keyword}, page: {page}, pcursor: {pcursor}"
                    )
                    videos_res = await self.ks_client.search_info_by_keyword(
                        keyword=keyword,
                        pcursor=pcursor,
                        search_session_id=search_session_id,
                    )
                    run_state.add_page()
                    vision_search_photo: Dict = (videos_res or {}).get("visionSearchPhoto") or {}
                    feeds = vision_search_photo.get("feeds") or []
                    run_state.add_seen(len(feeds))
                    if not videos_res or vision_search_photo.get("result") != 1 or not feeds:
                        # 原实现此处 continue 且不翻页，是死循环隐患；空页/异常响应一律停止
                        utils.logger.info("[KuaishouCrawler.search] Search result empty or abnormal, stop paging")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break
                    search_session_id = vision_search_photo.get("searchSessionId", "") or search_session_id

                    stored_ids, _page_resolved_ts = await self._filter_and_store_page(
                        feeds, window_lo, window_hi, window_enabled, run_state
                    )

                    # Sleep after page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(
                        f"[KuaishouCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page}"
                    )

                    # 评论只对本页新入库视频抓取（跟随全局 ENABLE_GET_COMMENTS）
                    await self.batch_get_video_comments(stored_ids)

                    # 游标推进：优先服务端真实 pcursor（"no_more" → 停止），缺失回退页码
                    page += 1
                    next_cursor = resolve_next_pcursor(vision_search_photo.get("pcursor"), page)
                    if next_cursor is None:
                        utils.logger.info("[KuaishouCrawler.search] 服务端返回 no_more，无更多结果")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break
                    pcursor = next_cursor

                # 循环自然退出：入库配额达成归结 quota_reached（页保护上限触发则落 completed）
                if run_state.items_stored >= config.CRAWLER_MAX_NOTES_COUNT:
                    run_state.mark_stop(STOP_QUOTA_REACHED)
            except DataFetchError as ex:
                # 记 exception 落一行历史后继续下一关键词，不中断整场爬取
                run_state.mark_stop(STOP_EXCEPTION)
                utils.logger.error(f"[KuaishouCrawler.search] Search error, keyword: {keyword}, error: {ex}")
            except asyncio.CancelledError:
                # ks 独有：get_comments 风控恢复路径会取消全部评论任务；CancelledError 是
                # BaseException，若不拦截，finally 会把中止的一轮记成 completed（假遥测）
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            except Exception:
                # 其他异常路径也落一行历史（stop_reason=exception），异常继续上抛
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())

    async def get_specified_videos(self):
        """Get the information and comments of the specified post"""
        utils.logger.info("[KuaishouCrawler.get_specified_videos] Parsing video URLs...")
        video_ids = []
        for video_url in config.KS_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)
                video_ids.append(video_info.video_id)
                utils.logger.info(f"Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_video_info_task(video_id=video_id, semaphore=semaphore)
            for video_id in video_ids
        ]
        video_details = await asyncio.gather(*task_list)
        for video_detail in video_details:
            if video_detail is not None:
                await kuaishou_store.update_kuaishou_video(video_detail)
        await self.batch_get_video_comments(video_ids)

    async def get_video_info_task(
        self, video_id: str, semaphore: asyncio.Semaphore
    ) -> Optional[Dict]:
        """Get video detail task"""
        async with semaphore:
            try:
                result = await self.ks_client.get_video_info(video_id)

                # Sleep after fetching video details
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.get_video_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {video_id}")

                utils.logger.info(
                    f"[KuaishouCrawler.get_video_info_task] Get video_id:{video_id} info result: {result} ..."
                )
                return result.get("visionVideoDetail")
            except DataFetchError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_video_info_task] Get video detail error: {ex}"
                )
                return None
            except KeyError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_video_info_task] have not fund video detail video_id:{video_id}, err: {ex}"
                )
                return None

    async def batch_get_video_comments(self, video_id_list: List[str]):
        """
        batch get video comments
        :param video_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(
                f"[KuaishouCrawler.batch_get_video_comments] Crawling comment mode is not enabled"
            )
            return

        utils.logger.info(
            f"[KuaishouCrawler.batch_get_video_comments] video ids:{video_id_list}"
        )
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for video_id in video_id_list:
            task = asyncio.create_task(
                self.get_comments(video_id, semaphore), name=video_id
            )
            task_list.append(task)

        comment_tasks_var.set(task_list)
        await asyncio.gather(*task_list)

    async def get_comments(self, video_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for video id
        :param video_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                utils.logger.info(
                    f"[KuaishouCrawler.get_comments] begin get video_id: {video_id} comments ..."
                )

                # Sleep before fetching comments
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[KuaishouCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for video {video_id}")

                await self.ks_client.get_video_all_comments(
                    photo_id=video_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=kuaishou_store.batch_update_ks_video_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
            except DataFetchError as ex:
                utils.logger.error(
                    f"[KuaishouCrawler.get_comments] get video_id: {video_id} comment error: {ex}"
                )
            except Exception as e:
                utils.logger.error(
                    f"[KuaishouCrawler.get_comments] may be been blocked, err:{e}"
                )
                # use time.sleeep block main coroutine instead of asyncio.sleep and cacel running comment task
                # maybe kuaishou block our request, we will take a nap and update the cookie again
                current_running_tasks = comment_tasks_var.get()
                for task in current_running_tasks:
                    task.cancel()
                time.sleep(20)
                await self.context_page.goto(f"{self.index_url}?isHome=1")
                await self.ks_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

    async def create_ks_client(self, httpx_proxy: Optional[str]) -> KuaiShouClient:
        """Create ks client"""
        utils.logger.info(
            "[KuaishouCrawler.create_ks_client] Begin create kuaishou API client ..."
        )
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )
        ks_client_obj = KuaiShouClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": self.index_url,
                "Referer": self.index_url,
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return ks_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info(
            "[KuaishouCrawler.launch_browser] Begin create browser context ..."
        )
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(
                os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM
            )  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent,
                channel="chrome",  # Use system's stable Chrome version
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")  # type: ignore
            browser_context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}, user_agent=user_agent
            )
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch browser using CDP mode
        """
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
            utils.logger.info(f"[KuaishouCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(
                f"[KuaishouCrawler] CDP mode launch failed, fallback to standard mode: {e}"
            )
            # Fallback to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(
                chromium, playwright_proxy, user_agent, headless
            )

    async def get_creators_and_videos(self) -> None:
        """Get creator's videos and retrieve their comment information."""
        utils.logger.info(
            "[KuaiShouCrawler.get_creators_and_videos] Begin get kuaishou creators"
        )
        for creator_url in config.KS_CREATOR_ID_LIST:
            try:
                # Parse creator URL to get user_id
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[KuaiShouCrawler.get_creators_and_videos] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                # get creator detail info from web html content
                createor_info: Dict = await self.ks_client.get_creator_info(user_id=user_id)
                if createor_info:
                    await kuaishou_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[KuaiShouCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            # Get all video information of the creator
            all_video_list = await self.ks_client.get_all_videos_by_creator(
                user_id=user_id,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=self.fetch_creator_video_detail,
            )

            video_ids = [
                video_item.get("photo", {}).get("id") for video_item in all_video_list
            ]
            await self.batch_get_video_comments(video_ids)

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_video_info_task(post_item.get("photo", {}).get("id"), semaphore)
            for post_item in video_list
        ]

        video_details = await asyncio.gather(*task_list)
        for video_detail in video_details:
            if video_detail is not None:
                await kuaishou_store.update_kuaishou_video(video_detail)

    async def close(self):
        """Close browser context"""
        # If using CDP mode, need special handling
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[KuaishouCrawler.close] Browser context closed ...")
