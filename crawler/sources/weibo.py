"""主数据源：微博（Cookie / 登录态 + Playwright 拦截 API）。"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from crawler.config import (
    CRAWLER_HEADLESS,
    REQUEST_TIMEOUT,
    USER_AGENT,
    WEIBO_COOKIE,
    WEIBO_KEYWORD,
    WEIBO_LIMIT,
    WEIBO_STATE_FILE,
)
from crawler.schema import CrawlPost

logger = logging.getLogger(__name__)

API_URL = "https://m.weibo.cn/api/container/getIndex"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_time(text: str) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    now = _utcnow()
    if "分钟前" in text:
        m = re.search(r"(\d+)", text)
        if m:
            return now - timedelta(minutes=int(m.group(1)))
    if "小时前" in text:
        m = re.search(r"(\d+)", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return None
    return None


def _cards_to_posts(cards: list, limit: int) -> list[CrawlPost]:
    posts: list[CrawlPost] = []
    for card in cards:
        if len(posts) >= limit:
            break
        mblog = card.get("mblog")
        if not mblog and card.get("card_group"):
            mblog = card["card_group"][0].get("mblog")
        if not mblog:
            continue
        mid = str(mblog.get("id") or mblog.get("mid") or "")
        if not mid:
            continue
        text = re.sub(r"<[^>]+>", "", (mblog.get("text") or "").strip())
        user = mblog.get("user") or {}
        posts.append(
            CrawlPost(
                id=f"weibo_{mid}",
                platform="weibo",
                title=text[:80] or f"微博 {mid}",
                content=text,
                author=user.get("screen_name") or "",
                publish_time=_parse_time(mblog.get("created_at", "")),
                url=f"https://m.weibo.cn/detail/{mid}",
            )
        )
    return posts


def _api_headers() -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://m.weibo.cn/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    if WEIBO_COOKIE:
        headers["Cookie"] = WEIBO_COOKIE
    return headers


def _from_api(keyword: str, limit: int) -> list[CrawlPost]:
    if not WEIBO_COOKIE:
        logger.info("未配置 WEIBO_COOKIE，跳过微博 API（见 docs/crawl-real-data.md）")
        return []

    posts: list[CrawlPost] = []
    containerid = f"100103type=1&q={quote(keyword)}"
    page = 1

    while len(posts) < limit and page <= 5:
        try:
            resp = requests.get(
                API_URL,
                params={"containerid": containerid, "page": page},
                headers=_api_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 432:
                logger.warning("微博 API 返回 432，需要有效 Cookie 或登录态")
                break
            resp.raise_for_status()
            cards = resp.json().get("data", {}).get("cards") or []
            posts.extend(_cards_to_posts(cards, limit - len(posts)))
        except Exception as e:
            logger.warning("微博 API 第 %s 页失败: %s", page, e)
            break
        page += 1
    return posts


def _from_playwright(keyword: str, limit: int) -> list[CrawlPost]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("未安装 playwright，请执行: pip install playwright && playwright install chromium")
        return []

    if not WEIBO_STATE_FILE.is_file():
        logger.info("未找到登录态 %s，请先运行: python scripts/save_weibo_login.py", WEIBO_STATE_FILE)
        return []

    posts: list[CrawlPost] = []
    captured: list[list] = []
    containerid = quote(f"100103type=1&q={keyword}")
    search_url = f"https://m.weibo.cn/search?containerid={containerid}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=CRAWLER_HEADLESS)
            context = browser.new_context(
                storage_state=str(WEIBO_STATE_FILE),
                user_agent=USER_AGENT,
                locale="zh-CN",
            )
            page = context.new_page()

            def on_response(response):
                if "getIndex" in response.url and response.status == 200:
                    try:
                        body = response.json()
                        cards = body.get("data", {}).get("cards") or []
                        if cards:
                            captured.append(cards)
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            # 滚动加载更多
            for _ in range(2):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            for cards in captured:
                posts = _merge(posts, _cards_to_posts(cards, limit))
                if len(posts) >= limit:
                    break
            browser.close()
    except Exception as e:
        logger.warning("微博 Playwright 采集失败: %s", e)
    return posts[:limit]


def crawl_weibo(keyword: str = WEIBO_KEYWORD, limit: int = WEIBO_LIMIT) -> list[CrawlPost]:
    posts = _from_api(keyword, limit)
    if len(posts) < limit // 2:
        logger.info("尝试 Playwright + 登录态采集微博…")
        posts = _merge(posts, _from_playwright(keyword, limit))
    logger.info("微博采集完成: %s 条", len(posts))
    return posts[:limit]


def _merge(a: list[CrawlPost], b: list[CrawlPost]) -> list[CrawlPost]:
    seen = {p.id for p in a}
    out = list(a)
    for p in b:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out
