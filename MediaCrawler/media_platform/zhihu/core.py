# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/zhihu/core.py
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
import asyncio
import os
import random  # Used for search start-page jitter (anti-starvation exploration)
from asyncio import Task
from typing import Dict, List, Optional, Tuple, cast

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from constant import zhihu as constant
from base.base_crawler import AbstractCrawler
from model.m_zhihu import ZhihuContent, ZhihuCreator
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import run_history as run_history_store
from store import zhihu as zhihu_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.crawl_quota import should_fetch_next_page
from tools.publish_time_window import is_within_window, parse_window, pick_zhihu_search_time_value
from tools.run_history import STOP_EMPTY_PAGE, STOP_EXCEPTION, STOP_QUOTA_REACHED, STOP_WINDOW_EXHAUSTED, RunState
from tools.topic_scope import compose_topic_keyword, is_broad_keyword, is_marketing_noise, matches_topic
from var import crawler_type_var, source_keyword_var

from .client import ZhiHuClient
from .exception import DataFetchError
from .field import SearchSort, SearchTime
from .help import ZhihuExtractor, judge_zhihu_url
from .login import ZhiHuLogin


class ZhihuCrawler(AbstractCrawler):
    context_page: Page
    zhihu_client: ZhiHuClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.zhihu.com"
        self.cookie_urls = [self.index_url]
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        self._extractor = ZhihuExtractor()
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh

    async def start(self) -> None:
        """
        Start the crawler
        Returns:

        """
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
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[ZhihuCrawler] Launching browser in CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[ZhihuCrawler] Launching browser in standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium, None, self.user_agent, headless=config.HEADLESS
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded")

            # Create a client to interact with the zhihu website.
            self.zhihu_client = await self.create_zhihu_client(httpx_proxy_format)
            if not await self.zhihu_client.pong():
                login_obj = ZhiHuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.zhihu_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            # Zhihu's search API requires opening the search page first to access cookies, homepage alone won't work
            utils.logger.info(
                "[ZhihuCrawler.start] Zhihu navigating to search page to get search page cookies, this process takes about 5 seconds"
            )
            await self.context_page.goto(
                f"{self.index_url}/search?q=python&search_source=Guess&utm_content=search_hot&type=content"
            )
            await asyncio.sleep(5)
            await self.zhihu_client.update_cookies(
                browser_context=self.browser_context,
                urls=self.cookie_urls,
            )

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
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

            utils.logger.info("[ZhihuCrawler.start] Zhihu Crawler finished ...")

    async def _filter_and_store_page(
        self,
        content_list: List[ZhihuContent],
        window_lo: Optional[int],
        window_hi: Optional[int],
        window_enabled: bool,
        run_state: RunState,
    ) -> Tuple[List[ZhihuContent], List[int]]:
        """单页搜索结果的过滤与入库：窗口 → 主题相关 → 营销负面 → 跳过已入库 → 逐条入库计数。

        返回（本页实际入库成功的内容列表, page_resolved_ts）；page_resolved_ts 在一切
        跳过/过滤决策之外收集——整页早停只看发布时间是否过旧，与内容是否被过滤/已入库无关。
        """
        page_resolved_ts: List[int] = []
        kept: List[ZhihuContent] = []
        window_filtered = topic_filtered = marketing_filtered = 0
        topic_terms = getattr(config, "TOPIC_RELEVANCE_TERMS", [])
        for content in content_list:
            # created_time 为秒级 epoch（0 视为 unknown，按 PUBLISH_TIME_KEEP_UNKNOWN 处理）
            ts_ms = int(content.created_time) * 1000 if content.created_time else None
            if ts_ms is not None:
                page_resolved_ts.append(ts_ms)
            if window_enabled and not is_within_window(
                ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN
            ):
                window_filtered += 1
                continue
            # 知乎判定文本最富（搜索结果直接含全文），主题/营销过滤共用同组文本
            texts = [content.title, content.desc, content.content_text]
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
            kept.append(content)

        if window_filtered:
            utils.logger.info(f"[ZhihuCrawler.search] 时间窗口过滤：跳过 {window_filtered} 条窗口外内容")
        if topic_filtered:
            utils.logger.info(f"[ZhihuCrawler.search] 主题过滤：跳过 {topic_filtered} 条与主题无关的内容")
        if marketing_filtered:
            utils.logger.info(f"[ZhihuCrawler.search] 营销内容过滤：跳过 {marketing_filtered} 条")

        # 爬取阶段跳过已入库内容（省请求额度）：必须在过滤后、入库与评论抓取之前；
        # page_resolved_ts 已在上面收集完毕，不受本次跳过影响
        if kept and bool(getattr(config, "ZHIHU_SKIP_EXISTING_NOTES", True)):
            existing = await zhihu_store.batch_get_existing_note_ids(
                [str(content.content_id or "").strip() for content in kept]
            )
            if existing:
                before = len(kept)
                kept = [
                    content for content in kept
                    if str(content.content_id or "").strip() not in existing
                ]
                if before - len(kept):
                    utils.logger.info(f"[ZhihuCrawler.search] 跳过已入库 {before - len(kept)} 条")

        stored: List[ZhihuContent] = []
        for content in kept:
            try:
                await zhihu_store.update_zhihu_content(content)
                stored.append(content)
                run_state.add_stored(1)  # 真正入库条数（过滤/跳过后）
            except Exception as ex:
                utils.logger.error(
                    f"[ZhihuCrawler.search] store failed content_id={content.content_id}: {ex}"
                )
        return stored, page_resolved_ts

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
        utils.logger.info("[ZhihuCrawler.search] Begin search zhihu keywords")
        zhihu_limit_count = 20  # zhihu limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < zhihu_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = zhihu_limit_count
        start_page = config.START_PAGE
        window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
        window_enabled = window_lo is not None or window_hi is not None

        # 知乎独有的服务端增强：排序（综合/最赞/最新）与时间档位（按窗口起点距今选最小覆盖档）
        sort_value = str(getattr(config, "ZHIHU_SEARCH_SORT", "") or "")
        search_sort = SearchSort(sort_value) if sort_value else SearchSort.DEFAULT
        search_time = SearchTime(
            pick_zhihu_search_time_value(window_lo, int(utils.get_current_timestamp()))
        )

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
                    f"[ZhihuCrawler.search] 宽泛词已跳过：{keyword.strip()}（设 ALLOW_BROAD_KEYWORDS=True 可放行）"
                )
                continue
            composed_keyword = compose_topic_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            )
            if composed_keyword != keyword.strip():
                utils.logger.info(f"[ZhihuCrawler.search] 主题限定：{keyword} → {composed_keyword}")
            keyword = composed_keyword
            source_keyword_var.set(keyword)
            utils.logger.info(f"[ZhihuCrawler.search] Current search keyword: {keyword}")
            page = 1
            # 防饥饿：仅综合排序时以一定概率把起始页随机后移（最新排序时间倒序天然无饥饿，不偏移）
            keyword_start_page = start_page
            if search_sort == SearchSort.DEFAULT and random.random() < float(
                getattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0)
            ):
                jitter = random.randint(1, int(getattr(config, "SEARCH_START_PAGE_JITTER_MAX", 1)))
                keyword_start_page += jitter
                utils.logger.info(f"[ZhihuCrawler.search] 防饥饿起始页偏移 +{jitter} → 从第 {keyword_start_page} 页开始")
            # 起始页 jitter 仅平移翻页窗口：跳过的页不发请求、不计入已抓页数（jitter=0 时与原行为等价）
            # 通用爬取历史：本关键词一轮搜索写一行，try/except/finally 保证异常路径也落一行
            run_state = RunState(
                platform="zhihu",
                source_keyword=keyword,
                started_at=int(utils.get_current_timestamp()),
            )
            try:
                # 配额按"新增入库条数"计（不再按页数），被过滤/跳过已入库的内容不烧配额；
                # 页数保护上限防止贫瘠词无限翻页
                while should_fetch_next_page(
                    run_state.items_stored,
                    run_state.pages_fetched,
                    config.CRAWLER_MAX_NOTES_COUNT,
                    int(getattr(config, "CRAWL_MAX_PAGES_PER_KEYWORD", 10)),
                ):
                    if page < keyword_start_page:
                        utils.logger.info(f"[ZhihuCrawler.search] Skip page {page}")
                        page += 1
                        continue
                    utils.logger.info(f"[ZhihuCrawler.search] search zhihu keyword: {keyword}, page: {page}")
                    content_list: List[ZhihuContent] = await self.zhihu_client.get_note_by_keyword(
                        keyword=keyword,
                        page=page,
                        sort=search_sort,
                        search_time=search_time,
                    )
                    run_state.add_page()
                    run_state.add_seen(len(content_list))
                    if not content_list:
                        utils.logger.info("[ZhihuCrawler.search] Search content list is empty")
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break

                    stored, page_resolved_ts = await self._filter_and_store_page(
                        content_list, window_lo, window_hi, window_enabled, run_state
                    )

                    # 评论只对本页新入库内容抓取（跟随全局 ENABLE_GET_COMMENTS）
                    await self.batch_get_content_comments(stored)

                    # 最新排序（时间倒序）且整页发布时间全部早于窗口起点 → 提前停止翻页
                    if (
                        search_sort == SearchSort.CREATE_TIME
                        and window_lo is not None
                        and page_resolved_ts
                        and all(ts < window_lo for ts in page_resolved_ts)
                    ):
                        utils.logger.info("[ZhihuCrawler.search] 整页发布时间早于窗口起点，提前停止翻页")
                        run_state.mark_stop(STOP_WINDOW_EXHAUSTED)
                        break

                    page += 1

                    # Sleep after page navigation
                    await utils.random_crawl_sleep()
                    utils.logger.info(f"[ZhihuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                # 循环自然退出：入库配额达成归结 quota_reached（页保护上限触发则落 completed）
                if run_state.items_stored >= config.CRAWLER_MAX_NOTES_COUNT:
                    run_state.mark_stop(STOP_QUOTA_REACHED)
            except DataFetchError as ex:
                # 原行为是 return 中断全部关键词；现在记 exception 落一行历史后继续下一关键词
                run_state.mark_stop(STOP_EXCEPTION)
                utils.logger.error(f"[ZhihuCrawler.search] Search content error, keyword: {keyword}, error: {ex}")
            except asyncio.CancelledError:
                # CancelledError 是 BaseException，下面的 except Exception 抓不住；不显式拦，
                # finally 会把被取消的一轮记成 completed（假遥测）。对齐快手。
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            except Exception:
                # 其他异常路径也落一行历史（stop_reason=exception），异常按微博行为继续上抛
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())

    async def batch_get_content_comments(self, content_list: List[ZhihuContent]):
        """
        Batch get content comments
        Args:
            content_list:

        Returns:

        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(
                f"[ZhihuCrawler.batch_get_content_comments] Crawling comment mode is not enabled"
            )
            return

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for content_item in content_list:
            task = asyncio.create_task(
                self.get_comments(content_item, semaphore), name=content_item.content_id
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(
        self, content_item: ZhihuContent, semaphore: asyncio.Semaphore
    ):
        """
        Get note comments with keyword filtering and quantity limitation
        Args:
            content_item:
            semaphore:

        Returns:

        """
        async with semaphore:
            utils.logger.info(
                f"[ZhihuCrawler.get_comments] Begin get note id comments {content_item.content_id}"
            )

            # Sleep before fetching comments
            await utils.random_crawl_sleep()
            utils.logger.info(f"[ZhihuCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for content {content_item.content_id}")

            await self.zhihu_client.get_note_all_comments(
                content=content_item,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=zhihu_store.batch_update_zhihu_note_comments,
            )

    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        utils.logger.info(
            "[ZhihuCrawler.get_creators_and_notes] Begin get xiaohongshu creators"
        )
        for user_link in config.ZHIHU_CREATOR_URL_LIST:
            utils.logger.info(
                f"[ZhihuCrawler.get_creators_and_notes] Begin get creator {user_link}"
            )
            user_url_token = user_link.split("/")[-1]
            # get creator detail info from web html content
            createor_info: ZhihuCreator = await self.zhihu_client.get_creator_info(
                url_token=user_url_token
            )
            if not createor_info:
                utils.logger.info(
                    f"[ZhihuCrawler.get_creators_and_notes] Creator {user_url_token} not found"
                )
                continue

            utils.logger.info(
                f"[ZhihuCrawler.get_creators_and_notes] Creator info: {createor_info}"
            )
            await zhihu_store.save_creator(creator=createor_info)

            # By default, only answer information is extracted, uncomment below if articles and videos are needed

            # Get all anwser information of the creator
            all_content_list = await self.zhihu_client.get_all_anwser_by_creator(
                creator=createor_info,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=zhihu_store.batch_update_zhihu_contents,
            )

            # Get all articles of the creator's contents
            # all_content_list = await self.zhihu_client.get_all_articles_by_creator(
            #     creator=createor_info,
            #     crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
            #     callback=zhihu_store.batch_update_zhihu_contents
            # )

            # Get all videos of the creator's contents
            # all_content_list = await self.zhihu_client.get_all_videos_by_creator(
            #     creator=createor_info,
            #     crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
            #     callback=zhihu_store.batch_update_zhihu_contents
            # )

            # Get all comments of the creator's contents
            await self.batch_get_content_comments(all_content_list)

    async def get_note_detail(
        self, full_note_url: str, semaphore: asyncio.Semaphore
    ) -> Optional[ZhihuContent]:
        """
        Get note detail
        Args:
            full_note_url: str
            semaphore:

        Returns:

        """
        async with semaphore:
            utils.logger.info(
                f"[ZhihuCrawler.get_specified_notes] Begin get specified note {full_note_url}"
            )
            # Judge note type
            note_type: str = judge_zhihu_url(full_note_url)
            if note_type == constant.ANSWER_NAME:
                question_id = full_note_url.split("/")[-3]
                answer_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get answer info, question_id: {question_id}, answer_id: {answer_id}"
                )
                result = await self.zhihu_client.get_answer_info(question_id, answer_id)

                # Sleep after fetching answer details
                await utils.random_crawl_sleep()
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching answer details {answer_id}")

                return result

            elif note_type == constant.ARTICLE_NAME:
                article_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get article info, article_id: {article_id}"
                )
                result = await self.zhihu_client.get_article_info(article_id)

                # Sleep after fetching article details
                await utils.random_crawl_sleep()
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching article details {article_id}")

                return result

            elif note_type == constant.VIDEO_NAME:
                video_id = full_note_url.split("/")[-1]
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Get video info, video_id: {video_id}"
                )
                result = await self.zhihu_client.get_video_info(video_id)

                # Sleep after fetching video details
                await utils.random_crawl_sleep()
                utils.logger.info(f"[ZhihuCrawler.get_note_detail] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {video_id}")

                return result

    async def get_specified_notes(self):
        """
        Get the information and comments of the specified post
        Returns:

        """
        get_note_detail_task_list = []
        for full_note_url in config.ZHIHU_SPECIFIED_ID_LIST:
            # remove query params
            full_note_url = full_note_url.split("?")[0]
            crawler_task = self.get_note_detail(
                full_note_url=full_note_url,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_notes: List[ZhihuContent] = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for index, note_detail in enumerate(note_details):
            if not note_detail:
                utils.logger.info(
                    f"[ZhihuCrawler.get_specified_notes] Note {config.ZHIHU_SPECIFIED_ID_LIST[index]} not found"
                )
                continue

            note_detail = cast(ZhihuContent, note_detail)  # only for type check
            need_get_comment_notes.append(note_detail)
            await zhihu_store.update_zhihu_content(note_detail)

        await self.batch_get_content_comments(need_get_comment_notes)

    async def create_zhihu_client(self, httpx_proxy: Optional[str]) -> ZhiHuClient:
        """Create zhihu client"""
        utils.logger.info(
            "[ZhihuCrawler.create_zhihu_client] Begin create zhihu API client ..."
        )
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )
        zhihu_client_obj = ZhiHuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cookie": cookie_str,
                "priority": "u=1, i",
                "referer": "https://www.zhihu.com/search?q=python&time_interval=a_year&type=content",
                "user-agent": self.user_agent,
                "x-api-version": "3.0.91",
                "x-app-za": "OS=Web",
                "x-requested-with": "fetch",
                "x-zse-93": "101_3_3.0",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return zhihu_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info(
            "[ZhihuCrawler.launch_browser] Begin create browser context ..."
        )
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
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
                channel="chrome",  # Use system Chrome stable version
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
            utils.logger.info(f"[ZhihuCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[ZhihuCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(
                chromium, playwright_proxy, user_agent, headless
            )

    async def close(self):
        """Close browser context"""
        # Special handling if using CDP mode
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[ZhihuCrawler.close] Browser context closed ...")
