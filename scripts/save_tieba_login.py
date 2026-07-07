"""
保存百度贴吧登录态（只需做一次）。

用法:
  save_tieba_login.bat

登录后会在目标贴吧版块停留，再按回车保存。
"""

import sys
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import COOKIES_DIR, TIEBA_KW, TIEBA_STATE_FILE  # noqa: E402

FORUM_URL = f"https://tieba.baidu.com/f?kw={quote(TIEBA_KW)}&ie=utf-8"


def _on_forum_page(url: str, kw: str) -> bool:
    u = unquote(url)
    return "/f?" in u and (kw in u or quote(kw) in url)


def _open_forum_page(page, forum_url: str, kw: str) -> None:
    """打开贴吧版块；贴吧常会重定向，需容错。"""
    last_err = None
    for attempt in range(1, 4):
        try:
            page.goto(forum_url, wait_until="domcontentloaded", timeout=90000)
            last_err = None
            break
        except Exception as e:
            last_err = e
            msg = str(e)
            if "interrupted" not in msg.lower():
                raise
            page.wait_for_timeout(2000)

    if last_err:
        print("\n提示: 贴吧自动跳转被重定向打断，改用页面内跳转…")
        page.evaluate("(url) => { window.location.href = url; }", forum_url)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=90000)
        except Exception:
            pass
        page.wait_for_timeout(4000)

    if _on_forum_page(page.url, kw):
        return

    print("\n未能自动进入目标贴吧，请你在浏览器里手动操作：")
    print(f"  地址栏打开: {forum_url}")
    print("  或搜索进入贴吧「" + kw + "」")
    input("  看到帖子列表后，回到此窗口按回车继续… ")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装: pip install playwright && playwright install chromium")
        sys.exit(1)

    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    print("即将打开浏览器")
    print("1) 登录百度账号")
    print(f"2) 打开贴吧版块: {TIEBA_KW}")
    print(f"   {FORUM_URL}")
    print("3) 确认能看到帖子列表后，回到此窗口按回车保存")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto("https://tieba.baidu.com", wait_until="domcontentloaded", timeout=90000)
        input("\n>>> 若未登录请先登录，完成后按回车继续: ")

        _open_forum_page(page, FORUM_URL, TIEBA_KW)
        page.wait_for_timeout(2000)
        print(f"\n当前页面: {page.url}")
        print("请确认页面上有帖子列表（不是安全验证页）")
        input(">>> 确认无误后按回车保存登录态: ")
        context.storage_state(path=str(TIEBA_STATE_FILE))
        browser.close()

    print("已保存:", TIEBA_STATE_FILE)
    print("然后运行 crawl.bat 采集数据")


if __name__ == "__main__":
    main()
