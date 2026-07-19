# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/tieba/core.py
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
from model.m_baidu_tieba import TiebaCreator, TiebaNote
from proxy.proxy_ip_pool import IpInfoModel, ProxyIpPool, create_ip_pool
from store import run_history as run_history_store
from store import tieba as tieba_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from tools.crawl_quota import should_fetch_next_page
from tools.publish_time_window import is_within_window, parse_tieba_publish_time_ms, parse_window
from tools.run_history import (
    STOP_EMPTY_PAGE,
    STOP_EXCEPTION,
    STOP_PARSER_MISMATCH,
    STOP_QUOTA_REACHED,
    STOP_WINDOW_EXHAUSTED,
    RunState,
)
from tools.subscription import STOP_CAUGHT_UP, split_new_ids, subscription_should_stop

from .exception import TiebaSearchParserMismatchError
from tools.topic_scope import compose_topic_keyword, is_broad_keyword, is_marketing_noise, matches_topic
from var import crawler_type_var, source_keyword_var

from .client import BaiduTieBaClient
from .field import SearchNoteType, SearchSortType
from .help import TieBaExtractor
from .login import BaiduTieBaLogin


class TieBaCrawler(AbstractCrawler):
    context_page: Page
    tieba_client: BaiduTieBaClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://tieba.baidu.com"
        self.cookie_urls = [self.index_url]
        self.user_agent = utils.get_user_agent()
        self._page_extractor = TieBaExtractor()
        self.cdp_manager = None

    async def start(self) -> None:
        """
        Start the crawler
        Returns:

        """
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            utils.logger.info(
                "[BaiduTieBaCrawler.start] Begin create ip proxy pool ..."
            )
            ip_proxy_pool = await create_ip_pool(
                config.IP_PROXY_POOL_COUNT, enable_validate_ip=True
            )
            ip_proxy_info: IpInfoModel = await ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)
            utils.logger.info(
                f"[BaiduTieBaCrawler.start] Init default ip proxy, value: {httpx_proxy_format}"
            )

        async with async_playwright() as playwright:
            # Choose startup mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[BaiduTieBaCrawler] Launching browser in CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[BaiduTieBaCrawler] Launching browser in standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )

            # Inject anti-detection scripts - for Baidu's special detection
            await self._inject_anti_detection_scripts()

            self.context_page = await self.browser_context.new_page()

            # First visit Baidu homepage, then click Tieba link to avoid triggering security verification
            await self._navigate_to_tieba_via_baidu()

            # Create a client to interact with the baidutieba website.
            self.tieba_client = await self.create_tieba_client(
                httpx_proxy_format,
                ip_proxy_pool if config.ENABLE_IP_PROXY else None
            )

            # Check login status and perform login if necessary
            if not await self.tieba_client.pong(browser_context=self.browser_context):
                login_obj = BaiduTieBaLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.tieba_client.update_cookies(
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
                # 上游此处还会调 get_specified_tieba_notes()（按 TIEBA_NAME_LIST 走详情页
                # 全吧爬取）。该联动已切断：TIEBA_NAME_LIST 现在是订阅源清单（creator 型），
                # 若保留，配好订阅源后每次关键词搜索都会隐式触发详情页大爬——两条路径必须解耦。
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # 订阅式（生产路径）：TIEBA_NAME_LIST 按吧增量盯梢（列表页直存）。
                # 上游的个人主页爬取保留在 get_creators_and_notes（TIEBA_CREATOR_URL_LIST）。
                if config.TIEBA_NAME_LIST:
                    await self.subscribe_tieba_boards()
                else:
                    await self.get_creators_and_notes()
            else:
                pass

            utils.logger.info("[BaiduTieBaCrawler.start] Tieba Crawler finished ...")

    async def search(self) -> None:
        """
        Search for notes and retrieve their comment information.
        Returns:

        """
        utils.logger.info(
            "[BaiduTieBaCrawler.search] Begin search baidu tieba keywords"
        )
        tieba_limit_count = 10  # tieba limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < tieba_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = tieba_limit_count
        start_page = config.START_PAGE
        window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
        window_enabled = window_lo is not None or window_hi is not None
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
                    f"[TieBaCrawler.search] 宽泛词已跳过：{keyword.strip()}（设 ALLOW_BROAD_KEYWORDS=True 可放行）"
                )
                continue
            composed_keyword = compose_topic_keyword(
                keyword,
                getattr(config, "CRAWL_TOPIC_QUALIFIER", ""),
                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
            )
            if composed_keyword != keyword.strip():
                utils.logger.info(f"[TieBaCrawler.search] 主题限定：{keyword} → {composed_keyword}")
            keyword = composed_keyword
            source_keyword_var.set(keyword)
            utils.logger.info(
                f"[BaiduTieBaCrawler.search] Current search keyword: {keyword}"
            )
            page = 1
            # 防饥饿：本关键词开搜前，以一定概率把起始页随机后移，避免每次都只翻到前几页
            keyword_start_page = start_page
            if random.random() < float(getattr(config, "SEARCH_START_PAGE_JITTER_PROB", 0.0)):
                jitter = random.randint(1, int(getattr(config, "SEARCH_START_PAGE_JITTER_MAX", 1)))
                keyword_start_page += jitter
                utils.logger.info(f"[TieBaCrawler.search] 防饥饿起始页偏移 +{jitter} → 从第 {keyword_start_page} 页开始")
            # 起始页 jitter 仅平移翻页窗口：跳过的页不发请求、不计入已抓页数（jitter=0 时与原行为等价）
            # 通用爬取历史：本关键词一轮搜索写一行，try/finally 保证异常路径也落一行
            run_state = RunState(
                platform="tieba",
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
                        utils.logger.info(f"[BaiduTieBaCrawler.search] Skip page {page}")
                        page += 1
                        continue
                    try:
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] search tieba keyword: {keyword}, page: {page}"
                        )
                        notes_list: List[TiebaNote] = (
                            await self.tieba_client.get_notes_by_keyword(
                                keyword=keyword,
                                page=page,
                                page_size=tieba_limit_count,
                                sort=SearchSortType.TIME_DESC,
                                note_type=SearchNoteType.FIXED_THREAD,
                            )
                        )
                        run_state.add_page()
                        run_state.add_seen(len(notes_list or []))  # 平台返回原始条数（过滤前）
                        if not notes_list:
                            utils.logger.info(
                                f"[BaiduTieBaCrawler.search] Search note list is empty"
                            )
                            run_state.mark_stop(STOP_EMPTY_PAGE)
                            break
                        utils.logger.info(
                            f"[BaiduTieBaCrawler.search] Note list len: {len(notes_list)}"
                        )

                        # 窗口过滤与主题过滤相互独立：窗口过滤仅在启用窗口时生效，主题过滤按开关始终生效；
                        # 两者合并为对 notes_list 的一次遍历。
                        page_resolved_ts: List[int] = []
                        kept_notes: List[TiebaNote] = []
                        window_filtered_count = 0
                        topic_filtered_count = 0
                        marketing_filtered_count = 0
                        topic_filter_enabled = getattr(config, "ENABLE_TOPIC_RELEVANCE_FILTER", False)
                        negative_filter_enabled = getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False)
                        for note in notes_list:
                            if window_enabled:
                                ts_ms = parse_tieba_publish_time_ms(note.publish_time)
                                if ts_ms is not None:
                                    page_resolved_ts.append(ts_ms)
                                if not is_within_window(ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN):
                                    window_filtered_count += 1
                                    continue
                            if topic_filter_enabled and not matches_topic(
                                [note.title, note.desc, note.tieba_name],
                                getattr(config, "TOPIC_RELEVANCE_TERMS", []),
                            ):
                                topic_filtered_count += 1
                                continue
                            # 营销内容负面词表（第三道防线）：命中负面词且无救回词的推广内容不入库
                            if negative_filter_enabled and is_marketing_noise(
                                [note.title, note.desc, note.tieba_name],
                                getattr(config, "TOPIC_NEGATIVE_TERMS", []),
                                getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", []),
                            ):
                                marketing_filtered_count += 1
                                continue
                            kept_notes.append(note)
                        if window_filtered_count:
                            utils.logger.info(
                                f"[TieBaCrawler.search] 发布时间窗口过滤 {window_filtered_count} 条"
                            )
                        if topic_filtered_count:
                            utils.logger.info(
                                f"[TieBaCrawler.search] 主题过滤：跳过 {topic_filtered_count} 条与主题无关的帖子"
                            )
                        if marketing_filtered_count:
                            utils.logger.info(
                                f"[TieBaCrawler.search] 营销内容过滤：跳过 {marketing_filtered_count} 条"
                            )
                        notes_list = kept_notes

                        # 爬取阶段跳过已入库帖子（省请求额度，仿小红书 XHS_SKIP_EXISTING_NOTE_DETAILS）：
                        # 必须在窗口/主题过滤之后、入库（及评论抓取，_handle_search_notes 内部决定）之前。
                        # page_resolved_ts 已在上面的过滤循环里收集完毕，不受本次跳过影响——早停看的是整页
                        # 发布时间是否过旧，与帖子是否已入库无关，已存在的帖子仍然贡献了它的发布时间。
                        if notes_list and bool(getattr(config, "TIEBA_SKIP_EXISTING_NOTES", True)):
                            existing_note_ids = await tieba_store.batch_get_existing_note_ids(
                                [str(note.note_id or "").strip() for note in notes_list]
                            )
                            if existing_note_ids:
                                before_count = len(notes_list)
                                notes_list = [
                                    note for note in notes_list
                                    if str(note.note_id or "").strip() not in existing_note_ids
                                ]
                                skipped_existing_count = before_count - len(notes_list)
                                if skipped_existing_count:
                                    utils.logger.info(f"[TieBaCrawler.search] 跳过已入库 {skipped_existing_count} 条")

                        if notes_list:
                            stored_count = await self._handle_search_notes(notes_list)
                            run_state.add_stored(stored_count)  # 实际入库条数（评论路径=详情抓取成功数）

                        if (
                            window_enabled
                            and window_lo is not None
                            and page_resolved_ts
                            and all(ts < window_lo for ts in page_resolved_ts)
                        ):
                            utils.logger.info("[TieBaCrawler.search] 整页发布时间早于窗口起点，提前停止翻页")
                            run_state.mark_stop(STOP_WINDOW_EXHAUSTED)
                            break

                        # Sleep after page navigation
                        await utils.random_crawl_sleep()
                        utils.logger.info(f"[TieBaCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page}")

                        page += 1
                    except TiebaSearchParserMismatchError as ex:
                        # DOM 变化：重试无用，落 parser_mismatch 提示人工适配解析器
                        # （mark_stop 首个原因生效，外层 except 的 STOP_EXCEPTION 不会覆盖）
                        run_state.mark_stop(STOP_PARSER_MISMATCH)
                        utils.logger.error(
                            f"[BaiduTieBaCrawler.search] 解析器失配（DOM 可能已变化）: {ex}"
                        )
                        raise
                    except Exception as ex:
                        utils.logger.error(
                            f"[BaiduTieBaCrawler.search] Search keywords error, current page: {page}, current keyword: {keyword}, err: {ex}"
                        )
                        # 页级异常不再静默吞掉（审计修复 2026-07-17）：原来 break 后 search()
                        # 正常返回，队列把任务标 done——瞬时网络错误也不重试，数据静默少采。
                        # 风控/Cookie 失效（TiebaAccessBlockedError）也走这里：可重试故障，
                        # 上抛让外层记 STOP_EXCEPTION 并落历史行，队列标 failed 可重排。
                        raise

                # 循环自然退出：入库配额达成归结 quota_reached（页保护上限触发则落 completed）
                if run_state.items_stored >= config.CRAWLER_MAX_NOTES_COUNT:
                    run_state.mark_stop(STOP_QUOTA_REACHED)
            except asyncio.CancelledError:
                # CancelledError 是 BaseException，下面的 except Exception 抓不住；不显式拦，
                # finally 会把被取消的一轮记成 completed（假遥测）。对齐快手。
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            except Exception:
                # 页内异常已被上面的 except 上抛；此处兜底其余异常路径也落一行历史
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())

    async def _handle_search_notes(self, notes_list: List[TiebaNote]) -> int:
        """入库搜索结果，返回真正调用 update_tieba_note 的条数（供配额/爬取历史精确计数）。

        评论路径经详情抓取，失败的帖子不会入库，只计成功数——否则详情全失败时
        items_stored 虚高，贫瘠词会漏判一轮。
        """
        if config.ENABLE_GET_COMMENTS:
            return await self.get_specified_notes(
                note_id_list=[note_detail.note_id for note_detail in notes_list]
            )

        stored_count = 0
        for note_detail in notes_list:
            # 单条 store 失败只跳过这一条、不中断整批（对齐知乎/快手/小红书）：
            # 只对成功入库的计数。原来无隔离，一条抛异常会冒泡中断整个关键词。
            try:
                await tieba_store.update_tieba_note(note_detail)
            except Exception as store_err:
                utils.logger.error(
                    f"[TieBaCrawler._handle_search_notes] store failed note_id={note_detail.note_id}: {store_err}"
                )
                continue
            stored_count += 1
        return stored_count

    async def subscribe_tieba_boards(self) -> None:
        """订阅式：按吧增量盯梢（生产路径，P0）。

        与上游 get_specified_tieba_notes 的区别：
        - **列表页直存，不进详情页**——详情页是贴吧最脆弱的路径（DOM 多变、多跳转
          多风控），列表卡片的标题/摘要/时间足够入库分析（与搜索路径同一取舍）；
        - **增量刹车**：逐页对照已入库集合，整页无新帖 = 已追平立即停；首轮冷启动
          靠 TIEBA_SUB_MAX_PAGES 页上限兜底（中山大学吧存量 345 万帖，绝不全吞）；
        - **营销过滤保留、主题过滤不做**——吧本身即主题，吧内帖不会都复读校名；
        - **run_history 遥测**：source_keyword 记 `sub:吧名吧`，单源失败不拖垮其余源。
        """

        page_size = 50  # 贴吧列表页 pn 步长
        page_cap = max(int(getattr(config, "TIEBA_SUB_MAX_PAGES", 10)), 1)
        negative_filter_enabled = getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False)
        for tieba_name in config.TIEBA_NAME_LIST:
            source_label = f"sub:{tieba_name}吧"
            source_keyword_var.set(source_label)
            run_state = RunState(
                platform="tieba",
                source_keyword=source_label,
                started_at=int(utils.get_current_timestamp()),
            )
            try:
                page_num = 0
                while True:
                    note_list: List[TiebaNote] = await self.tieba_client.get_notes_by_tieba_name(
                        tieba_name=tieba_name, page_num=page_num
                    )
                    run_state.add_page()
                    run_state.add_seen(len(note_list or []))
                    if not note_list:
                        run_state.mark_stop(STOP_EMPTY_PAGE)
                        break

                    kept = [
                        note for note in note_list
                        if not (
                            negative_filter_enabled
                            and is_marketing_noise(
                                [note.title, note.desc, note.tieba_name],
                                getattr(config, "TOPIC_NEGATIVE_TERMS", []),
                                getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", []),
                            )
                        )
                    ]
                    page_ids = [str(note.note_id or "").strip() for note in kept]
                    existing = await tieba_store.batch_get_existing_note_ids(page_ids)
                    new_ids = set(split_new_ids(page_ids, existing))
                    stored_this_page = 0
                    for note in kept:
                        note_id = str(note.note_id or "").strip()
                        if note_id not in new_ids:
                            continue
                        if not note.tieba_name:
                            note.tieba_name = tieba_name
                        await tieba_store.update_tieba_note(note)
                        stored_this_page += 1
                    run_state.add_stored(stored_this_page)
                    if stored_this_page:
                        utils.logger.info(
                            f"[TieBaCrawler.subscribe_tieba_boards] {source_label} "
                            f"第 {run_state.pages_fetched} 页新增 {stored_this_page} 条"
                        )

                    stop, reason = subscription_should_stop(
                        stored_this_page, run_state.pages_fetched, page_cap
                    )
                    if stop:
                        if reason == STOP_CAUGHT_UP:
                            run_state.mark_stop(STOP_EMPTY_PAGE)  # 已追平：订阅的正常收工
                        # page_cap 不标记 → finish 落 completed（首轮冷启动到上限）
                        utils.logger.info(
                            f"[TieBaCrawler.subscribe_tieba_boards] {source_label} 停止：{reason}"
                        )
                        break
                    await utils.random_crawl_sleep()
                    page_num += page_size
            except asyncio.CancelledError:
                run_state.mark_stop(STOP_EXCEPTION)
                raise
            except Exception as ex:
                # 订阅源相互独立：单源失败记异常行后继续下一个源
                run_state.mark_stop(STOP_EXCEPTION)
                utils.logger.error(
                    f"[TieBaCrawler.subscribe_tieba_boards] {source_label} 失败：{ex}"
                )
            finally:
                run_state.finish(int(utils.get_current_timestamp()))
                await run_history_store.save_crawler_run_history(run_state.as_row())

    async def get_specified_tieba_notes(self):
        """
        Get the information and comments of the specified post by tieba name
        Returns:

        """
        tieba_limit_count = 50
        if config.CRAWLER_MAX_NOTES_COUNT < tieba_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = tieba_limit_count
        for tieba_name in config.TIEBA_NAME_LIST:
            utils.logger.info(
                f"[BaiduTieBaCrawler.get_specified_tieba_notes] Begin get tieba name: {tieba_name}"
            )
            page_number = 0
            while page_number <= config.CRAWLER_MAX_NOTES_COUNT:
                note_list: List[TiebaNote] = (
                    await self.tieba_client.get_notes_by_tieba_name(
                        tieba_name=tieba_name, page_num=page_number
                    )
                )
                if not note_list:
                    utils.logger.info(
                        f"[BaiduTieBaCrawler.get_specified_tieba_notes] Get note list is empty"
                    )
                    break

                utils.logger.info(
                    f"[BaiduTieBaCrawler.get_specified_tieba_notes] tieba name: {tieba_name} note list len: {len(note_list)}"
                )
                await self.get_specified_notes([note.note_id for note in note_list])

                # Sleep after processing notes
                await utils.random_crawl_sleep()
                utils.logger.info(f"[TieBaCrawler.get_specified_tieba_notes] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after processing notes from page {page_number}")

                page_number += tieba_limit_count

    async def get_specified_notes(
        self, note_id_list: List[str] = config.TIEBA_SPECIFIED_ID_LIST
    ) -> int:
        """
        Get the information and comments of the specified post
        Args:
            note_id_list:

        Returns:
            真正入库（update_tieba_note）的条数：详情抓取失败的帖子不计
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(note_id=note_id, semaphore=semaphore)
            for note_id in note_id_list
        ]
        note_details = await asyncio.gather(*task_list)
        note_details_model: List[TiebaNote] = []
        for note_detail in note_details:
            if note_detail is not None:
                note_details_model.append(note_detail)
                await tieba_store.update_tieba_note(note_detail)
        await self.batch_get_note_comments(note_details_model)
        return len(note_details_model)

    async def get_note_detail_async_task(
        self, note_id: str, semaphore: asyncio.Semaphore
    ) -> Optional[TiebaNote]:
        """
        Get note detail
        Args:
            note_id: baidu tieba note id
            semaphore: asyncio semaphore

        Returns:

        """
        async with semaphore:
            try:
                utils.logger.info(
                    f"[BaiduTieBaCrawler.get_note_detail] Begin get note detail, note_id: {note_id}"
                )
                note_detail: TiebaNote = await self.tieba_client.get_note_by_id(note_id)

                # Sleep after fetching note details
                await utils.random_crawl_sleep()
                utils.logger.info(f"[TieBaCrawler.get_note_detail_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching note details {note_id}")

                if not note_detail:
                    utils.logger.error(
                        f"[BaiduTieBaCrawler.get_note_detail] Get note detail error, note_id: {note_id}"
                    )
                    return None
                return note_detail
            except Exception as ex:
                utils.logger.error(
                    f"[BaiduTieBaCrawler.get_note_detail] Get note detail error: {ex}"
                )
                return None
            except KeyError as ex:
                utils.logger.error(
                    f"[BaiduTieBaCrawler.get_note_detail] have not fund note detail note_id:{note_id}, err: {ex}"
                )
                return None

    async def batch_get_note_comments(self, note_detail_list: List[TiebaNote]):
        """
        Batch get note comments
        Args:
            note_detail_list:

        Returns:

        """
        if not config.ENABLE_GET_COMMENTS:
            return

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_detail in note_detail_list:
            task = asyncio.create_task(
                self.get_comments_async_task(note_detail, semaphore),
                name=note_detail.note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments_async_task(
        self, note_detail: TiebaNote, semaphore: asyncio.Semaphore
    ):
        """
        Get comments async task
        Args:
            note_detail:
            semaphore:

        Returns:

        """
        async with semaphore:
            utils.logger.info(
                f"[BaiduTieBaCrawler.get_comments] Begin get note id comments {note_detail.note_id}"
            )

            # Sleep before fetching comments
            await utils.random_crawl_sleep()
            utils.logger.info(f"[TieBaCrawler.get_comments_async_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds before fetching comments for note {note_detail.note_id}")

            await self.tieba_client.get_note_all_comments(
                note_detail=note_detail,
                crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                callback=tieba_store.batch_update_tieba_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )

    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        utils.logger.info(
            "[WeiboCrawler.get_creators_and_notes] Begin get weibo creators"
        )
        for creator_url in config.TIEBA_CREATOR_URL_LIST:
            creator_page_html_content = await self.tieba_client.get_creator_info_by_url(
                creator_url=creator_url
            )
            creator_info: TiebaCreator = self._page_extractor.extract_creator_info(
                creator_page_html_content
            )
            if creator_info:
                utils.logger.info(
                    f"[WeiboCrawler.get_creators_and_notes] creator info: {creator_info}"
                )
                if not creator_info:
                    raise Exception("Get creator info error")

                await tieba_store.save_creator(user_info=creator_info)

                # Get all note information of the creator
                all_notes_list = (
                    await self.tieba_client.get_all_notes_by_creator_user_name(
                        user_name=creator_info.user_name,
                        crawl_interval=0,
                        callback=tieba_store.batch_update_tieba_notes,
                        max_note_count=config.CRAWLER_MAX_NOTES_COUNT,
                        creator_page_html_content=creator_page_html_content,
                    )
                )

                await self.batch_get_note_comments(all_notes_list)

            else:
                utils.logger.error(
                    f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_url:{creator_url}"
                )

    async def _navigate_to_tieba_via_baidu(self):
        """
        Simulate real user access path:
        1. First visit Baidu homepage (https://www.baidu.com/)
        2. Wait for page to load
        3. Click "Tieba" link in top navigation bar
        4. Jump to Tieba homepage

        This avoids triggering Baidu's security verification
        """
        utils.logger.info("[TieBaCrawler] Simulating real user access path...")

        try:
            # Step 1: Visit Baidu homepage
            utils.logger.info("[TieBaCrawler] Step 1: Visiting Baidu homepage https://www.baidu.com/")
            await self.context_page.goto("https://www.baidu.com/", wait_until="domcontentloaded")

            # Step 2: Wait for page loading, using delay setting from config file
            utils.logger.info(f"[TieBaCrawler] Step 2: Waiting {config.CRAWLER_MAX_SLEEP_SEC} seconds to simulate user browsing...")
            await utils.random_crawl_sleep()

            # Step 3: Find and click "Tieba" link
            utils.logger.info("[TieBaCrawler] Step 3: Finding and clicking 'Tieba' link...")

            # Try multiple selectors to ensure finding the Tieba link
            tieba_selectors = [
                'a[href="http://tieba.baidu.com/"]',
                'a[href="https://tieba.baidu.com/"]',
                'a.mnav:has-text("贴吧")',
                'text=贴吧',
            ]

            tieba_link = None
            for selector in tieba_selectors:
                try:
                    tieba_link = await self.context_page.wait_for_selector(selector, timeout=5000)
                    if tieba_link:
                        utils.logger.info(f"[TieBaCrawler] Found Tieba link (selector: {selector})")
                        break
                except Exception:
                    continue

            if not tieba_link:
                utils.logger.warning("[TieBaCrawler] Tieba link not found, directly accessing Tieba homepage")
                await self.context_page.goto(self.index_url, wait_until="domcontentloaded")
                return

            # Step 4: Click Tieba link (check if it will open in a new tab)
            utils.logger.info("[TieBaCrawler] Step 4: Clicking Tieba link...")

            # Check link's target attribute
            target_attr = await tieba_link.get_attribute("target")
            utils.logger.info(f"[TieBaCrawler] Link target attribute: {target_attr}")

            if target_attr == "_blank":
                # If it's a new tab, need to wait for new page and switch
                utils.logger.info("[TieBaCrawler] Link will open in new tab, waiting for new page...")

                async with self.browser_context.expect_page() as new_page_info:
                    await tieba_link.click()

                # Get newly opened page
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded")

                # Close old Baidu homepage
                await self.context_page.close()

                # Switch to new Tieba page
                self.context_page = new_page
                utils.logger.info("[TieBaCrawler] Successfully switched to new tab (Tieba page)")
            else:
                # If it's same tab navigation, wait for navigation normally
                utils.logger.info("[TieBaCrawler] Link navigates in current tab...")
                async with self.context_page.expect_navigation(wait_until="domcontentloaded"):
                    await tieba_link.click()

            # Step 5: Wait for page to stabilize, using delay setting from config file
            utils.logger.info(f"[TieBaCrawler] Step 5: Page loaded, waiting {config.CRAWLER_MAX_SLEEP_SEC} seconds...")
            await utils.random_crawl_sleep()

            current_url = self.context_page.url
            utils.logger.info(f"[TieBaCrawler] Successfully entered Tieba via Baidu homepage! Current URL: {current_url}")

        except Exception as e:
            utils.logger.error(f"[TieBaCrawler] Failed to access Tieba via Baidu homepage: {e}")
            utils.logger.info("[TieBaCrawler] Fallback: directly accessing Tieba homepage")
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded")

    async def _inject_anti_detection_scripts(self):
        """
        Inject anti-detection JavaScript scripts
        For Baidu Tieba's special detection mechanism
        """
        utils.logger.info("[TieBaCrawler] Injecting anti-detection scripts...")

        # Lightweight anti-detection script, only covering key detection points
        anti_detection_js = """
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });

        // Override window.navigator.chrome
        if (!window.navigator.chrome) {
            window.navigator.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        }

        // Override Permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Override plugins length (make it look like there are plugins)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
            configurable: true
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
            configurable: true
        });

        // Remove window.cdc_ and other ChromeDriver remnants
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        console.log('[Anti-Detection] Scripts injected successfully');
        """

        await self.browser_context.add_init_script(anti_detection_js)
        utils.logger.info("[TieBaCrawler] Anti-detection scripts injected")

    async def create_tieba_client(
        self, httpx_proxy: Optional[str], ip_pool: Optional[ProxyIpPool] = None
    ) -> BaiduTieBaClient:
        """
        Create tieba client with real browser User-Agent and complete headers
        Args:
            httpx_proxy: HTTP proxy
            ip_pool: IP proxy pool

        Returns:
            BaiduTieBaClient instance
        """
        utils.logger.info("[TieBaCrawler.create_tieba_client] Begin create tieba API client...")

        # Extract User-Agent from real browser to avoid detection
        user_agent = await self.context_page.evaluate("() => navigator.userAgent")
        utils.logger.info(f"[TieBaCrawler.create_tieba_client] Extracted User-Agent from browser: {user_agent}")

        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )

        # Build complete browser request headers, simulating real browser behavior
        tieba_client = BaiduTieBaClient(
            timeout=10,
            ip_pool=ip_pool,
            default_ip_proxy=httpx_proxy,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "User-Agent": user_agent,  # Use real browser UA
                "Cookie": cookie_str,
                "Host": "tieba.baidu.com",
                "Referer": "https://tieba.baidu.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
            playwright_page=self.context_page,  # Pass in playwright page object
        )
        return tieba_client

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        Launch browser and create browser
        Args:
            chromium:
            playwright_proxy:
            user_agent:
            headless:

        Returns:

        """
        utils.logger.info(
            "[BaiduTieBaCrawler.launch_browser] Begin create browser context ..."
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
            utils.logger.info(f"[TieBaCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[TieBaCrawler] CDP mode launch failed, falling back to standard mode: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(
                chromium, playwright_proxy, user_agent, headless
            )

    async def close(self):
        """
        Close browser context
        Returns:

        """
        # If using CDP mode, need special handling
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[BaiduTieBaCrawler.close] Browser context closed ...")
