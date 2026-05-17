"""
保存微博登录态（只需做一次）。

用法:
  .venv\\Scripts\\python.exe scripts\\save_weibo_login.py

会打开浏览器 -> 请手动登录微博 -> 回到终端按回车 -> 保存到 data/cookies/weibo_state.json
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.config import COOKIES_DIR, WEIBO_STATE_FILE  # noqa: E402


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装: pip install playwright && playwright install chromium")
        sys.exit(1)

    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    print("即将打开浏览器，请登录 https://m.weibo.cn")
    print("登录成功后回到此窗口按回车保存登录态…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        page.goto("https://m.weibo.cn/login", wait_until="domcontentloaded", timeout=60000)
        input("\n>>> 登录完成后按回车保存: ")
        context.storage_state(path=str(WEIBO_STATE_FILE))
        browser.close()

    print("已保存:", WEIBO_STATE_FILE)
    print("现在可以运行 crawl.bat 进行真实采集")


if __name__ == "__main__":
    main()
