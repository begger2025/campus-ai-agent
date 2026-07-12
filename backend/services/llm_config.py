"""LLM / embedding runtime configuration for the public opinion agent.

Mirrors the subproject's app/config.py LLM section. Reads the main project's
.env (already loaded by backend.database, but load again defensively so these
modules work standalone).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")

load_dotenv(ROOT / ".env", override=False, interpolate=False)


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# 主项目 .env 已有 OPENAI_*；LLM_ENABLED 默认 True（与子项目不同：主项目配了 key 即视为启用）。
LLM_ENABLED = _read_bool("LLM_ENABLED", True)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = _read_int("LLM_TIMEOUT_SECONDS", 45)
LLM_MAX_RETRIES = _read_int("LLM_MAX_RETRIES", 2)
LLM_RETRY_BASE_SECONDS = _read_float("LLM_RETRY_BASE_SECONDS", 0.5)
LLM_CACHE_ENABLED = _read_bool("LLM_CACHE_ENABLED", True)
LLM_CACHE_PATH = Path(os.getenv("LLM_CACHE_PATH") or (DATA_DIR / "llm_cache.json"))

REACT_MAX_STEPS = _read_int("REACT_MAX_STEPS", 5)

EMBEDDING_ENABLED = _read_bool("EMBEDDING_ENABLED", True)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_CLUSTER_THRESHOLD = _read_float("EMBEDDING_CLUSTER_THRESHOLD", 0.6)
EMBEDDING_ALIGN_THRESHOLD = _read_float("EMBEDDING_ALIGN_THRESHOLD", 0.75)

# 成为一个 public_event 至少要有几条帖子。1 = 不压制（单帖也能成事件，旧行为）。
# 默认 2：一条帖子不是"公共事件"，只是一条帖子——公共事件的最低含义是"不止一个人在说"。
EVENT_MIN_CLUSTER_SIZE = max(_read_int("EVENT_MIN_CLUSTER_SIZE", 2), 1)
