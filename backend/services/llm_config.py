"""LLM / embedding runtime configuration for the public opinion agent.

Mirrors the subproject's app/config.py LLM section. Reads the main project's
.env (already loaded by backend.database, but load again defensively so these
modules work standalone).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from backend.agent.public_opinion_core.llm_keywords import (
    DEFAULT_MAX_KEYWORDS_PER_EVENT,
    DEFAULT_TOP_EVENTS,
)
from backend.agent.public_opinion_core.llm_refine import DEFAULT_REFINE_MIN_SIZE
from backend.agent.public_opinion_core.llm_risk import DEFAULT_MAX_TEXTS as DEFAULT_RISK_MAX_TEXTS
from backend.agent.public_opinion_core.semantic_clustering import (
    DEFAULT_MERGE_THRESHOLD,
    MERGE_THRESHOLD_ENV,
)


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
# openai SDK 底层是 httpx，而 httpx 默认 trust_env=True：在 Windows 上它不只读
# HTTP_PROXY/HTTPS_PROXY，还会读**注册表里的系统代理**（Clash 一类工具会写这里），
# 所以清空环境变量对它无效。实测同一次智谱调用：走系统代理 14.4s，直连 4.5s（慢 3 倍）。
# 默认直连；确实需要走代理才能上网的人显式设 true。
# 语义与 evidence/config.py::http_trust_env 保持一致（那边同一个坑曾把可达的
# sysu.edu.cn 判成 ConnectTimeout，真证据被当成"编造的链接"）。
LLM_HTTP_TRUST_ENV = _read_bool("LLM_HTTP_TRUST_ENV", False)

REACT_MAX_STEPS = _read_int("REACT_MAX_STEPS", 5)

EMBEDDING_ENABLED = _read_bool("EMBEDDING_ENABLED", True)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_CLUSTER_THRESHOLD = _read_float("EMBEDDING_CLUSTER_THRESHOLD", 0.6)
EMBEDDING_ALIGN_THRESHOLD = _read_float("EMBEDDING_ALIGN_THRESHOLD", 0.75)

# 贪心聚类之后的**质心合并**阈值：两个簇的质心相似度 ≥ 它就合成一个事件。
# 单趟贪心没有回头路，同一个话题会按输入顺序裂成好几个簇（真实数据上出现过 4 个
# 「宿舍相关讨论」并列）。合并 pass 负责把它们缝回去；1.0 = 关闭合并。
EMBEDDING_MERGE_THRESHOLD = _read_float(MERGE_THRESHOLD_ENV, DEFAULT_MERGE_THRESHOLD)

# 成为一个 public_event 至少要有几条帖子。1 = 不压制（单帖也能成事件，旧行为）。
# 默认 2：一条帖子不是"公共事件"，只是一条帖子——公共事件的最低含义是"不止一个人在说"。
EVENT_MIN_CLUSTER_SIZE = max(_read_int("EVENT_MIN_CLUSTER_SIZE", 2), 1)

# ---- 事件聚类的 LLM 精修（拆开 embedding 误合并的大桶 + 具体化标题）----
# 单独的端点配置：精修要的是"读得懂中文校园语境"的强模型，和别处的用途未必同一个。
# 缺省回落到 OPENAI_*（当前 .env 里两者相同）。
EVENT_LLM_MODEL = os.getenv("EVENT_LLM_MODEL") or OPENAI_MODEL
EVENT_LLM_BASE_URL = os.getenv("EVENT_LLM_BASE_URL") or OPENAI_BASE_URL
EVENT_LLM_API_KEY = os.getenv("EVENT_LLM_API_KEY") or OPENAI_API_KEY

# 关掉即回到纯 embedding 聚类（答辩现场断网/欠费时的开关；不关也会自动降级，见 llm_refine）。
EVENT_REFINE_ENABLED = _read_bool("EVENT_REFINE_ENABLED", True)

# 多大的簇才值得一次 LLM 调用。默认 8，理由（真实簇大小分布 + 拆分的算术下界）见 llm_refine.py。
EVENT_REFINE_MIN_SIZE = max(_read_int("EVENT_REFINE_MIN_SIZE", DEFAULT_REFINE_MIN_SIZE), 2)

# ---- 事件级 LLM 风险研判（严重性与热度解耦）----
# 复用同一组 EVENT_LLM_*（同一个"读得懂中文校园语境"的强模型）。
# 关掉即回到规则风险（六个电诈词 + 互动量加分，见 llm_risk.py 的缺陷说明）；
# 不关也会自动逐事件降级——LLM 挂了事件照出，只是风险退回规则值。
EVENT_RISK_ENABLED = _read_bool("EVENT_RISK_ENABLED", True)

# 一个事件最多送几条帖子给模型（严重性藏在少数几条帖子里，读完 91 条纯属烧钱）。
EVENT_RISK_MAX_TEXTS = max(_read_int("EVENT_RISK_MAX_TEXTS", DEFAULT_RISK_MAX_TEXTS), 1)

# ---- 事件状态研判（生命周期：这件事完了没有）----
# 复用同一组 EVENT_LLM_*，也复用 EVENT_RISK_MAX_TEXTS（读的是同一批成员帖，只是问题不同）。
# 关掉即回到"未研判"：生命周期因子恒为 1.0，排序逐位退化回「严重性 × 时效性」（改造前）。
# 不关也会自动逐事件降级——LLM 挂了事件照出，只是那个事件不带状态（见 llm_lifecycle.py）。
EVENT_LIFECYCLE_ENABLED = _read_bool("EVENT_LIFECYCLE_ENABLED", True)

# ---- 从事件生成爬取关键词（智能选题的 LLM 那一半）----
# 复用同一组 EVENT_LLM_*。关掉即回到"用户提问 + 内容标签 + 事件标签"三路——**算术那一半
# 照常工作**（事件仍然进候选池、仍然按 severity×recency×lifecycle 加权），只是提不出
# 「学术不端」这种从未在语料里出现过的词（见 llm_keywords.py 顶部的论证）。
# 不关也会自动逐事件降级：一个事件的词生成失败，别的事件照常。
EVENT_KEYWORDS_ENABLED = _read_bool("EVENT_KEYWORDS_ENABLED", True)

# 只给**算术已经说它重要**的前 N 个事件花 LLM 的钱（按 event_priority 降序）。
EVENT_KEYWORD_TOP_EVENTS = max(_read_int("EVENT_KEYWORD_TOP_EVENTS", DEFAULT_TOP_EVENTS), 0)

# 一个事件最多贡献几个生成词（再多就是同义词灌水，只会挤掉用户的真实提问）。
EVENT_KEYWORD_MAX = max(
    _read_int("EVENT_KEYWORD_MAX", DEFAULT_MAX_KEYWORDS_PER_EVENT), 1
)
