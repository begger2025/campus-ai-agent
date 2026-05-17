import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SAMPLES_DIR = ROOT / "data" / "samples"
COOKIES_DIR = ROOT / "data" / "cookies"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
COOKIES_DIR.mkdir(parents=True, exist_ok=True)

WEIBO_KEYWORD = os.getenv("WEIBO_KEYWORD", "校园")
WEIBO_LIMIT = 30
TIEBA_KW = os.getenv("TIEBA_KEYWORD", "大学生活")
TIEBA_LIMIT = 25

TARGET_MIN = 20
TARGET_MAX = 50

REQUEST_TIMEOUT = int(os.getenv("CRAWLER_REQUEST_TIMEOUT", "20"))
TIEBA_TIMEOUT = int(os.getenv("TIEBA_TIMEOUT", "60"))
TIEBA_RETRIES = int(os.getenv("TIEBA_RETRIES", "3"))

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
USER_AGENT = os.getenv("CRAWLER_USER_AGENT", MOBILE_UA)

WEIBO_COOKIE = os.getenv("WEIBO_COOKIE", "").strip()
WEIBO_STATE_FILE = COOKIES_DIR / "weibo_state.json"
CRAWLER_HEADLESS = os.getenv("CRAWLER_HEADLESS", "true").lower() in ("1", "true", "yes")
