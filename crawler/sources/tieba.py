"""备用数据源：百度贴吧（重试 + Playwright 备用）。"""

import logging
import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from crawler.config import (
    CRAWLER_HEADLESS,
    DESKTOP_UA,
    TIEBA_KW,
    TIEBA_LIMIT,
    TIEBA_RETRIES,
    TIEBA_TIMEOUT,
)
from crawler.schema import CrawlPost

logger = logging.getLogger(__name__)

BASE = "https://tieba.baidu.com"


def _parse_list_html(html: str, limit: int) -> list[CrawlPost]:
    posts: list[CrawlPost] = []
    soup = BeautifulSoup(html, "html.parser")
    for li in soup.select("li.j_thread_list"):
        if len(posts) >= limit:
            break
        tid = li.get("data-tid")
        if not tid:
            continue
        title_el = li.select_one("a.j_th_tit")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        thread_url = urljoin(BASE, href) if href else f"{BASE}/p/{tid}"
        author_el = li.select_one(".frs-author-name")
        author = author_el.get_text(strip=True) if author_el else ""
        reply_el = li.select_one(".threadlist_rep_num")
        reply = reply_el.get_text(strip=True) if reply_el else "0"
        posts.append(
            CrawlPost(
                id=f"tieba_{tid}",
                platform="tieba",
                title=title,
                content=f"贴吧主题帖，回复数约 {reply}",
                author=author,
                publish_time=None,
                url=thread_url,
            )
        )
    return posts


def _from_requests(kw: str, limit: int) -> list[CrawlPost]:
    url = f"{BASE}/f?kw={quote(kw)}&ie=utf-8"
    headers = {
        "User-Agent": DESKTOP_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://tieba.baidu.com/",
    }
    for attempt in range(1, TIEBA_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=TIEBA_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            if "百度安全验证" in resp.text or "验证码" in resp.text:
                logger.warning("贴吧第 %s 次：触发安全验证页", attempt)
                time.sleep(2)
                continue
            posts = _parse_list_html(resp.text, limit)
            if posts:
                return posts
        except Exception as e:
            logger.warning("贴吧 HTTP 第 %s 次失败: %s", attempt, e)
            time.sleep(2)
    return []


def _from_playwright(kw: str, limit: int) -> list[CrawlPost]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    url = f"{BASE}/f?kw={quote(kw)}&ie=utf-8"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CRAWLER_HEADLESS)
            page = browser.new_page(user_agent=DESKTOP_UA)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
        return _parse_list_html(html, limit)
    except Exception as e:
        logger.warning("贴吧 Playwright 失败: %s", e)
        return []


def crawl_tieba(kw: str = TIEBA_KW, limit: int = TIEBA_LIMIT) -> list[CrawlPost]:
    posts = _from_requests(kw, limit)
    if len(posts) < limit // 2:
        logger.info("尝试 Playwright 采集贴吧…")
        posts = _merge(posts, _from_playwright(kw, limit))
    logger.info("贴吧采集完成: %s 条", len(posts))
    return posts[:limit]


def _merge(a: list[CrawlPost], b: list[CrawlPost]) -> list[CrawlPost]:
    seen = {p.id for p in a}
    out = list(a)
    for p in b:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out
