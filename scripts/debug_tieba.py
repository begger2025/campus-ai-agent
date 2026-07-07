"""Debug tieba Playwright responses. Run: .venv\\Scripts\\python.exe scripts\\debug_tieba.py"""
import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import TIEBA_KW, TIEBA_STATE_FILE, DESKTOP_UA  # noqa: E402

def main():
    from playwright.sync_api import sync_playwright

    kw = TIEBA_KW
    url = f"https://tieba.baidu.com/f?kw={quote(kw)}&ie=utf-8"
    hits = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(TIEBA_STATE_FILE), user_agent=DESKTOP_UA)
        page = ctx.new_page()

        def on_response(resp):
            u = resp.url
            if resp.status != 200:
                return
            if any(x in u for x in ("tieba", "baidu")) and ("json" in u or "data" in u or "api" in u):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct or u.endswith(".json") or "/data/" in u:
                        body = resp.text()[:500]
                        hits.append((u[:120], body[:200]))
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(8000)
        html = page.content()
        browser.close()

    print("API hits:", len(hits))
    for u, b in hits[:15]:
        print("---", u)
        print(b)
    print("html len", len(html), "j_thread", html.count("j_thread"), "href /p/", html.count("/p/"))


if __name__ == "__main__":
    main()
