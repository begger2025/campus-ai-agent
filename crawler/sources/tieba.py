"""备用数据源：百度贴吧（登录态 + Playwright 为主）。"""

import json
import logging
import re
import time
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from crawler.config import (
    CRAWLER_HEADLESS,
    DESKTOP_UA,
    TIEBA_COOKIE,
    TIEBA_KEYWORDS_FALLBACK,
    TIEBA_KW,
    TIEBA_LIMIT,
    TIEBA_PLAYWRIGHT_TIMEOUT,
    TIEBA_RETRIES,
    TIEBA_SKIP_HTTP,
    TIEBA_STATE_FILE,
    TIEBA_TIMEOUT,
)
from crawler.schema import CrawlPost

logger = logging.getLogger(__name__)

BASE = "https://tieba.baidu.com"
_SECURITY_MARKERS = ("百度安全验证", "验证码", "BIOC_OPTIONS", "passMod_authwidget")


def _is_security_page(html: str) -> bool:
    return any(m in html for m in _SECURITY_MARKERS)


def _cookie_header() -> str:
    if TIEBA_COOKIE:
        return TIEBA_COOKIE
    if not TIEBA_STATE_FILE.is_file():
        return ""
    try:
        state = json.loads(TIEBA_STATE_FILE.read_text(encoding="utf-8"))
        parts = [
            f"{c['name']}={c['value']}"
            for c in state.get("cookies", [])
            if "baidu" in c.get("domain", "")
        ]
        if parts:
            logger.info("已加载贴吧 Cookie %s 项（来自 tieba_state.json）", len(parts))
        return "; ".join(parts)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取贴吧登录态失败: %s", e)
        return ""


def _post_from_thread_obj(item: dict) -> CrawlPost | None:
    tid = item.get("thread_id") or item.get("tid") or item.get("id")
    if not tid:
        return None
    title = (item.get("title") or item.get("thread_name") or "").strip()
    if not title:
        return None
    author = ""
    author_obj = item.get("author")
    if isinstance(author_obj, dict):
        author = author_obj.get("name") or author_obj.get("display_name") or ""
    elif isinstance(author_obj, str):
        author = author_obj
    abstract = (item.get("abstract") or item.get("content") or "").strip()
    content = abstract or f"贴吧主题帖 tid={tid}"
    return CrawlPost(
        id=f"tieba_{tid}",
        platform="tieba",
        title=title,
        content=content,
        author=author,
        publish_time=None,
        url=f"{BASE}/p/{tid}",
    )


def _threads_from_payload(payload: dict) -> list:
    if payload.get("error"):
        logger.warning("贴吧 API 返回错误: %s", payload.get("error"))
        return []
    errno = payload.get("errno")
    if errno is not None and errno != 0:
        return []

    data = payload.get("data") or {}
    threads = data.get("thread_list")
    if isinstance(threads, dict):
        threads = threads.get("thread_list") or threads.get("thread_list")
    if isinstance(threads, list):
        return threads
    return []


def _parse_page_data_json(text: str, limit: int) -> list[CrawlPost]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []

    posts: list[CrawlPost] = []
    for item in _threads_from_payload(payload):
        if not isinstance(item, dict):
            continue
        post = _post_from_thread_obj(item)
        if post:
            posts.append(post)
        if len(posts) >= limit:
            break
    return posts


def _parse_embedded_json(html: str, limit: int) -> list[CrawlPost]:
    """从页面内嵌 JSON（script）提取 thread_list。"""
    posts: list[CrawlPost] = []
    patterns = [
        r'"thread_list"\s*:\s*(\{[\s\S]*?\})\s*[,}]',
        r'"thread_list"\s*:\s*(\[[\s\S]*?\])',
    ]
    for pat in patterns:
        for match in re.finditer(pat, html):
            chunk = match.group(1)
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, list):
                items = obj
            elif isinstance(obj, dict):
                items = obj.get("thread_list") or []
                if isinstance(items, dict):
                    items = items.get("thread_list") or []
            else:
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                post = _post_from_thread_obj(item)
                if post:
                    posts.append(post)
                if len(posts) >= limit:
                    return posts
    return posts


def _parse_vue_links(html: str, limit: int) -> list[CrawlPost]:
    """新版贴吧 PC 页（Vue CSR）：帖子链接为 /p/{tid}。"""
    soup = BeautifulSoup(html, "html.parser")
    posts: list[CrawlPost] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        if len(posts) >= limit:
            break
        href = a.get("href", "")
        m = re.search(r"/p/(\d+)", href)
        if not m:
            continue
        tid = m.group(1)
        if tid in seen:
            continue
        title = a.get_text(strip=True)
        if len(title) < 4:
            continue
        seen.add(tid)
        thread_url = urljoin(BASE, href) if href.startswith("/") else href
        posts.append(
            CrawlPost(
                id=f"tieba_{tid}",
                platform="tieba",
                title=title,
                content=f"贴吧主题帖 tid={tid}",
                author="",
                publish_time=None,
                url=thread_url,
            )
        )
    return posts


def _parse_list_html(html: str, limit: int) -> list[CrawlPost]:
    posts: list[CrawlPost] = []
    soup = BeautifulSoup(html, "html.parser")

    candidates = soup.select("li.j_thread_list")
    if not candidates:
        candidates = soup.select("div.j_thread_list, li[data-tid]")

    for li in candidates:
        if len(posts) >= limit:
            break
        tid = li.get("data-tid") or li.get("data-thread-id")
        if not tid:
            continue
        title_el = li.select_one("a.j_th_tit, a[class*='title']")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        thread_url = urljoin(BASE, href) if href else f"{BASE}/p/{tid}"
        author_el = li.select_one(".frs-author-name, .tb_icon_author")
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


def _from_forum_api(kw: str, limit: int, cookie: str) -> list[CrawlPost]:
    if not cookie:
        return []

    url = f"{BASE}/f/data/data/forum/pageData"
    params = {"ie": "utf-8", "kw": kw, "pn": "1", "rn": str(min(limit, 50))}
    headers = {
        "User-Agent": DESKTOP_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": f"{BASE}/f?kw={quote(kw)}&ie=utf-8",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookie,
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=(15, min(TIEBA_TIMEOUT, 60)))
        resp.raise_for_status()
        posts = _parse_page_data_json(resp.text, limit)
        if posts:
            logger.info("贴吧 API 采集 %s 条 (kw=%s)", len(posts), kw)
        return posts
    except Exception as e:
        logger.warning("贴吧 API 失败 (kw=%s): %s", kw, e)
        return []


def _from_requests(kw: str, limit: int, cookie: str) -> list[CrawlPost]:
    posts = _from_forum_api(kw, limit, cookie)
    if posts:
        return posts

    page_url = f"{BASE}/f?kw={quote(kw)}&ie=utf-8"
    headers = {
        "User-Agent": DESKTOP_UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": f"{BASE}/",
        "Cookie": cookie,
    }
    for attempt in range(1, TIEBA_RETRIES + 1):
        try:
            resp = requests.get(page_url, headers=headers, timeout=(15, min(TIEBA_TIMEOUT, 60)))
            resp.raise_for_status()
            resp.encoding = "utf-8"
            if _is_security_page(resp.text):
                logger.warning("贴吧 HTTP 第 %s 次：安全验证页 (kw=%s)", attempt, kw)
                break
            posts = _parse_list_html(resp.text, limit)
            if posts:
                return posts
        except Exception as e:
            logger.warning("贴吧 HTTP 第 %s 次失败 (kw=%s): %s", attempt, kw, e)
            time.sleep(2)
    return []


def _from_playwright(kw: str, limit: int) -> list[CrawlPost]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("未安装 playwright")
        return []

    if not TIEBA_STATE_FILE.is_file() and not TIEBA_COOKIE:
        logger.info("未找到贴吧登录态，请先运行 save_tieba_login.bat")
        return []

    forum_url = f"{BASE}/f?kw={quote(kw)}&ie=utf-8"
    api_snippets: list[str] = []
    posts: list[CrawlPost] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=CRAWLER_HEADLESS,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context_kwargs = {
                "user_agent": DESKTOP_UA,
                "locale": "zh-CN",
                "viewport": {"width": 1280, "height": 800},
            }
            if TIEBA_STATE_FILE.is_file():
                context_kwargs["storage_state"] = str(TIEBA_STATE_FILE)
            elif TIEBA_COOKIE:
                cookies = []
                for part in TIEBA_COOKIE.split(";"):
                    part = part.strip()
                    if "=" in part:
                        name, value = part.split("=", 1)
                        cookies.append(
                            {
                                "name": name.strip(),
                                "value": value.strip(),
                                "domain": ".baidu.com",
                                "path": "/",
                            }
                        )
                if cookies:
                    context_kwargs["storage_state"] = {"cookies": cookies, "origins": []}

            context = browser.new_context(**context_kwargs)
            page = context.new_page()

            def on_response(response):
                if response.status != 200:
                    return
                url = response.url
                if "pageData" in url or "threadlist" in url or "/f/data/" in url:
                    try:
                        body = response.text()
                        if body and body.strip().startswith("{"):
                            api_snippets.append(body)
                    except Exception:
                        pass

            page.on("response", on_response)
            logger.info("打开贴吧版块: %s", kw)
            try:
                page.goto(forum_url, wait_until="networkidle", timeout=TIEBA_PLAYWRIGHT_TIMEOUT)
            except Exception:
                page.goto(forum_url, wait_until="domcontentloaded", timeout=TIEBA_PLAYWRIGHT_TIMEOUT)
            page.wait_for_timeout(8000)

            for _ in range(3):
                page.evaluate("window.scrollBy(0, 900)")
                page.wait_for_timeout(1200)

            try:
                page.wait_for_selector('a[href*="/p/"]', timeout=20000)
            except Exception:
                pass

            html = page.content()
            p_links = html.count("/p/")
            logger.info(
                "贴吧页面 kw=%s: /p/ 链接约 %s 处, j_thread_list=%s, 安全验证=%s",
                kw,
                p_links,
                html.count("j_thread_list"),
                _is_security_page(html),
            )

            if _is_security_page(html):
                logger.warning(
                    "贴吧仍遇安全验证 (kw=%s)。请 save_tieba_login.bat 在「%s」吧保存登录态，"
                    "并保持 CRAWLER_HEADLESS=false",
                    kw,
                    kw,
                )
            else:
                posts = _merge(posts, _parse_vue_links(html, limit))
                posts = _merge(posts, _parse_list_html(html, limit))
                posts = _merge(posts, _parse_embedded_json(html, limit))

            for snippet in api_snippets:
                posts = _merge(posts, _parse_page_data_json(snippet, limit))
                if len(posts) >= limit:
                    break

            if len(posts) < limit:
                try:
                    raw = page.evaluate(
                        """async (kw) => {
                            const u = '/f/data/data/forum/pageData?ie=utf-8&kw='
                              + encodeURIComponent(kw) + '&pn=1&rn=30';
                            const r = await fetch(u, {
                              credentials: 'include',
                              headers: {'X-Requested-With': 'XMLHttpRequest'}
                            });
                            return await r.text();
                        }""",
                        kw,
                    )
                    if raw:
                        posts = _merge(posts, _parse_page_data_json(raw, limit))
                except Exception as e:
                    logger.debug("贴吧页内 fetch 失败: %s", e)

            browser.close()
    except Exception as e:
        logger.warning("贴吧 Playwright 失败 (kw=%s): %s", kw, e)

    return posts[:limit]


def _keyword_candidates() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for kw in [TIEBA_KW, *TIEBA_KEYWORDS_FALLBACK]:
        if kw and kw not in seen:
            seen.add(kw)
            ordered.append(kw)
    return ordered


def crawl_tieba(kw: str = TIEBA_KW, limit: int = TIEBA_LIMIT) -> list[CrawlPost]:
    cookie = _cookie_header()
    posts: list[CrawlPost] = []

    if not TIEBA_STATE_FILE.is_file() and not TIEBA_COOKIE:
        logger.warning("未配置贴吧登录态，请先运行 save_tieba_login.bat")

    keywords = _keyword_candidates()
    if kw and kw not in keywords:
        keywords.insert(0, kw)

    for forum_kw in keywords:
        if len(posts) >= limit:
            break
        logger.info("使用 Playwright + 登录态采集贴吧 (kw=%s)…", forum_kw)
        posts = _merge(posts, _from_playwright(forum_kw, limit))

        if not TIEBA_SKIP_HTTP and len(posts) < limit and cookie:
            logger.info("Playwright 不足，尝试 HTTP 补充 (kw=%s)…", forum_kw)
            posts = _merge(posts, _from_requests(forum_kw, limit, cookie))

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
