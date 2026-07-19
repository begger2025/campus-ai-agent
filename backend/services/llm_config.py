"""LLM / embedding runtime configuration for the public opinion agent.

Mirrors the subproject's app/config.py LLM section. Reads the main project's
.env (already loaded by backend.database, but load again defensively so these
modules work standalone).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from backend.agent.public_opinion_core.concurrency import DEFAULT_LLM_CONCURRENCY
from backend.agent.public_opinion_core.llm_keywords import (
    DEFAULT_MAX_KEYWORDS_PER_EVENT,
    DEFAULT_TOP_EVENTS,
)
from backend.agent.public_opinion_core.llm_refine import (
    DEFAULT_REFINE_MAX_MEMBERS,
    DEFAULT_REFINE_MIN_SIZE,
)
from backend.agent.public_opinion_core.llm_risk import DEFAULT_MAX_TEXTS as DEFAULT_RISK_MAX_TEXTS
from backend.agent.public_opinion_core.semantic_clustering import (
    DEFAULT_MAX_SPAN_DAYS,
    DEFAULT_MERGE_THRESHOLD,
    MAX_SPAN_DAYS_ENV,
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

# ---- LLM 备胎端点（主通道失败自动切换，优先顺序 = OPENAI_* → LLM_FALLBACK_*） ----
# 三项配齐才启用（model + base_url + key）；与主通道配置完全相同则视为未配置。
# 切换发生在 llm_client.call_llm 内部：中转站（gpt-5.4）拥堵/欠费/超时耗尽重试后，
# 自动改打备胎（如智谱 GLM 直连 https://open.bigmodel.cn/api/paas/v4）。
# API key 缺省复用 EVIDENCE_GLM_API_KEY——项目里 GLM 只有一把 key，不重复粘贴。
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
LLM_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "")
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY") or os.getenv("EVIDENCE_GLM_API_KEY", "")

REACT_MAX_STEPS = _read_int("REACT_MAX_STEPS", 5)

EMBEDDING_ENABLED = _read_bool("EMBEDDING_ENABLED", True)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_CLUSTER_THRESHOLD = _read_float("EMBEDDING_CLUSTER_THRESHOLD", 0.6)
EMBEDDING_ALIGN_THRESHOLD = _read_float("EMBEDDING_ALIGN_THRESHOLD", 0.75)

# 贪心聚类之后的**质心合并**阈值：两个簇的质心相似度 ≥ 它就合成一个事件。
# 单趟贪心没有回头路，同一个话题会按输入顺序裂成好几个簇（真实数据上出现过 4 个
# 「宿舍相关讨论」并列）。合并 pass 负责把它们缝回去；1.0 = 关闭合并。
EMBEDDING_MERGE_THRESHOLD = _read_float(MERGE_THRESHOLD_ENV, DEFAULT_MERGE_THRESHOLD)

# 一个事件的成员帖时间跨度上限（天）。0 = 关闭（消融基线 / 答辩现场开关）。
#
# embedding 只问"像不像"，不问"是不是同一时候发生的"。真实事故：一条 **2021 年**的
# 「东校区封闭管理」（疫情封校，热度 9839）被聚进 2026 年的「东校区宿舍搬迁」，
# 跨度 1782 天——而它一条就贡献了该事件 **90% 的热度**，那个热度数字是假的。
# 「作息调整争议」同病，跨度 1666 天。全库 23% 的帖子是 2024 年以前的，这不是孤例。
#
# 详见 semantic_clustering.DEFAULT_MAX_SPAN_DAYS 的论证（为什么是 90 天、为什么用算术）。
EVENT_MAX_SPAN_DAYS = _read_float(MAX_SPAN_DAYS_ENV, DEFAULT_MAX_SPAN_DAYS)

# ---- 舆情助手的语义检索（字面检索的天花板补丁）----
#
# 用户问「东校宿舍搬迁」，库里的事件叫「东校**区**宿舍搬迁」——差一个字，
# `LIKE '%东校宿舍搬迁%'` 就整个匹配不上（标题/摘要/5 条代表帖没有一个含这个连续子串），
# 用户拿到"未检索到相关事件数据"。中文的同一件事有无数种说法，LIKE 只认连续子串。
#
# 只在**字面颗粒无收**时补位（见 event_read_model.query_published_events 的论证：
# 实测「学术不端」的语义最高分是错的事件，而字面能正确命中——语义是"认得出改写"，
# 不是"比字面更准"）。关掉即回到纯字面检索。
EVENT_SEMANTIC_MATCH_ENABLED = _read_bool("EVENT_SEMANTIC_MATCH_ENABLED", True)

# 余弦阈值 0.65，在**当前 10 个已发布事件**的真实标题上标定（BAAI/bge-small-zh）。
#
# 该命中的（改写）                      该拒绝的（库里没有对应事件）
#   东校宿舍搬迁 → 东校区宿舍搬迁  0.98     宿舍热水 → 宿舍火情通报  0.56  ← 拒绝里最高
#   东校区换宿舍 → 东校区宿舍搬迁  0.88     宿舍热水之外全 ≤ 0.45
#   举报副院长   → 耿同学举报副院长 0.84     考研    → 康某论文调查  0.45
#   搬宿舍      → 东校区宿舍搬迁  0.81     食堂    → 东校区宿舍搬迁 0.43
#   课间时间缩短 → 中大课间缩短争议 0.76     图书馆   → 东校区宿舍搬迁 0.39
#   宿舍火灾    → 中大宿舍火情通报  0.70     天气    → 宿舍火情通报  0.32
#   宿舍着火/起火 → 中大宿舍火情通报 0.67
#   论文造假    → 中大康某论文调查  0.54  ← **漏网**
#
# **诚实的结论：没有一个干净的阈值。** 该命中的最低分（论文造假 0.54）比该拒绝的最高分
# （宿舍热水 0.56）还低——单靠阈值分不开这两个。0.65 是权衡出来的最优点：
#     命中 8/9，正确拒绝 5/5。唯一漏的是「论文造假」。
# 失败方向选对了：**宁可返回空、让它回落帖子层，也不要把「宿舍热水」的提问答成一份火情简报。**
#
# （原来定 0.70 会漏掉 4/9——「宿舍着火」「宿舍起火」都被挡在门外，而库里明明有火情事件。）
EVENT_SEMANTIC_MATCH_THRESHOLD = _read_float("EVENT_SEMANTIC_MATCH_THRESHOLD", 0.65)

# ---- LLM 裁决：只判算术拿不准的那条模糊带 ----
#
# 上面那句"没有干净的阈值"不是缺陷描述，是一个**信号**：这件事不是"可测量"的。
# 余弦回答「有多像」（标量），而用户真正问的是「**是不是**这件事」（判断）。
# 「宿舍热水」和「宿舍火情」很像但不是一回事；「论文造假」和「康某论文调查」
# 一点不像却就是一回事——余弦分不开，因为它没有"是不是"的概念。
#
#     余弦 ≥ 0.65   -> 直接采纳   （标定集里 8/8 全对，不花钱）
#     余弦 <  0.45  -> 直接拒绝   （标定集里 3/3 全对：天气 0.32 / 图书馆 0.39 / 食堂 0.43）
#     0.45 ~ 0.65   -> **LLM 裁决**（3/14 落这儿：考研 0.45、论文造假 0.54、宿舍热水 0.56）
#
# 这就是「可测量的用算术，需要判断的用 AI」的递归应用——AI 只被叫来判算术束手无策的那三个。
EVENT_SEMANTIC_LOW_THRESHOLD = _read_float("EVENT_SEMANTIC_LOW_THRESHOLD", 0.45)

# 关掉即回到纯余弦（消融基线：13/14 -> 开启后 14/14）。
EVENT_JUDGE_ENABLED = _read_bool("EVENT_JUDGE_ENABLED", True)

# 裁决模型。14 条评测集实测（10 个真实事件标题）：
#     glm-4-plus    14/14   0.8s   ← 默认
#     glm-4-air     14/14   1.1s
#     glm-4-flashx  13/14   0.6s   ← 便宜的 flash 在「论文造假」上和余弦犯同一个错
#     glm-4-flash   13/14   1.3s   ← 同上
#     gpt-5.4       14/14   3.6s   （事件研判用的那个，杀鸡用牛刀）
#     gpt-4o-mini   不可用（InternalServerError）
# **省钱省不出判断力**：flash 系列快且便宜，但在唯一需要判断的那个 case 上，
# 它们和余弦一起翻了车。裁决层的全部价值就在那个 case 上，所以不能省这一档。
#
# 缺省复用证据采集那套智谱配置（.env 里已有 EVIDENCE_GLM_API_KEY / EVIDENCE_GLM_MODEL）。
# 注意 base_url：证据采集用的是 /web_search 独立端点，对话要用 OpenAI 兼容的 /v4。
EVENT_JUDGE_MODEL = os.getenv("EVENT_JUDGE_MODEL") or os.getenv("EVIDENCE_GLM_MODEL") or "glm-4-plus"
EVENT_JUDGE_BASE_URL = (
    os.getenv("EVENT_JUDGE_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4"
)
EVENT_JUDGE_API_KEY = (
    os.getenv("EVENT_JUDGE_API_KEY") or os.getenv("EVIDENCE_GLM_API_KEY") or OPENAI_API_KEY
)

# 成为一个 public_event 至少要有几条帖子。1 = 不压制（单帖也能成事件，旧行为）。
# 默认 2：一条帖子不是"公共事件"，只是一条帖子——公共事件的最低含义是"不止一个人在说"。
EVENT_MIN_CLUSTER_SIZE = max(_read_int("EVENT_MIN_CLUSTER_SIZE", 2), 1)

# ---- 事件聚类的 LLM 精修（拆开 embedding 误合并的大桶 + 具体化标题）----
# 单独的端点配置：精修要的是"读得懂中文校园语境"的强模型，和别处的用途未必同一个。
# 缺省回落到 OPENAI_*（当前 .env 里两者相同）。
EVENT_LLM_MODEL = os.getenv("EVENT_LLM_MODEL") or OPENAI_MODEL
EVENT_LLM_BASE_URL = os.getenv("EVENT_LLM_BASE_URL") or OPENAI_BASE_URL
EVENT_LLM_API_KEY = os.getenv("EVENT_LLM_API_KEY") or OPENAI_API_KEY

# 事件流水线里 per-event / per-cluster 的 LLM 调用（聚类精修 / 风险研判 / 状态研判）的并发度。
#
# **被修的缺陷**：这三处以前是串行的 for 循环——37 个事件 × 2 + N 个簇 ≈ 90+ 次调用，
# 单次实测 4~7 秒，`scripts/generate_public_events.py` 于是要跑 7~8 分钟。而这些调用**互不
# 依赖**（判「宿舍火灾有多严重」不需要先知道「食堂涨价」判成了什么），几乎全是在等网络。
#
# 8 = 默认（见 core/concurrency.py 的取值论证）：37 ÷ 8 ≈ 5 轮 ≈ 25 秒。
# 端点限流严（429）就调小；**1 = 退回串行**，且逐位等价于改造前的行为（消融的对照臂）。
# 并发只改「跑得多快」，不改「跑出什么」：结果按输入顺序回填，与串行版逐位一致。
EVENT_LLM_CONCURRENCY = max(_read_int("EVENT_LLM_CONCURRENCY", DEFAULT_LLM_CONCURRENCY), 1)

# 关掉即回到纯 embedding 聚类（答辩现场断网/欠费时的开关；不关也会自动降级，见 llm_refine）。
EVENT_REFINE_ENABLED = _read_bool("EVENT_REFINE_ENABLED", True)

# 多大的簇才值得一次 LLM 调用。默认 8，理由（真实簇大小分布 + 拆分的算术下界）见 llm_refine.py。
EVENT_REFINE_MIN_SIZE = max(_read_int("EVENT_REFINE_MIN_SIZE", DEFAULT_REFINE_MIN_SIZE), 2)

# 多大的簇就不再送精修（防超长 prompt）。默认 150；巨桶最需要精修却最容易撞上限——
# 第 6 轮微博入库后 182 帖巨簇被跳过（实测），部署侧按语料规模放宽。下限钳在 MIN_SIZE，
# 倒挂配置（max < min）没有意义。
EVENT_REFINE_MAX_MEMBERS = max(
    _read_int("EVENT_REFINE_MAX_MEMBERS", DEFAULT_REFINE_MAX_MEMBERS),
    EVENT_REFINE_MIN_SIZE,
)

# 近重簇合并裁决（灰区相似度的簇对交 LLM 判"是不是同一件事"，见 core/llm_merge.py）。
# 关掉即回到"只拆不合"的老行为；候选筛选（灰区/时间兼容/对数封顶）与失败方向在核心包。
EVENT_MERGE_ENABLED = _read_bool("EVENT_MERGE_ENABLED", True)

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
