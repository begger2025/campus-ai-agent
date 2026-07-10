"""Crawl keyword recommendation planner（智能选题核心算法）.

纯函数、零 IO、零新依赖。四路客观信号融合为一个可解释分数：
  A demand    —— 用户提问频率，3 天半衰期衰减
  B gap       —— 提问后站内检索命中不足的话题加权补给
  C heat      —— 已爬内容在小红书侧的互动热度延续，7 天半衰期
  D discovery —— 笔记标签里冒头、但从未作为关键词爬过的新话题

score(kw) = (0.5·demand_norm + 0.3·min(2·demand_norm, 1) + 0.2·heat_norm) × crawl_penalty × 10
crawl_penalty：14 天内爬过 ×0.3；命中贫瘠集合（爬过但零相关入库）×0.1（强降权，替代而非叠乘）

设计文档：主项目 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


HALF_LIFE_ASK_DAYS = 3.0
HALF_LIFE_CONTENT_DAYS = 7.0
CRAWL_PENALTY = 0.3
BARREN_PENALTY = 0.1
CRAWL_PENALTY_WINDOW_DAYS = 14
GAP_HIT_THRESHOLD = 3
GAP_BOOST = 2.0
W_ASK = 0.5
W_GAP = 0.3
W_HEAT = 0.2
SCORE_SCALE = 10.0
ASK_WINDOW_DAYS = 7
MAX_KEYWORD_LEN = 12

SCHOOL_PREFIXES = ("中山大学", "中大")
# 太宽泛、不适合作为爬取关键词的通用词（含学校名本身与营销标签）。
GENERIC_BLACKLIST = frozenset(
    {
        "中山大学", "中大", "大学", "校园", "学校", "大学生", "学生",
        "大学生活", "校园生活", "日常", "分享", "生活", "推荐", "攻略",
        "vlog", "打卡", "笔记", "干货", "好物",
        "探店", "美食", "穿搭", "ootd", "旅游", "旅行", "景点", "拍照",
        "约拍", "优惠", "团购", "种草", "测评", "集美", "姐妹",
    }
)

# emoji / 图形符号区段（保守清单：不含中文、英文、数字、常规标点）。
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),  # SMP 图形区：表情、交通、麻将、补充符号等
    (0x2600, 0x27BF),    # 杂项符号与装饰符号（☀✅✈ 等）
    (0x2B00, 0x2BFF),    # 杂项符号和箭头（⭐⬆ 等）
    (0xFE00, 0xFE0F),    # 变体选择符（emoji 样式后缀）
    (0x200D, 0x200D),    # 零宽连接符（组合 emoji）
)


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)


def _strip_edge_punct(word: str) -> str:
    """剥离首尾的标点符号（Unicode P 类）与空白，词内字符不动。"""

    start, end = 0, len(word)
    while start < end and (unicodedata.category(word[start]).startswith("P") or word[start].isspace()):
        start += 1
    while end > start and (unicodedata.category(word[end - 1]).startswith("P") or word[end - 1].isspace()):
        end -= 1
    return word[start:end]


@dataclass(slots=True)
class QueryRecord:
    """一次用户提问（来自 chat_query_log）。"""

    keyword: str
    asked_at: datetime
    hit_count: int = 0


@dataclass(slots=True)
class ContentStat:
    """一个词在一条已爬内容上的统计（C 用 source_keyword，D 用笔记标签）。"""

    keyword: str
    engagement: int
    published_at: datetime


@dataclass(slots=True)
class KeywordSuggestion:
    keyword: str
    score: float
    signals: list[str] = field(default_factory=list)
    ask_count_7d: int = 0
    last_asked_at: datetime | None = None
    last_hit_count: int | None = None
    last_crawled_at: datetime | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("last_asked_at", "last_crawled_at"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        data["score"] = round(self.score, 1)
        return data


def normalize_keyword(keyword: str) -> str:
    """归一化候选词：删 emoji、剥首尾标点、剥学校前缀、过滤黑名单/单字/纯数字/超长。返回 "" 表示丢弃。"""

    word = (keyword or "").strip().lower()
    word = "".join(char for char in word if not _is_emoji(char))
    # 先清掉首尾 emoji/标点再剥前缀，否则"🔥中山大学食堂"这类词会让 startswith 失配
    word = _strip_edge_punct(word)
    for prefix in SCHOOL_PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix):
            word = word[len(prefix):]
            break
    # 剥前缀可能暴露新的首部标点（如"中山大学-食堂"→"-食堂"），需再剥一次
    word = _strip_edge_punct(word)
    if len(word) < 2 or word in GENERIC_BLACKLIST or word.isdigit():
        return ""
    if len(word) > MAX_KEYWORD_LEN:
        return ""
    return word


@dataclass(slots=True)
class _Candidate:
    """打分中间态：一个候选词累计的各路信号原始值。"""

    demand: float = 0.0
    ask_total: int = 0
    ask_count_7d: int = 0
    last_asked_at: datetime | None = None
    last_hit_count: int | None = None
    heat_raw: float = 0.0
    content_count: int = 0
    last_crawled_at: datetime | None = None


def _decay(age_days: float, half_life_days: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / half_life_days)


def _age_days(now: datetime, moment: datetime) -> float:
    return (now - moment).total_seconds() / 86400.0


def _build_reason(cand: _Candidate, *, now: datetime, gap: bool, penalized: bool, barren: bool = False) -> str:
    parts: list[str] = []
    if cand.ask_total:
        if cand.ask_count_7d:
            parts.append(f"近7天被问{cand.ask_count_7d}次")
        else:
            parts.append("近期有用户提问")
        if gap:
            parts.append(f"最近一次命中{cand.last_hit_count or 0}条站内数据")
    if cand.heat_raw > 0:
        label = "相关" if cand.last_crawled_at else "带此标签"
        parts.append(f"近期有{cand.content_count}条已爬内容{label}、互动量热")
    if cand.last_crawled_at is not None:
        days = max(int(_age_days(now, cand.last_crawled_at)), 0)
        if barren:
            parts.append(f"{days}天前爬过但无相关内容（已强降权）")
        else:
            parts.append(f"{days}天前爬过（已降权）" if penalized else f"{days}天前爬过")
    elif barren:
        # 贫瘠标记来自爬取历史，即使内容表倒推不出爬取时间也如实说明
        parts.append("近期爬过但无相关内容（已强降权）")
    else:
        parts.append("从未爬取过" if cand.ask_total else "从未作为关键词爬取")
    return "，".join(parts)


def _build_alias_map(keywords: set[str]) -> dict[str, str]:
    """短词并入唯一包含它的长词（"空调"→"宿舍空调"）；多个包含者视为歧义，不合并。"""

    alias: dict[str, str] = {}
    for word in sorted(keywords, key=len):
        containers = [other for other in keywords if other != word and word in other]
        if len(containers) == 1:
            alias[word] = containers[0]
    return alias


def plan_keywords(
    queries: list[QueryRecord],
    content_stats: list[ContentStat],
    crawled_at_by_keyword: dict[str, datetime],
    now: datetime,
    top_n: int = 10,
    barren_keywords: set[str] | None = None,
) -> list[KeywordSuggestion]:
    """四信号融合打分，返回按分数降序的 Top-N 推荐。

    barren_keywords：近期爬过但零相关入库的贫瘠词（原始形态），命中者强降权至 BARREN_PENALTY。
    """

    normalized_queries = [
        (word, query) for query in queries if (word := normalize_keyword(query.keyword))
    ]
    normalized_contents = [
        (word, stat) for stat in content_stats if (word := normalize_keyword(stat.keyword))
    ]
    normalized_crawled: dict[str, datetime] = {}
    for raw_keyword, crawled_at in crawled_at_by_keyword.items():
        word = normalize_keyword(raw_keyword)
        if word and (word not in normalized_crawled or crawled_at > normalized_crawled[word]):
            normalized_crawled[word] = crawled_at

    all_words = {w for w, _ in normalized_queries} | {w for w, _ in normalized_contents}
    alias = _build_alias_map(all_words)

    def canon(word: str) -> str:
        return alias.get(word, word)

    # 贫瘠词与 crawled_at_by_keyword 同口径对账：归一化（丢弃为空者）后再并入合并词
    barren_set = {
        canon(word) for raw in (barren_keywords or set()) if (word := normalize_keyword(raw))
    }

    candidates: dict[str, _Candidate] = {}

    for word, query in normalized_queries:
        cand = candidates.setdefault(canon(word), _Candidate())
        age = _age_days(now, query.asked_at)
        cand.demand += _decay(age, HALF_LIFE_ASK_DAYS)
        cand.ask_total += 1
        if age <= ASK_WINDOW_DAYS:
            cand.ask_count_7d += 1
        if cand.last_asked_at is None or query.asked_at > cand.last_asked_at:
            cand.last_asked_at = query.asked_at
            cand.last_hit_count = query.hit_count

    for word, stat in normalized_contents:
        cand = candidates.setdefault(canon(word), _Candidate())
        age = _age_days(now, stat.published_at)
        cand.heat_raw += math.log10(1 + max(stat.engagement, 0)) * _decay(age, HALF_LIFE_CONTENT_DAYS)
        cand.content_count += 1

    for word, crawled_at in normalized_crawled.items():
        word = canon(word)
        if word not in candidates:
            continue
        cand = candidates[word]
        if cand.last_crawled_at is None or crawled_at > cand.last_crawled_at:
            cand.last_crawled_at = crawled_at

    max_demand = max((c.demand for c in candidates.values()), default=0.0)
    max_heat = max((c.heat_raw for c in candidates.values()), default=0.0)

    suggestions: list[KeywordSuggestion] = []
    for word, cand in candidates.items():
        demand_norm = cand.demand / max_demand if max_demand else 0.0
        heat_norm = cand.heat_raw / max_heat if max_heat else 0.0
        gap = cand.ask_total > 0 and (cand.last_hit_count or 0) < GAP_HIT_THRESHOLD
        gap_norm = min(demand_norm * GAP_BOOST, 1.0) if gap else 0.0
        penalized = (
            cand.last_crawled_at is not None
            and _age_days(now, cand.last_crawled_at) < CRAWL_PENALTY_WINDOW_DAYS
        )
        barren = word in barren_set
        # 贫瘠词强降权替代常规降权（不叠乘）
        penalty = BARREN_PENALTY if barren else (CRAWL_PENALTY if penalized else 1.0)
        score = (W_ASK * demand_norm + W_GAP * gap_norm + W_HEAT * heat_norm) * penalty * SCORE_SCALE
        if score <= 0:
            continue
        signals: list[str] = []
        if cand.ask_total:
            signals.append("demand")
        if gap:
            signals.append("gap")
        if cand.heat_raw > 0:
            signals.append("heat" if cand.last_crawled_at else "discovery")
        suggestions.append(
            KeywordSuggestion(
                keyword=word,
                score=score,
                signals=signals,
                ask_count_7d=cand.ask_count_7d,
                last_asked_at=cand.last_asked_at,
                last_hit_count=cand.last_hit_count,
                last_crawled_at=cand.last_crawled_at,
                reason=_build_reason(cand, now=now, gap=gap, penalized=penalized, barren=barren),
            )
        )

    suggestions.sort(key=lambda s: (-s.score, s.keyword))
    return suggestions[:top_n]
