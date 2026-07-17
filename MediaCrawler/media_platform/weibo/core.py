# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/core.py
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

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/23 15:41
# @Desc    : Weibo crawler main workflow code

import asyncio
import os
import random  # Used for search start-page jitter (anti-starvation exploration)
from asyncio import Task
from typing import Dict, List, Optional, Set, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import run_history as run_history_store
from store import weibo as weibo_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.crawl_quota import should_fetch_next_page
from tools.publish_time_window import is_within_window, parse_window
from tools.run_history import STOP_EMPTY_PAGE, STOP_EXCEPTION, STOP_QUOTA_REACHED, STOP_WINDOW_EXHAUSTED, RunState
from tools.topic_scope import compose_topic_keyword, is_broad_keyword, is_marketing_noise, matches_topic
from var import crawler_type_var, source_keyword_var

from .client import WeiboClient
from .exception import DataFetchError
from .field import SearchType
from .help import filter_search_result_card
from .login import WeiboLogin


class WeiboCrawler(AbstractCrawler):
    context_page: Page
    wb_client: WeiboClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self):
        self.index_url = "https://www.weibo.com"
        self.mobile_index_url = "https://m.weibo.cn"
        self.cookie_urls = [self.mobile_index_url]
        self.user_agent = utils.get_user_agent()
        self.mobile_user_agent = utils.get_mobile_user_agent()
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh

    async def start(self):
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Select launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[WeiboCrawler] Launching browser with CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.mobile_user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[WeiboCrawler] Launching browser with standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(chromium, None, self.mobile_user_agent, headless=config.HEADLESS)

                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")


            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url)
            await asyncio.sleep(2)


            # Create a client to interact with the xiaohongshu website.
            self.wb_client = await self.create_weibo_client(httpx_proxy_format)
            if not await self.wb_client.pong():
                login_obj = WeiboLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()

                # After successful login, redirect to mobile website and update mobile cookies
                utils.logger.info("[WeiboCrawler.start] redirect weibo mobile homepage and update cookies on mobile platform")
                await self.context_page.goto(self.mobile_index_url)
                await asyncio.sleep(3)
                # Only get mobile cookies to avoid confusion between PC and mobile cookies
                await self.wb_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for video and retrieve their comment information.
                if config.CRAWL_FROM_QUEUE:
                    from tools.crawl_queue_runner import run_keyword_queue
                    await run_keyword_queue(self)
                else:
                    await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass
            utils.logger.info("[WeiboCrawler.start] Weibo Crawler finished ...")

    async def search(self):
        """
        search weibo note with keywords
        :return:
        """
        utils.logger.info("[WeiboCrawler.search] Begin search weibo keywords")
        weibo_limit_count = 10  # weibo limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < weibo_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = weibo_limit_count
        start_page = config.START_PAGE
        window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
        window_enabled = window_lo is not None or window_hi is not None

        # Set the search type based on the configuration for weibo
        if config.WEIBO_SEARCH_TYPE == "default":
            search_type = SearchType.DEFAULT
        elif config.WEIBO_SEARCH_TYPE == "real_time":
            search_type = SearchType.REAL_TIME
        elif config.WEIBO_SEARCH_TYPE == "popular":
            search_type = SearchType.POPULAR
        elif config.WEIBO_SEARCH_TYPE == "video":
            search_type = SearchType.VIDEO
        else:
            utils.logger.error(f"[WeiboCrawler.search] Invalid WEIBO_SEARCH_TYPE: {config.WEIBO_SEARCH_TYPE}")
            return

        for keyword in config.KEYWORDS.split(","):
            keyword = keyword.strip()
            if not keyword:
                continue  # 结尾逗号/空段的空串：跳过，不对空关键词跑整轮搜索（对齐小红书）
            # 宽泛词拦截（用原始词判定，需在主题限定组合之前）：裸主题词对过滤零区分力
            if is_broad_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            ) and not getattr(config, "ALLOW_BROAD_KEYWORDS", False):
                utils.logger.warning(
                    f"[WeiboCrawler.search] 宽泛词已跳过：{keyword.strip()}（设 ALLOW_BROAD_KEYWORDS=True 可放行）"
                )
                continue
            composed_keyword = compose_topic_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            )
            if composed_keyword != keyword.strip():
                utils.logger.info(f"[WeiboCrawler.search] 主题限定：{keyword} → {composed_keyword}")
            keyword = composed_keyword
            source_keyword_var.set(keyword)
            utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}")
            page = 1
            # 防饥饿：本关键词开搜前，以一定概率把起始页随机后移，避免每次都只翻到前几页
            keyword_start_page = start_page
            if random.random() < float(getattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0)):
                jitter = random.randint(1, int(getattr(config, "SEARCH_START_PAGE_JITTER_MAX", 1)))
                keyword_start_page += jitter
                utils.logger.info(f"[WeiboCrawler.search] 防饥饿起始页偏移 +{jitter} → 从第 {keyword_start_page} 页开始")
            # 起始页 jitter 仅平移翻页窗口：跳过的页不发请求、不计入已抓页数（jitter=0 时与原行为等价）
            # 通用爬取历史：本关键词一轮搜索写一行，try/finally 保证异常路径也落一行
            run_state = RunState(
                platform="wb",
                source_keyword=keyword,
                started_at=int(utils.get_current_timestamp()),
            )
            try:
                # 配额按"新增入库条数"计（不再按页数），被过滤/跳过已入库的帖子不烧配额；
                # 页数保护上限防止贫瘠词无限翻页（根治关键词一轮后"干涸"）
                while should_fetch_next_page(
                    run_state.items_stored,
                    run_state.pages_fetched,
                    config.CRAWLER_MAX_NOTES_COUNT,
                    int(getattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10)),
                ):
                    if page < keyword_start_page:
                        utils.logger.info(f"[WeiboCrawler.search] Skip page: {page}")
                        page += 1
                        continue
                    utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
                    search_res = await self.wb_client.get_note_by_keyword(keyword=keyword, page=page, search_type=search_type)
                    run_state.add_page()
                    note_id_list: List[str] = []
                    note_list = filter_search_result_card(search_res.get("cards"))
                    run_state.add_seen(len(note_list))  # 帖子卡数（filter_search_result_card 之后）
                    if not note_list:
                        utils.logger.info("[WeiboCrawler.search] Search note list is empty")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break
                    # If full text fetching is enabled, batch get full text of posts
                    note_list = await self.batch_get_notes_full_text(note_list)
                    page_resolved_ts: List[int] = []
                    topic_filtered_count = 0
                    marketing_filtered_count = 0
                    surviving_items: List[Tuple[Dict, Dict]] = []  # (note_item, mblog) that passed window/topic filters
                    for note_item in note_list:
                        if note_item:
                            mblog: Dict = note_item.get("mblog")
                            if mblog:
                                publish_ts_ms = None
                                try:
                                    created_at = (mblog or {}).get("created_at")
                                    if created_at:
                                        publish_ts_ms = int(utils.rfc2822_to_china_datetime(created_at).timestamp() * 1000)
                                except (TypeError, ValueError):
                                    publish_ts_ms = None
                                if window_enabled:
                                    if publish_ts_ms is not None:
                                        page_resolved_ts.append(publish_ts_ms)
                                    if not is_within_window(publish_ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN):
                                        continue
                                if getattr(config, "ENABLE_TOPIC_RELEVANCE_FILTER", False) and not matches_topic(
                                    [(mblog or {}).get("text") or (mblog or {}).get("content") or ""],
                                    getattr(config, "TOPIC_RELEVANCE_TERMS", []),
                                ):
                                    topic_filtered_count += 1
                                    continue
                                # 营销内容负面词表（第三道防线）：命中负面词且无救回词的推广内容不入库
                                if getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False) and is_marketing_noise(
                                    [(mblog or {}).get("text") or (mblog or {}).get("content") or ""],
                                    getattr(config, "TOPIC_NEGATIVE_TERMS", []),
                                    getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", []),
                                ):
                                    marketing_filtered_count += 1
                                    continue
                                surviving_items.append((note_item, mblog))

                    if topic_filtered_count:
                        utils.logger.info(f"[WeiboCrawler.search] 主题过滤：跳过 {topic_filtered_count} 条与主题无关的微博")
                    if marketing_filtered_count:
                        utils.logger.info(f"[WeiboCrawler.search] 营销内容过滤：跳过 {marketing_filtered_count} 条")

                    # 爬取阶段跳过已入库帖子（省请求额度，仿小红书 XHS_SKIP_EXISTING_NOTE_DETAILS）：
                    # 必须在窗口/主题过滤之后、入库与评论抓取之前。page_resolved_ts 已在上面的过滤循环里
                    # 收集完毕，不受本次跳过影响——早停看的是整页发布时间是否过旧，与帖子是否已入库无关，
                    # 已存在的帖子仍然贡献了它的发布时间到 page_resolved_ts。
                    existing_note_ids: Set[str] = set()
                    if surviving_items and bool(getattr(config, "WEIBO_SKIP_EXISTING_NOTES", True)):
                        existing_note_ids = await weibo_store.batch_get_existing_note_ids(
                            [str(mblog.get("id") or "").strip() for _, mblog in surviving_items]
                        )

                    skipped_existing_count = 0
                    for note_item, mblog in surviving_items:
                        note_id = str(mblog.get("id") or "").strip()
                        if note_id and note_id in existing_note_ids:
                            skipped_existing_count += 1
                            continue
                        # 单条 store 失败只跳过这一条、不中断整个关键词（对齐知乎/快手/小红书）：
                        # 只对成功入库的计数，失败的不虚计。原来无隔离，一条抛异常整词放弃剩余帖。
                        try:
                            await weibo_store.update_weibo_note(note_item)
                        except Exception as store_err:
                            utils.logger.error(
                                f"[WeiboCrawler.search] store failed note_id={mblog.get('id')}: {store_err}"
                            )
                            continue
                        note_id_list.append(mblog.get("id"))
                        run_state.add_stored(1)  # 真正入库条数（过滤/跳过后）
                        await self.get_note_images(mblog)

                    if skipped_existing_count:
                        utils.logger.info(f"[WeiboCrawler.search] 跳过已入库 {skipped_existing_count} 条")

                    if (
                        window_enabled
                        and window_lo is not None
                        and config.WEIBO_SEARCH_TYPE == "real_time"
                        and page_resolved_ts
                        and all(ts < window_lo for ts in page_resolved_ts)
                    ):
                        utils.logger.info("[WeiboCrawler.search] 整页发布时间早于窗口起点，提前停止翻页")
                        run_state.mark_stop(STOP_WINDOW_EXHAUSTED)
                        await self.batch_get_notes_comments(note_id_list)
                        break

                    page += 1

                    # Sleep after page navigation
                    await utils.random_crawl_sleep()
                    utils.logger.info(f"[WeiboCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                    await self.batch_get_notes_comments(note_id_list)

                # 循环自然退出：入库配额达成归结 quota_reached（页保护上限触发则落 completed）
                if run_state.items_stored >= config.CRAWLER_MAX_NOTES_COUNT:
                    run_state.mark_stop(STOP_QUOTA_REACHED)
            except asyncio.CancelledError:
                # CancelledError 是 BaseException，下面的 except Exception 抓不住；不显式拦，
                # finally 会把被取消（Ctrl-C / 评论任务取消）的一轮记成 completed（假遥测，
                # 污染贫瘠词判定）。对齐快手。
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            except Exception:
                # 异常路径也落一行历史（stop_reason=exception），异常按原行为继续上抛
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())

    async def get_specified_notes(self):
        """
        get specified notes info
        :return:
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_note_info_task(note_id=note_id, semaphore=semaphore) for note_id in config.WEIBO_SPECIFIED_ID_LIST]
        video_details = await asyncio.gather(*task_list)
        for note_item in video_details:
            if note_item:
                await weibo_store.update_weibo_note(note_item)
        await self.batch_get_notes_comments(config.WEIBO_SPECIFIED_ID_LIST)

    async def get_note_info_task(self, note_id: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """
        Get note detail task
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                result = await self.wb_client.get_note_info_by_id(note_id)

                # Sleep after fetching note details
                await utils.random_crawl_sleep()
                utils.logger.info(f"[WeiboCrawler.get_note_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def batch_get_notes_comments(self, note_id_list: List[str]):
        """
        batch get notes comments
        :param note_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[WeiboCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[WeiboCrawler.batch_get_notes_comments] note ids:{note_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_id in note_id_list:
            task = asyncio.create_task(self.get_note_comments(note_id, semaphore), name=note_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_note_comments(self, note_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for note id
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                utils.logger.info(f"[WeiboCrawler.get_note_comments] begin get note_id: {note_id} comments ...")

                # Sleep before fetching comments
                await utils.random_crawl_sleep()
                utils.logger.info(f"[WeiboCrawler.get_note_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_id}")

                await self.wb_client.get_note_all_comments(
                    note_id=note_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,  # Use fixed interval instead of random
                    callback=weibo_store.batch_update_weibo_note_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] may be been blocked, err:{e}")

    async def get_note_images(self, mblog: Dict):
        """
        get note images
        :param mblog:
        :return:
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[WeiboCrawler.get_note_images] Crawling image mode is not enabled")
            return

        pics: List = mblog.get("pics")
        if not pics:
            return
        for pic in pics:
            if isinstance(pic, str):
                url = pic
                pid = url.split("/")[-1].split(".")[0]
            elif isinstance(pic, dict):
                url = pic.get("url")
                pid = pic.get("pid", "")
            else:
                continue
            if not url:
                continue
            content = await self.wb_client.get_note_image(url)
            await utils.random_crawl_sleep()
            utils.logger.info(f"[WeiboCrawler.get_note_images] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching image")
            if content != None:
                extension_file_name = url.split(".")[-1]
                await weibo_store.update_weibo_note_image(pid, content, extension_file_name)

    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        utils.logger.info("[WeiboCrawler.get_creators_and_notes] Begin get weibo creators")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            createor_info_res: Dict = await self.wb_client.get_creator_info_by_id(creator_id=user_id)
            if createor_info_res:
                createor_info: Dict = createor_info_res.get("userInfo", {})
                utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] creator info: {createor_info}")
                if not createor_info:
                    raise DataFetchError("Get creator info error")
                await weibo_store.save_creator(user_id, user_info=createor_info)

                # Create a wrapper callback to get full text before saving data
                async def save_notes_with_full_text(note_list: List[Dict]):
                    # If full text fetching is enabled, batch get full text first
                    updated_note_list = await self.batch_get_notes_full_text(note_list)
                    await weibo_store.batch_update_weibo_notes(updated_note_list)

                # Get all note information of the creator
                all_notes_list = await self.wb_client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=f"107603{user_id}",
                    crawl_interval=0,
                    callback=save_notes_with_full_text,
                )

                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes_list if note_item.get("mblog", {}).get("id")]
                await self.batch_get_notes_comments(note_ids)

            else:
                utils.logger.error(f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_id:{user_id}")

    async def create_weibo_client(self, httpx_proxy: Optional[str]) -> WeiboClient:
        """Create xhs client"""
        utils.logger.info("[WeiboCrawler.create_weibo_client] Begin create weibo API client ...")
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )
        weibo_client_obj = WeiboClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": utils.get_mobile_user_agent(),
                "Cookie": cookie_str,
                "Origin": "https://m.weibo.cn",
                "Referer": "https://m.weibo.cn",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return weibo_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[WeiboCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
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
                channel="chrome",  # Use system's Chrome stable version
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch browser with CDP mode
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
            utils.logger.info(f"[WeiboCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[WeiboCrawler] CDP mode startup failed, falling back to standard mode: {e}")
            # Fallback to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def get_note_full_text(self, note_item: Dict) -> Dict:
        """
        Get full text content of a post
        If the post content is truncated (isLongText=True), request the detail API to get complete content
        :param note_item: Post data, contains mblog field
        :return: Updated post data
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_item

        mblog = note_item.get("mblog", {})
        if not mblog:
            return note_item

        # Check if it's a long text
        is_long_text = mblog.get("isLongText", False)
        if not is_long_text:
            return note_item

        note_id = mblog.get("id")
        if not note_id:
            return note_item

        try:
            utils.logger.info(f"[WeiboCrawler.get_note_full_text] Fetching full text for note: {note_id}")
            full_note = await self.wb_client.get_note_info_by_id(note_id)
            if full_note and full_note.get("mblog"):
                # Replace original content with complete content
                note_item["mblog"] = full_note["mblog"]
                utils.logger.info(f"[WeiboCrawler.get_note_full_text] Successfully fetched full text for note: {note_id}")

            # Sleep after request to avoid rate limiting
            await utils.random_crawl_sleep()
        except DataFetchError as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Failed to fetch full text for note {note_id}: {ex}")
        except Exception as ex:
            utils.logger.error(f"[WeiboCrawler.get_note_full_text] Unexpected error for note {note_id}: {ex}")

        return note_item

    async def batch_get_notes_full_text(self, note_list: List[Dict]) -> List[Dict]:
        """
        Batch get full text content of posts
        :param note_list: List of posts
        :return: Updated list of posts
        """
        if not config.ENABLE_WEIBO_FULL_TEXT:
            return note_list

        result = []
        for note_item in note_list:
            updated_note = await self.get_note_full_text(note_item)
            result.append(updated_note)
        return result

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[WeiboCrawler.close] Browser context closed ...")
