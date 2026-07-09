# 智能选题（爬取关键词推荐）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于四路客观信号（用户需求 A / 供给缺口 B / 小红书热度延续 C / 新话题发现 D）的规则打分管线，自动推荐下一轮爬取关键词，在管理端「智能选题」面板呈现。

**Architecture:** 算法核心 `keyword_planner.py` 是纯函数（零 IO、零新依赖），在子项目 campus-opinion-agent TDD 开发，经 `scripts/sync_opinion_core.py` 单向同步进主项目 `backend/agent/public_opinion_core/`。主项目负责：新表 `chat_query_log`（对话端点成功路径非阻塞落库）、聚合 adapter、`GET /api/admin/keyword-suggestions`、前端「智能选题」页、两个开发期自举脚本。

**Tech Stack:** Python 3.11 dataclasses + unittest（零网络测试）、FastAPI + SQLAlchemy、Vue3 + Element Plus。设计文档：`docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md`。

**两个仓库的路径与命令约定**（下文简称 SUB / MAIN）：

| | 路径 | 测试命令（在仓库根执行） |
|---|---|---|
| SUB | `D:\桌面文件\软件工程大作业\campus-opinion-agent` | `cd backend` 后 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v` |
| MAIN | `D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main` | `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.<模块名> -v` |

全量回归：SUB `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s tests -q`（现有 260 个测试 ~0.6s）；MAIN `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s backend/tests -t . -q`（现有 68 个 ~4s）。

**打分公式（来自已批准设计，subscore 全部归一化到 0–1 后 ×10 展示）：**

```
score(kw) = (0.5·demand_norm + 0.3·gap_norm + 0.2·heat_norm) × crawl_penalty × 10
demand      = Σ 每次提问 0.5^(距今天数/3)；demand_norm = demand / max(demand)
gap_norm    = demand_norm × 2（该词最近一次提问命中 < 3 条时），否则 0
heat        = Σ log10(1+互动量) × 0.5^(距发布天数/7)；heat_norm = heat / max(heat)
crawl_penalty = 14 天内爬过 ? 0.3 : 1.0
```

---

## Task 1（SUB）：planner 数据结构 + 关键词归一化

**Files:**
- Create: `backend/app/public_opinion_core/keyword_planner.py`
- Test: `backend/tests/test_keyword_planner.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_keyword_planner.py`：

```python
from __future__ import annotations

import unittest
from datetime import datetime

from app.public_opinion_core.keyword_planner import (
    ContentStat,
    KeywordSuggestion,
    QueryRecord,
    normalize_keyword,
)


NOW = datetime(2026, 7, 10, 12, 0, 0)


class NormalizeKeywordTest(unittest.TestCase):
    def test_strips_whitespace_and_school_prefix(self) -> None:
        self.assertEqual(normalize_keyword("  中山大学食堂 "), "食堂")
        self.assertEqual(normalize_keyword("中大宿舍"), "宿舍")

    def test_school_name_alone_is_filtered(self) -> None:
        self.assertEqual(normalize_keyword("中山大学"), "")
        self.assertEqual(normalize_keyword("中大"), "")

    def test_generic_blacklist_and_short_words_filtered(self) -> None:
        self.assertEqual(normalize_keyword("大学生活"), "")
        self.assertEqual(normalize_keyword("校园"), "")
        self.assertEqual(normalize_keyword("水"), "")   # 单字
        self.assertEqual(normalize_keyword("2026"), "")  # 纯数字
        self.assertEqual(normalize_keyword(""), "")

    def test_normal_keyword_passes_through(self) -> None:
        self.assertEqual(normalize_keyword("宿舍空调"), "宿舍空调")


class DataclassTest(unittest.TestCase):
    def test_suggestion_to_dict_serializes_datetimes(self) -> None:
        suggestion = KeywordSuggestion(
            keyword="宿舍空调",
            score=9.14159,
            signals=["demand", "gap"],
            ask_count_7d=5,
            last_asked_at=NOW,
            last_hit_count=0,
            last_crawled_at=None,
            reason="近7天被问5次",
        )
        data = suggestion.to_dict()
        self.assertEqual(data["score"], 9.1)
        self.assertEqual(data["last_asked_at"], "2026-07-10T12:00:00")
        self.assertIsNone(data["last_crawled_at"])
        self.assertEqual(data["signals"], ["demand", "gap"])

    def test_record_dataclasses_construct(self) -> None:
        QueryRecord(keyword="食堂", asked_at=NOW, hit_count=2)
        ContentStat(keyword="期末周", engagement=120, published_at=NOW)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v
```
预期：`ModuleNotFoundError: No module named 'app.public_opinion_core.keyword_planner'`。

- [ ] **Step 3: 最小实现**

创建 `backend/app/public_opinion_core/keyword_planner.py`：

```python
"""Crawl keyword recommendation planner（智能选题核心算法）.

纯函数、零 IO、零新依赖。四路客观信号融合为一个可解释分数：
  A demand    —— 用户提问频率，3 天半衰期衰减
  B gap       —— 提问后站内检索命中不足的话题加权补给
  C heat      —— 已爬内容在小红书侧的互动热度延续，7 天半衰期
  D discovery —— 笔记标签里冒头、但从未作为关键词爬过的新话题

score(kw) = (0.5·demand_norm + 0.3·gap_norm + 0.2·heat_norm) × crawl_penalty × 10

设计文档：主项目 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


HALF_LIFE_ASK_DAYS = 3.0
HALF_LIFE_CONTENT_DAYS = 7.0
CRAWL_PENALTY = 0.3
CRAWL_PENALTY_WINDOW_DAYS = 14
GAP_HIT_THRESHOLD = 3
GAP_BOOST = 2.0
W_ASK = 0.5
W_GAP = 0.3
W_HEAT = 0.2
SCORE_SCALE = 10.0
ASK_WINDOW_DAYS = 7

SCHOOL_PREFIXES = ("中山大学", "中大")
# 太宽泛、不适合作为爬取关键词的通用词（含学校名本身）。
GENERIC_BLACKLIST = frozenset(
    {
        "中山大学", "中大", "大学", "校园", "学校", "大学生", "学生",
        "大学生活", "校园生活", "日常", "分享", "生活", "推荐", "攻略",
        "vlog", "打卡", "笔记", "干货", "好物",
    }
)


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

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("last_asked_at", "last_crawled_at"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        data["score"] = round(self.score, 1)
        return data


def normalize_keyword(keyword: str) -> str:
    """归一化候选词：去空白、剥学校前缀、过滤黑名单/单字/纯数字。返回 "" 表示丢弃。"""

    word = (keyword or "").strip().lower()
    for prefix in SCHOOL_PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix):
            word = word[len(prefix):].strip()
            break
    if len(word) < 2 or word in GENERIC_BLACKLIST or word.isdigit():
        return ""
    return word
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（6 个测试）。

- [ ] **Step 5: 提交（SUB 仓库）**

```bash
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent"
git add backend/app/public_opinion_core/keyword_planner.py backend/tests/test_keyword_planner.py
git commit -m "feat(keyword-planner): 数据结构与关键词归一化"
```

---

## Task 2（SUB）：需求分 + 缺口加权（plan_keywords 只吃提问信号）

**Files:**
- Modify: `backend/app/public_opinion_core/keyword_planner.py`
- Test: `backend/tests/test_keyword_planner.py`

- [ ] **Step 1: 写失败测试**

在 `test_keyword_planner.py` 追加（同时在文件顶部 import 处加入 `plan_keywords` 和 `timedelta`）：

```python
from datetime import datetime, timedelta

from app.public_opinion_core.keyword_planner import (
    ContentStat,
    KeywordSuggestion,
    QueryRecord,
    normalize_keyword,
    plan_keywords,
)


def _ask(keyword: str, days_ago: float, hit_count: int = 0) -> QueryRecord:
    return QueryRecord(keyword=keyword, asked_at=NOW - timedelta(days=days_ago), hit_count=hit_count)


class DemandSignalTest(unittest.TestCase):
    def test_more_recent_asks_rank_higher(self) -> None:
        queries = [_ask("宿舍空调", 0.5), _ask("食堂涨价", 6.5)]
        result = plan_keywords(queries, [], {}, now=NOW)
        self.assertEqual([s.keyword for s in result], ["宿舍空调", "食堂涨价"])
        self.assertGreater(result[0].score, result[1].score)

    def test_ask_counts_accumulate(self) -> None:
        queries = [_ask("宿舍空调", 1), _ask("宿舍空调", 2), _ask("食堂涨价", 1)]
        result = plan_keywords(queries, [], {}, now=NOW)
        self.assertEqual(result[0].keyword, "宿舍空调")
        self.assertEqual(result[0].ask_count_7d, 2)
        self.assertEqual(result[1].ask_count_7d, 1)

    def test_gap_boost_applies_when_recent_hits_low(self) -> None:
        # 同样各被问 1 次；缺口词（命中0）必须高于已有数据的词（命中5）
        queries = [_ask("宿舍空调", 1, hit_count=0), _ask("食堂涨价", 1, hit_count=5)]
        result = plan_keywords(queries, [], {}, now=NOW)
        by_kw = {s.keyword: s for s in result}
        self.assertGreater(by_kw["宿舍空调"].score, by_kw["食堂涨价"].score)
        self.assertIn("gap", by_kw["宿舍空调"].signals)
        self.assertNotIn("gap", by_kw["食堂涨价"].signals)

    def test_gap_uses_latest_hit_count(self) -> None:
        # 早先命中 0，最近一次命中 5 → 缺口已被补上，不再加权
        queries = [_ask("宿舍空调", 5, hit_count=0), _ask("宿舍空调", 1, hit_count=5)]
        result = plan_keywords(queries, [], {}, now=NOW)
        self.assertNotIn("gap", result[0].signals)
        self.assertEqual(result[0].last_hit_count, 5)

    def test_demand_reason_mentions_asks_and_crawl_status(self) -> None:
        queries = [_ask("宿舍空调", 1, hit_count=0)] * 5
        result = plan_keywords(queries, [], {}, now=NOW)
        self.assertIn("近7天被问5次", result[0].reason)
        self.assertIn("命中0条", result[0].reason)
        self.assertIn("从未爬取过", result[0].reason)
        self.assertEqual(result[0].signals, ["demand", "gap"])

    def test_blacklisted_and_empty_keywords_ignored(self) -> None:
        queries = [_ask("校园", 1), _ask("", 1)]
        self.assertEqual(plan_keywords(queries, [], {}, now=NOW), [])

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(plan_keywords([], [], {}, now=NOW), [])
```

- [ ] **Step 2: 运行确认失败**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v
```
预期：`ImportError: cannot import name 'plan_keywords'`。

- [ ] **Step 3: 最小实现**

在 `keyword_planner.py` 末尾追加（`math` 加入顶部 import：`import math`——本任务用不到但 Task 3 需要，可先不加；此处仅需以下代码）：

```python
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


def _build_reason(cand: _Candidate, *, now: datetime, gap: bool, penalized: bool) -> str:
    parts: list[str] = []
    if cand.ask_total:
        if cand.ask_count_7d:
            parts.append(f"近7天被问{cand.ask_count_7d}次")
        else:
            parts.append("近期有用户提问")
        if gap:
            parts.append(f"最近一次命中{cand.last_hit_count or 0}条站内数据")
    if cand.content_count:
        label = "相关" if cand.last_crawled_at else "带此标签"
        parts.append(f"近14天有{cand.content_count}条已爬内容{label}、互动量热")
    if cand.last_crawled_at is not None:
        days = max(int(_age_days(now, cand.last_crawled_at)), 0)
        parts.append(f"{days}天前爬过（已降权）" if penalized else f"{days}天前爬过")
    else:
        parts.append("从未爬取过" if cand.ask_total else "从未作为关键词爬取")
    return "，".join(parts)


def plan_keywords(
    queries: list[QueryRecord],
    content_stats: list[ContentStat],
    crawled_at_by_keyword: dict[str, datetime],
    now: datetime,
    top_n: int = 10,
) -> list[KeywordSuggestion]:
    """四信号融合打分，返回按分数降序的 Top-N 推荐。"""

    candidates: dict[str, _Candidate] = {}

    for query in queries:
        word = normalize_keyword(query.keyword)
        if not word:
            continue
        cand = candidates.setdefault(word, _Candidate())
        age = _age_days(now, query.asked_at)
        cand.demand += _decay(age, HALF_LIFE_ASK_DAYS)
        cand.ask_total += 1
        if age <= ASK_WINDOW_DAYS:
            cand.ask_count_7d += 1
        if cand.last_asked_at is None or query.asked_at > cand.last_asked_at:
            cand.last_asked_at = query.asked_at
            cand.last_hit_count = query.hit_count

    max_demand = max((c.demand for c in candidates.values()), default=0.0)
    max_heat = max((c.heat_raw for c in candidates.values()), default=0.0)

    suggestions: list[KeywordSuggestion] = []
    for word, cand in candidates.items():
        demand_norm = cand.demand / max_demand if max_demand else 0.0
        heat_norm = cand.heat_raw / max_heat if max_heat else 0.0
        gap = cand.ask_total > 0 and (cand.last_hit_count or 0) < GAP_HIT_THRESHOLD
        gap_norm = demand_norm * GAP_BOOST if gap else 0.0
        penalized = (
            cand.last_crawled_at is not None
            and _age_days(now, cand.last_crawled_at) < CRAWL_PENALTY_WINDOW_DAYS
        )
        penalty = CRAWL_PENALTY if penalized else 1.0
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
                reason=_build_reason(cand, now=now, gap=gap, penalized=penalized),
            )
        )

    suggestions.sort(key=lambda s: (-s.score, s.keyword))
    return suggestions[:top_n]
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（13 个测试）。

- [ ] **Step 5: 提交（SUB 仓库）**

```bash
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent"
git add backend/app/public_opinion_core/keyword_planner.py backend/tests/test_keyword_planner.py
git commit -m "feat(keyword-planner): 需求分衰减与缺口加权"
```

---

## Task 3（SUB）：热点分（C 延续 / D 发现）

**Files:**
- Modify: `backend/app/public_opinion_core/keyword_planner.py`
- Test: `backend/tests/test_keyword_planner.py`

- [ ] **Step 1: 写失败测试**

在 `test_keyword_planner.py` 追加：

```python
def _content(keyword: str, days_ago: float, engagement: int) -> ContentStat:
    return ContentStat(keyword=keyword, engagement=engagement, published_at=NOW - timedelta(days=days_ago))


class HeatSignalTest(unittest.TestCase):
    def test_pure_heat_ranking_without_any_queries(self) -> None:
        # 冷启动：没有任何用户提问，纯靠内容热度也要能出推荐
        stats = [_content("期末周", 1, 500), _content("校车路线", 1, 20)]
        result = plan_keywords([], stats, {}, now=NOW)
        self.assertEqual([s.keyword for s in result], ["期末周", "校车路线"])
        # 最热词 heat_norm=1 → score = 0.2×1×10 = 2.0
        self.assertAlmostEqual(result[0].score, 2.0, places=3)

    def test_engagement_is_log_damped(self) -> None:
        # 互动量 10000 vs 100：log10 抑制后分差远小于 100 倍
        stats = [_content("爆款话题", 1, 10_000), _content("普通话题", 1, 100)]
        result = plan_keywords([], stats, {}, now=NOW)
        ratio = result[0].score / result[1].score
        self.assertLess(ratio, 3.0)
        self.assertGreater(ratio, 1.0)

    def test_older_content_decays(self) -> None:
        stats = [_content("新话题", 1, 100), _content("旧话题", 13, 100)]
        result = plan_keywords([], stats, {}, now=NOW)
        self.assertEqual(result[0].keyword, "新话题")

    def test_never_crawled_tag_is_discovery(self) -> None:
        stats = [_content("期末周", 1, 300)]
        result = plan_keywords([], stats, {}, now=NOW)
        self.assertEqual(result[0].signals, ["discovery"])
        self.assertIn("从未作为关键词爬取", result[0].reason)

    def test_crawled_keyword_is_heat_continuation(self) -> None:
        stats = [_content("食堂", 1, 300)]
        crawled = {"食堂": NOW - timedelta(days=20)}  # 爬过但超出降权窗口
        result = plan_keywords([], stats, crawled, now=NOW)
        self.assertEqual(result[0].signals, ["heat"])
        self.assertIn("20天前爬过", result[0].reason)
        self.assertNotIn("已降权", result[0].reason)

    def test_zero_engagement_content_produces_no_suggestion(self) -> None:
        stats = [_content("无人问津", 1, 0)]
        self.assertEqual(plan_keywords([], stats, {}, now=NOW), [])
```

- [ ] **Step 2: 运行确认失败**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v
```
预期：HeatSignalTest 全部 FAIL（content_stats 尚未被消费，返回空列表 / signals 缺失）。

- [ ] **Step 3: 实现**

`keyword_planner.py` 顶部加 `import math`。在 `plan_keywords` 中，需求分循环之后、`max_demand = ...` 之前插入：

```python
    for stat in content_stats:
        word = normalize_keyword(stat.keyword)
        if not word:
            continue
        cand = candidates.setdefault(word, _Candidate())
        age = _age_days(now, stat.published_at)
        cand.heat_raw += math.log10(1 + max(stat.engagement, 0)) * _decay(age, HALF_LIFE_CONTENT_DAYS)
        cand.content_count += 1

    for raw_keyword, crawled_at in crawled_at_by_keyword.items():
        word = normalize_keyword(raw_keyword)
        if not word or word not in candidates:
            continue
        cand = candidates[word]
        if cand.last_crawled_at is None or crawled_at > cand.last_crawled_at:
            cand.last_crawled_at = crawled_at
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（19 个测试）。

- [ ] **Step 5: 提交（SUB 仓库）**

```bash
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent"
git add backend/app/public_opinion_core/keyword_planner.py backend/tests/test_keyword_planner.py
git commit -m "feat(keyword-planner): 热点延续与新话题发现信号"
```

---

## Task 4（SUB）：已爬降权 + 包含关系合并 + top_n

**Files:**
- Modify: `backend/app/public_opinion_core/keyword_planner.py`
- Test: `backend/tests/test_keyword_planner.py`

- [ ] **Step 1: 写失败测试**

在 `test_keyword_planner.py` 追加：

```python
class PenaltyAndMergeTest(unittest.TestCase):
    def test_recently_crawled_keyword_is_penalized(self) -> None:
        stats = [_content("食堂", 1, 300), _content("校车", 1, 300)]
        crawled = {"食堂": NOW - timedelta(days=3)}
        result = plan_keywords([], stats, crawled, now=NOW)
        by_kw = {s.keyword: s for s in result}
        # 同热度，3 天前爬过的必须只有未爬过的 0.3 倍
        self.assertAlmostEqual(by_kw["食堂"].score, by_kw["校车"].score * 0.3, places=3)
        self.assertIn("已降权", by_kw["食堂"].reason)

    def test_contained_keyword_merges_into_unique_container(self) -> None:
        # 提问"空调" + 标签"宿舍空调" → 合并为"宿舍空调"，同时带需求和发现信号
        queries = [_ask("空调", 1, hit_count=0)]
        stats = [_content("宿舍空调", 1, 200)]
        result = plan_keywords(queries, stats, {}, now=NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].keyword, "宿舍空调")
        self.assertIn("demand", result[0].signals)
        self.assertIn("discovery", result[0].signals)

    def test_ambiguous_containment_stays_separate(self) -> None:
        # "空调"同时被"宿舍空调"和"空调维修"包含 → 歧义，不合并，三词并存
        stats = [_content("空调", 1, 100), _content("宿舍空调", 1, 100), _content("空调维修", 1, 100)]
        result = plan_keywords([], stats, {}, now=NOW)
        self.assertEqual(len(result), 3)

    def test_top_n_truncates(self) -> None:
        stats = [_content(f"话题{i:02d}", 1, 100 + i) for i in range(15)]
        result = plan_keywords([], stats, {}, now=NOW, top_n=10)
        self.assertEqual(len(result), 10)

    def test_school_prefixed_query_merges_with_bare_keyword(self) -> None:
        # "中山大学食堂"归一化成"食堂"后与已爬"食堂"合并，继承爬取时间
        queries = [_ask("中山大学食堂", 1)]
        crawled = {"食堂": NOW - timedelta(days=3)}
        stats = [_content("食堂", 2, 100)]
        result = plan_keywords(queries, stats, crawled, now=NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].keyword, "食堂")
        self.assertIsNotNone(result[0].last_crawled_at)
```

- [ ] **Step 2: 运行确认失败**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v
```
预期：`test_contained_keyword_merges_into_unique_container` FAIL（返回 2 条而非 1 条）。降权/前缀两个测试在 Task 2/3 的实现下应已通过——若也 FAIL，先修实现再继续。

- [ ] **Step 3: 实现合并**

在 `keyword_planner.py` 的 `plan_keywords` 前追加：

```python
def _build_alias_map(keywords: set[str]) -> dict[str, str]:
    """短词并入唯一包含它的长词（"空调"→"宿舍空调"）；多个包含者视为歧义，不合并。"""

    alias: dict[str, str] = {}
    for word in sorted(keywords, key=len):
        containers = [other for other in keywords if other != word and word in other]
        if len(containers) == 1:
            alias[word] = containers[0]
    for word in list(alias):  # 链式折叠到不动点（严格包含不可能成环）
        target = alias[word]
        while target in alias:
            target = alias[target]
        alias[word] = target
    return alias
```

修改 `plan_keywords`：在函数开头（`candidates: dict... = {}` 之前）先归一化收集全部候选词并建别名映射，三个消费循环都改为写入 `canon(word)`：

```python
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
```

（原先直接消费 `queries` / `content_stats` / `crawled_at_by_keyword` 的三个循环删除，用上面版本替换；`max_demand` 之后的打分段保持不变。）

- [ ] **Step 4: 运行确认通过 + 子项目全量回归**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest tests.test_keyword_planner -v
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s tests -q
```
预期：planner 24 个测试 OK；全量 260+24 全绿。

- [ ] **Step 5: 提交（SUB 仓库）**

```bash
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent"
git add backend/app/public_opinion_core/keyword_planner.py backend/tests/test_keyword_planner.py
git commit -m "feat(keyword-planner): 已爬降权与包含关系合并，算法完成"
```

---

## Task 5（SUB→MAIN）：同步核心到主项目

**Files:**
- Modify: MAIN `scripts/sync_opinion_core.py:3`（docstring 文件数 12→13）
- 自动生成: MAIN `backend/agent/public_opinion_core/keyword_planner.py`

- [ ] **Step 1: 更新同步脚本 docstring**

MAIN `scripts/sync_opinion_core.py` 第 3 行 `- public_opinion_core/：12 个核心文件原样复制（多余文件删除）` 改为 `- public_opinion_core/：13 个核心文件原样复制（多余文件删除）`。

- [ ] **Step 2: 执行同步**

```
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/sync_opinion_core.py
```
预期输出：`core: copied 13, removed 0`、`services: 8 个白名单文件，全部已是最新`。确认 `backend/agent/public_opinion_core/keyword_planner.py` 已存在。

- [ ] **Step 3: 主项目导入冒烟 + 全量回归**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "from backend.agent.public_opinion_core.keyword_planner import plan_keywords; print('ok')"
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s backend/tests -t . -q
```
预期：`ok`；现有 68 个测试全绿。

- [ ] **Step 4: 提交（MAIN 仓库）**

```bash
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add backend/agent/public_opinion_core/keyword_planner.py scripts/sync_opinion_core.py
git commit -m "feat(agent-core): 同步 keyword_planner 智能选题算法核心"
```

---

## Task 6（MAIN）：ChatQueryLog 模型

**Files:**
- Modify: `backend/models.py`（`ProcessedPost` 类之后追加）
- Test: `backend/tests/test_chat_query_log.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_chat_query_log.py`：

```python
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ChatQueryLog


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class ChatQueryLogModelTest(unittest.TestCase):
    def test_table_creates_and_row_inserts_with_defaults(self) -> None:
        # 表必须在 Base.metadata 里（SQLite 演示快照 create_all 依赖这一点）
        db = make_session_factory()()
        db.add(ChatQueryLog(user_id="7", message="宿舍空调怎么样", intent="search", keyword="宿舍", hit_count=2))
        db.commit()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.keyword, "宿舍")
        self.assertEqual(row.hit_count, 2)
        self.assertIsNotNone(row.created_at)
        db.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_chat_query_log -v
```
预期：`ImportError: cannot import name 'ChatQueryLog'`。

- [ ] **Step 3: 实现模型**

`backend/models.py` 中 `ProcessedPost` 类定义之后（`PublicEvent` 之前）插入：

```python
class ChatQueryLog(Base):
    """用户对舆情助手的一次提问（智能选题的需求/缺口信号源）。"""

    __tablename__ = "chat_query_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    intent: Mapped[str] = mapped_column(String(32), default="")
    # keyword 是意图路由提取的话题词；hit_count 是该轮回答检索命中的事件数。
    keyword: Mapped[str] = mapped_column(String(64), default="", index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`。共享 MySQL 建表说明：正式库运行一次 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "from backend.database import init_db; init_db()"`（`init_db` 即 create_all，幂等；执行计划时如 `.env` 指向共享库需先与用户确认再动真库）。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add backend/models.py backend/tests/test_chat_query_log.py
git commit -m "feat(models): chat_query_log 提问日志表"
```

---

## Task 7（MAIN）：对话端点成功路径非阻塞落库

**Files:**
- Modify: `backend/services/log_service.py`（追加 `record_chat_query`）
- Modify: `backend/routers/agent_public.py:70-95`（chat 端点）
- Test: `backend/tests/test_chat_query_log.py`（追加端点测试）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_chat_query_log.py` 追加（顶部 import 增加 `from unittest import mock`、`from fastapi.testclient import TestClient`、`from backend.admin_models import User`、`from backend.database import get_db`、`from backend.main import app`、`from backend.services.auth_service import get_current_user`）：

```python
CANNED_CHAT = {
    "intent": "hotspots",
    "keyword": "宿舍",
    "answer": "回答内容",
    "route_source": "rules",
    "events": [{"title": "a"}, {"title": "b"}],
}


class ChatEndpointLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: User(id=7, username="tester", role="user")
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_chat_success_writes_query_log(self, service_cls) -> None:
        service_cls.return_value.chat.return_value = dict(CANNED_CHAT)

        response = self.client.post("/api/agent/public/chat", json={"message": "宿舍最近有什么热点"})

        self.assertEqual(response.status_code, 200)
        db = self.session_factory()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.user_id, "7")
        self.assertEqual(row.message, "宿舍最近有什么热点")
        self.assertEqual(row.intent, "hotspots")
        self.assertEqual(row.keyword, "宿舍")
        self.assertEqual(row.hit_count, 2)  # len(events)
        db.close()

    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_search_intent_counts_notes(self, service_cls) -> None:
        service_cls.return_value.chat.return_value = {
            "intent": "search",
            "keyword": "",
            "answer": "已找到 1 条",
            "route_source": "rules",
            "events": [],
            "notes": [{"title": "n1"}],
        }

        self.client.post("/api/agent/public/chat", json={"message": "随便看看"})

        db = self.session_factory()
        row = db.query(ChatQueryLog).one()
        self.assertEqual(row.hit_count, 1)
        self.assertEqual(row.keyword, "")
        db.close()

    @mock.patch("backend.routers.agent_public.record_chat_query", side_effect=RuntimeError("log db down"))
    @mock.patch("backend.routers.agent_public.OpinionChatService")
    def test_log_failure_does_not_break_chat(self, service_cls, _record) -> None:
        service_cls.return_value.chat.return_value = dict(CANNED_CHAT)

        response = self.client.post("/api/agent/public/chat", json={"message": "宿舍最近有什么热点"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
        self.assertEqual(response.json()["data"]["answer"], "回答内容")
```

- [ ] **Step 2: 运行确认失败**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_chat_query_log -v
```
预期：`AttributeError: <module 'backend.routers.agent_public'> does not have the attribute 'record_chat_query'` 及日志行数断言失败。

- [ ] **Step 3: 实现**

`backend/services/log_service.py` 顶部 import 区加入 `from backend.models import ChatQueryLog`，文件末尾追加：

```python
def record_chat_query(
    db: Session,
    *,
    user_id: str,
    message: str,
    intent: str,
    keyword: str,
    hit_count: int,
) -> ChatQueryLog:
    """记录一次舆情助手提问（智能选题的需求/缺口信号）。只 add 不 commit，由调用方控制事务。"""

    log = ChatQueryLog(
        user_id=(user_id or "")[:64],
        message=(message or "")[:500],
        intent=(intent or "")[:32],
        keyword=(keyword or "")[:64],
        hit_count=max(int(hit_count or 0), 0),
    )
    db.add(log)
    return log
```

（若 `log_service.py` 没有 `Session` 类型导入，函数签名的 `db` 参数不加注解也可，与该文件现有风格保持一致。）

`backend/routers/agent_public.py`：第 22 行 import 改为

```python
from backend.services.log_service import record_chat_query, write_admin_operation, write_system_log
```

chat 端点 `data = service.chat(...)` 与 `return ok(data)` 之间插入：

```python
        # 智能选题信号：成功路径落一条提问日志；写失败绝不影响对话主流程。
        try:
            if data.get("intent") == "search":
                hit_count = len(data.get("notes") or [])
            else:
                hit_count = len(data.get("events") or [])
            record_chat_query(
                db,
                user_id=str(current_user.id),
                message=payload.message,
                intent=str(data.get("intent") or ""),
                keyword=str(data.get("keyword") or ""),
                hit_count=hit_count,
            )
            db.commit()
        except Exception:
            db.rollback()
```

- [ ] **Step 4: 运行确认通过 + 相邻回归**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_chat_query_log backend.tests.test_opinion_chat_history backend.tests.test_opinion_chat_citations -v
```
预期：全部 OK（现有 chat 测试不受影响）。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add backend/services/log_service.py backend/routers/agent_public.py backend/tests/test_chat_query_log.py
git commit -m "feat(chat): 对话成功路径非阻塞记录提问日志"
```

---

## Task 8（MAIN）：keyword_suggestion_adapter 聚合层

**Files:**
- Create: `backend/services/keyword_suggestion_adapter.py`
- Test: `backend/tests/test_keyword_suggestions.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_keyword_suggestions.py`：

```python
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ChatQueryLog, ProcessedPost
from backend.services.keyword_suggestion_adapter import get_keyword_suggestions

NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _post(raw_post_id: int, source_keyword: str, days_ago: int, likes: int, tags_json: str = "") -> ProcessedPost:
    moment = NOW - timedelta(days=days_ago)
    return ProcessedPost(
        raw_post_id=raw_post_id,
        platform="xhs",
        title=f"{source_keyword}相关帖子{raw_post_id}",
        source_keyword=source_keyword,
        like_count=likes,
        tags_json=tags_json,
        publish_time=moment,
        created_at=moment,
    )


class KeywordSuggestionAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_empty_database_returns_empty_suggestions(self) -> None:
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)
        self.assertEqual(data["meta"]["post_count"], 0)

    def test_end_to_end_four_signals(self) -> None:
        # A+B：宿舍空调被问 3 次、命中 0，从未爬过 → 应登顶
        for i in range(3):
            self.db.add(
                ChatQueryLog(
                    user_id="7",
                    message="宿舍空调怎么样",
                    intent="opinion_answer",
                    keyword="宿舍空调",
                    hit_count=0,
                    created_at=NOW - timedelta(days=1, hours=i),
                )
            )
        # C：食堂 3 天前爬过、内容热 → heat 信号且已降权
        # D：这些帖子带"期末周"标签，从未作为关键词爬过 → discovery
        self.db.add(_post(1, "食堂", 3, 500, tags_json='["期末周"]'))
        self.db.add(_post(2, "食堂", 3, 300, tags_json='["期末周"]'))
        self.db.commit()

        data = get_keyword_suggestions(self.db, now=NOW)
        by_kw = {s["keyword"]: s for s in data["suggestions"]}

        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertEqual(data["suggestions"][0]["signals"], ["demand", "gap"])
        self.assertIn("heat", by_kw["食堂"]["signals"])
        self.assertIn("已降权", by_kw["食堂"]["reason"])
        self.assertEqual(by_kw["期末周"]["signals"], ["discovery"])
        self.assertEqual(data["meta"]["query_count"], 3)
        self.assertEqual(data["meta"]["post_count"], 2)

    def test_broken_tags_json_is_tolerated(self) -> None:
        self.db.add(_post(1, "食堂", 3, 500, tags_json="not-json"))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual([s["keyword"] for s in data["suggestions"]], ["食堂"])

    def test_queries_without_keyword_are_skipped(self) -> None:
        self.db.add(ChatQueryLog(user_id="7", message="综合分析一下", intent="complex_analysis", keyword="", hit_count=0, created_at=NOW))
        self.db.commit()
        data = get_keyword_suggestions(self.db, now=NOW)
        self.assertEqual(data["suggestions"], [])
        self.assertEqual(data["meta"]["query_count"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_keyword_suggestions -v
```
预期：`ModuleNotFoundError: No module named 'backend.services.keyword_suggestion_adapter'`。

- [ ] **Step 3: 实现**

创建 `backend/services/keyword_suggestion_adapter.py`：

```python
"""智能选题聚合层：从 chat_query_log / processed_posts 取四路信号，调核心 planner。

只读，不写任何表。算法本体在 backend/agent/public_opinion_core/keyword_planner.py
（由子项目单向同步，勿在主项目直接改）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.agent.public_opinion_core.keyword_planner import (
    ContentStat,
    QueryRecord,
    plan_keywords,
)
from backend.models import ChatQueryLog, ProcessedPost

CONTENT_WINDOW_DAYS = 14


def _parse_tags(tags_json: str) -> list[str]:
    try:
        data = json.loads(tags_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(tag).strip() for tag in data if str(tag).strip()]


def get_keyword_suggestions(
    db: Session,
    *,
    days: int = 30,
    top: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()

    logs = (
        db.query(ChatQueryLog)
        .filter(ChatQueryLog.created_at >= now - timedelta(days=days))
        .all()
    )
    queries = [
        QueryRecord(keyword=log.keyword, asked_at=log.created_at, hit_count=log.hit_count or 0)
        for log in logs
        if log.keyword
    ]

    posts = (
        db.query(ProcessedPost)
        .filter(ProcessedPost.created_at >= now - timedelta(days=CONTENT_WINDOW_DAYS))
        .all()
    )
    content_stats: list[ContentStat] = []
    for post in posts:
        published = post.publish_time or post.created_at or now
        engagement = (
            (post.like_count or 0)
            + (post.collect_count or 0)
            + (post.comment_count or 0)
            + (post.share_count or 0)
        )
        words = set(_parse_tags(post.tags_json))
        if post.source_keyword:
            words.add(post.source_keyword)
        for word in words:
            content_stats.append(ContentStat(keyword=word, engagement=engagement, published_at=published))

    # 上次爬取时间查全表（不限 14 天窗），reason 里的"N天前爬过"才准确。
    crawled_rows = (
        db.query(ProcessedPost.source_keyword, func.max(ProcessedPost.created_at))
        .filter(ProcessedPost.source_keyword != "")
        .group_by(ProcessedPost.source_keyword)
        .all()
    )
    crawled_at_by_keyword = {keyword: crawled_at for keyword, crawled_at in crawled_rows}

    suggestions = plan_keywords(queries, content_stats, crawled_at_by_keyword, now=now, top_n=top)
    return {
        "suggestions": [s.to_dict() for s in suggestions],
        "meta": {
            "query_count": len(queries),
            "post_count": len(posts),
            "query_window_days": days,
            "content_window_days": CONTENT_WINDOW_DAYS,
        },
    }
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（4 个测试）。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add backend/services/keyword_suggestion_adapter.py backend/tests/test_keyword_suggestions.py
git commit -m "feat(services): 智能选题四信号聚合 adapter"
```

---

## Task 9（MAIN）：管理端 API

**Files:**
- Modify: `backend/routers/admin.py`（追加端点）
- Test: `backend/tests/test_keyword_suggestions.py`（追加 API 测试）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_keyword_suggestions.py` 追加（顶部 import 增加 `from fastapi.testclient import TestClient`、`from backend.admin_models import User`、`from backend.database import get_db`、`from backend.main import app`、`from backend.services.auth_service import get_current_user`）：

```python
class KeywordSuggestionsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session_factory = make_session_factory()

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def login_as(self, role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: User(id=1, username=f"test_{role}", role=role)

    def test_requires_token(self) -> None:
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 401)

    def test_normal_user_is_forbidden(self) -> None:
        self.login_as("user")
        self.assertEqual(self.client.get("/api/admin/keyword-suggestions").status_code, 403)

    def test_admin_gets_suggestions_payload(self) -> None:
        self.login_as("admin")
        db = self.session_factory()
        db.add(ChatQueryLog(user_id="1", message="宿舍空调怎么样", intent="search", keyword="宿舍空调", hit_count=0, created_at=datetime.utcnow()))
        db.commit()
        db.close()

        response = self.client.get("/api/admin/keyword-suggestions?days=30&top=5")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["suggestions"][0]["keyword"], "宿舍空调")
        self.assertIn("meta", data)

    def test_empty_data_returns_empty_list(self) -> None:
        self.login_as("admin")
        response = self.client.get("/api/admin/keyword-suggestions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["suggestions"], [])
```

- [ ] **Step 2: 运行确认失败**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_keyword_suggestions -v
```
预期：API 测试 404（路由不存在）。

- [ ] **Step 3: 实现端点**

`backend/routers/admin.py`：import 区加入 `from backend.services.keyword_suggestion_adapter import get_keyword_suggestions`（若 `Query` 未从 fastapi 导入则一并加入）。在 `/admin/overview` 端点之后追加：

```python
@router.get("/admin/keyword-suggestions")
def keyword_suggestions(
    days: int = Query(default=30, ge=1, le=365),
    top: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """智能选题：四信号融合的爬取关键词推荐（设计见 docs/superpowers/specs/2026-07-10）。"""

    return ok(get_keyword_suggestions(db, days=days, top=top))
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（8 个测试）。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add backend/routers/admin.py backend/tests/test_keyword_suggestions.py
git commit -m "feat(api): GET /api/admin/keyword-suggestions 智能选题接口"
```

---

## Task 10（MAIN）：seed_query_log.py 提问清单导入脚本

**Files:**
- Create: `scripts/seed_query_log.py`
- Test: `backend/tests/test_keyword_seed_scripts.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_keyword_seed_scripts.py`：

```python
from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import ChatQueryLog, ProcessedPost

NOW = datetime(2026, 7, 10, 12, 0, 0)


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class _StubRoute:
    """确定性路由桩：绕开 LLM/规则差异，测试只关心种子脚本自身的行为。"""

    def __init__(self, keyword: str, intent: str = "search") -> None:
        self.keyword = keyword
        self.intent = intent
        self.source = "rules"


def stub_route(message: str) -> _StubRoute:
    return _StubRoute(keyword="宿舍" if "宿舍" in message else "")


class SeedQueryLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_seeds_questions_with_routed_keyword_and_hits(self) -> None:
        from scripts.seed_query_log import seed_questions

        self.db.add(
            ProcessedPost(raw_post_id=1, platform="xhs", title="宿舍空调坏了", source_keyword="宿舍", created_at=NOW, publish_time=NOW)
        )
        self.db.commit()

        inserted = seed_questions(
            self.db,
            ["宿舍空调怎么样", "# 注释行跳过", "", "食堂饭菜如何"],
            route=stub_route,
            now=NOW,
        )
        self.db.commit()

        self.assertEqual(inserted, 2)
        rows = self.db.query(ChatQueryLog).order_by(ChatQueryLog.id).all()
        self.assertEqual(rows[0].keyword, "宿舍")
        self.assertGreaterEqual(rows[0].hit_count, 1)  # 站内有"宿舍"相关帖
        self.assertEqual(rows[0].user_id, "seed")
        self.assertEqual(rows[1].keyword, "")
        self.assertEqual(rows[1].hit_count, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_keyword_seed_scripts -v
```
预期：`ModuleNotFoundError: No module named 'scripts.seed_query_log'`。

- [ ] **Step 3: 实现脚本**

创建 `scripts/seed_query_log.py`：

```python
"""把收集来的真实问题清单灌入 chat_query_log（开发期自举，激活需求/缺口信号）。

用法：
  .venv/Scripts/python.exe scripts/seed_query_log.py --file questions.txt [--user-id seed] [--dry-run]

questions.txt 每行一个问题；空行与 # 开头的行跳过。
设计见 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md 第 7.3 节。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models import ChatQueryLog  # noqa: E402
from backend.services.intent_router import route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402


def seed_questions(db, questions, *, user_id: str = "seed", route=route_intent, now: datetime | None = None) -> int:
    """逐条路由提取话题词、统计站内命中，写入提问日志。返回插入条数（不 commit）。"""

    now = now or datetime.utcnow()
    inserted = 0
    for question in questions:
        question = (question or "").strip()
        if not question or question.startswith("#"):
            continue
        routed = route(question)
        keyword = (routed.keyword or "").strip()
        hit_count = len(query_agent_rows(db, keyword=keyword, platforms=None, limit=10)) if keyword else 0
        db.add(
            ChatQueryLog(
                user_id=user_id[:64],
                message=question[:500],
                intent=(routed.intent or "")[:32],
                keyword=keyword[:64],
                hit_count=hit_count,
                created_at=now,
            )
        )
        inserted += 1
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="导入问题清单到 chat_query_log")
    parser.add_argument("--file", required=True, help="问题清单文件，每行一个问题")
    parser.add_argument("--user-id", default="seed")
    parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
    args = parser.parse_args()

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        inserted = seed_questions(db, questions, user_id=args.user_id)
        if args.dry_run:
            db.rollback()
            print(f"[dry-run] 将导入 {inserted} 条提问")
        else:
            db.commit()
            print(f"已导入 {inserted} 条提问到 chat_query_log")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add scripts/seed_query_log.py backend/tests/test_keyword_seed_scripts.py
git commit -m "feat(scripts): seed_query_log 问题清单导入（开发期自举）"
```

---

## Task 11（MAIN）：check_question_coverage.py 覆盖率验收脚本

**Files:**
- Create: `scripts/check_question_coverage.py`
- Test: `backend/tests/test_keyword_seed_scripts.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_keyword_seed_scripts.py` 追加：

```python
class CheckCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session_factory()()
        self.addCleanup(self.db.close)

    def test_coverage_report_counts_hits_and_misses(self) -> None:
        from scripts.check_question_coverage import check_coverage

        self.db.add(
            ProcessedPost(raw_post_id=1, platform="xhs", title="宿舍空调坏了", source_keyword="宿舍", created_at=NOW, publish_time=NOW)
        )
        self.db.commit()

        report = check_coverage(
            self.db,
            ["宿舍空调怎么样", "食堂饭菜如何", "# 注释"],
            route=stub_route,
        )

        self.assertEqual(report.total, 2)
        self.assertEqual(report.hits, 1)
        self.assertEqual(report.misses, ["食堂饭菜如何"])
        self.assertAlmostEqual(report.rate, 0.5)

    def test_empty_question_list_rate_is_zero(self) -> None:
        from scripts.check_question_coverage import check_coverage

        report = check_coverage(self.db, [], route=stub_route)
        self.assertEqual(report.total, 0)
        self.assertEqual(report.rate, 0.0)
```

（`stub_route` 中 keyword 为空的问题按"全文检索"处理，本测试里"食堂饭菜如何"经 stub 得到空关键词、库内无匹配 → miss。）

- [ ] **Step 2: 运行确认失败**

```
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest backend.tests.test_keyword_seed_scripts -v
```
预期：`ModuleNotFoundError: No module named 'scripts.check_question_coverage'`。

- [ ] **Step 3: 实现脚本**

创建 `scripts/check_question_coverage.py`：

```python
"""问题清单覆盖率验收：逐条检索站内数据，报告命中率（开发期目标 ≥ 80%）。

用法：
  .venv/Scripts/python.exe scripts/check_question_coverage.py --file questions.txt

设计见 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md 第 7.3 节。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.services.intent_router import route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402


@dataclass
class CoverageReport:
    total: int = 0
    hits: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


def check_coverage(db, questions, *, route=route_intent) -> CoverageReport:
    """逐条问题：路由提取话题词（空则用全句）检索，命中≥1 条算覆盖。"""

    report = CoverageReport()
    for question in questions:
        question = (question or "").strip()
        if not question or question.startswith("#"):
            continue
        report.total += 1
        routed = route(question)
        keyword = (routed.keyword or "").strip() or question
        rows = query_agent_rows(db, keyword=keyword, platforms=None, limit=1)
        if rows:
            report.hits += 1
        else:
            report.misses.append(question)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="问题清单站内覆盖率验收")
    parser.add_argument("--file", required=True, help="问题清单文件，每行一个问题")
    args = parser.parse_args()

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        report = check_coverage(db, questions)
    finally:
        db.close()

    print(f"覆盖率：{report.hits}/{report.total} = {report.rate:.0%}（开发期目标 ≥ 80%）")
    if report.misses:
        print("未命中的问题（优先安排爬取）：")
        for question in report.misses:
            print(f"  ✗ {question}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行确认通过**

同 Step 2 命令。预期：`OK`（4 个测试）。

- [ ] **Step 5: 提交（MAIN 仓库）**

```bash
git add scripts/check_question_coverage.py backend/tests/test_keyword_seed_scripts.py
git commit -m "feat(scripts): check_question_coverage 覆盖率验收（目标≥80%）"
```

---

## Task 12（MAIN）：前端「智能选题」页面

**Files:**
- Modify: `frontend/src/api/admin.js`（追加 API 函数）
- Modify: `frontend/src/config/nav.js`（adminItems 追加导航）
- Modify: `frontend/src/router/index.js`（追加路由）
- Create: `frontend/src/views/AdminKeywordsView.vue`

前端无单测基建，本任务以 `npm run build` 作语法验证 + 手动走查验收。

- [ ] **Step 1: API 函数**

`frontend/src/api/admin.js` 末尾追加：

```javascript
// —— 智能选题 ——
export function fetchKeywordSuggestions(params = {}) {
  return http.get('/admin/keyword-suggestions', { params })
}
```

- [ ] **Step 2: 导航项**

`frontend/src/config/nav.js`：`@element-plus/icons-vue` 的 import 列表加入 `MagicStick`；`adminItems` 数组在 `'/admin/ops'` 项之前插入：

```javascript
  { path: '/admin/keywords', label: '智能选题', icon: markRaw(MagicStick), roles: ['admin'] },
```

- [ ] **Step 3: 路由**

`frontend/src/router/index.js`：顶部 import 区加入
`import AdminKeywordsView from '@/views/AdminKeywordsView.vue'`；在 `admin/raw-posts` 路由对象之后插入：

```javascript
      {
        path: 'admin/keywords',
        name: 'AdminKeywords',
        component: AdminKeywordsView,
        meta: { title: '智能选题', subtitle: '客观数据驱动的爬取关键词推荐', roles: ['admin'] },
      },
```

- [ ] **Step 4: 页面组件**

创建 `frontend/src/views/AdminKeywordsView.vue`：

```vue
<template>
  <section class="admin-page admin-keywords">
    <div class="panel-card">
      <div class="intro-card">
        <p class="intro-title">下一轮优先爬什么，由四路客观信号决定：</p>
        <p class="intro-line">
          <el-tag size="small">需求</el-tag> 用户最近在问什么（3天半衰期）
          <el-tag size="small" type="danger">缺口</el-tag> 问了但站内没数据（×2加权）
          <el-tag size="small" type="warning">热点</el-tag> 已爬话题在小红书仍在升温
          <el-tag size="small" type="success">新话题</el-tag> 笔记标签冒头、从未爬过
        </p>
        <p class="intro-meta" v-if="meta">
          基于近 {{ meta.query_window_days }} 天 {{ meta.query_count }} 条用户提问 与
          近 {{ meta.content_window_days }} 天 {{ meta.post_count }} 条已爬内容计算；
          14 天内爬过的关键词 ×0.3 降权。
        </p>
        <el-button size="small" :loading="loading" @click="load">刷新推荐</el-button>
      </div>

      <div class="table-shell" v-loading="loading">
        <table class="compact-table">
          <thead>
            <tr>
              <th style="width: 48px">#</th>
              <th style="min-width: 120px">关键词</th>
              <th style="width: 140px">分数</th>
              <th>信号</th>
              <th style="min-width: 260px">推荐理由</th>
              <th style="width: 130px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in suggestions" :key="item.keyword">
              <td>{{ index + 1 }}</td>
              <td class="kw-cell">{{ item.keyword }}</td>
              <td>
                <div class="score-bar">
                  <div class="score-fill" :style="{ width: scoreWidth(item.score) }" />
                  <span class="score-text">{{ item.score }}</span>
                </div>
              </td>
              <td>
                <el-tag
                  v-for="signal in item.signals"
                  :key="signal"
                  size="small"
                  :type="SIGNAL_TYPE[signal]"
                  class="signal-tag"
                >
                  {{ SIGNAL_LABEL[signal] }}
                </el-tag>
              </td>
              <td class="reason-cell">{{ item.reason }}</td>
              <td>
                <el-button link type="primary" @click="copyCommand(item.keyword)">复制爬取命令</el-button>
              </td>
            </tr>
            <tr v-if="!suggestions.length && !loading">
              <td colspan="6" class="empty-hint">
                暂无推荐。可先在「舆情助手」提问、或运行爬取流水线积累数据后刷新。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchKeywordSuggestions } from '@/api/admin'

const SIGNAL_LABEL = { demand: '需求', gap: '缺口', heat: '热点', discovery: '新话题' }
const SIGNAL_TYPE = { demand: 'primary', gap: 'danger', heat: 'warning', discovery: 'success' }

const suggestions = ref([])
const meta = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await fetchKeywordSuggestions({ days: 30, top: 10 })
    suggestions.value = data.suggestions || []
    meta.value = data.meta || null
  } catch (error) {
    ElMessage.error(error.message || '加载推荐失败')
  } finally {
    loading.value = false
  }
}

function scoreWidth(score) {
  const max = suggestions.value.length ? suggestions.value[0].score : 10
  return `${Math.min(Math.round((score / (max || 1)) * 100), 100)}%`
}

async function copyCommand(keyword) {
  const command = `.\\.venv\\Scripts\\python.exe main.py --keywords "${keyword}" --get_comment yes`
  try {
    await navigator.clipboard.writeText(command)
    ElMessage.success(`已复制（在 MediaCrawler 目录下执行）：${command}`)
  } catch {
    ElMessage.warning(`复制失败，请手动执行：${command}`)
  }
}

onMounted(load)
</script>

<style scoped>
.admin-page {
  padding: 16px;
}

.panel-card {
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 10px;
  padding: 16px;
}

.intro-card {
  padding: 12px 14px;
  margin-bottom: 14px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.intro-title {
  font-weight: 600;
  margin: 0;
}

.intro-line {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  color: var(--color-text-secondary, #6b7280);
}

.intro-meta {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-secondary, #9ca3af);
}

.table-shell {
  overflow-x: auto;
}

.compact-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.compact-table th,
.compact-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--color-border-light, #f0f0f0);
  text-align: left;
  vertical-align: middle;
}

.kw-cell {
  font-weight: 600;
}

.reason-cell {
  color: var(--color-text-secondary, #6b7280);
}

.signal-tag {
  margin-right: 4px;
}

.score-bar {
  position: relative;
  height: 18px;
  background: var(--color-fill, #f3f4f6);
  border-radius: 9px;
  overflow: hidden;
  min-width: 110px;
}

.score-fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: var(--el-color-primary, #409eff);
  opacity: 0.25;
  border-radius: 9px;
}

.score-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
}

.empty-hint {
  text-align: center;
  color: var(--color-text-secondary, #9ca3af);
  padding: 28px 0;
}
</style>
```

- [ ] **Step 5: 构建验证 + 手动走查**

```
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend
npm run build
```
预期：构建成功无报错。然后 `npm run dev` + 后端 `dev.bat`（或按 README 启动），用 admin/admin123456 登录走查：侧栏出现「智能选题」→ 页面加载出推荐或空态引导 → 复制按钮弹出成功提示。用 user/user123456 登录确认侧栏无此项、直接访问 `/admin/keywords` 被拦截。

- [ ] **Step 6: 提交（MAIN 仓库）**

```bash
git add frontend/src/api/admin.js frontend/src/config/nav.js frontend/src/router/index.js frontend/src/views/AdminKeywordsView.vue
git commit -m "feat(frontend): 管理端「智能选题」推荐面板"
```

---

## Task 13（双仓）：收尾验证

- [ ] **Step 1: 双仓全量回归**

```
cd D:\桌面文件\软件工程大作业\campus-opinion-agent\backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s tests -q

cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s backend/tests -t . -q
```
预期：SUB 284 个（260+24）、MAIN 84 个左右（68+16）全绿，零网络、无警告输出。

- [ ] **Step 2: 端到端演示动线冒烟（真实服务）**

按 README 启动后端 + 前端：
1. 以 user 登录，在「舆情助手」问一句"宿舍空调怎么样"；
2. 以 admin 登录打开「智能选题」，确认"宿舍空调"出现且带【需求】徽章、理由含命中信息；
3. 点复制按钮，粘贴出的命令格式为 `.\.venv\Scripts\python.exe main.py --keywords "宿舍空调" --get_comment yes`。

- [ ] **Step 3: 设计文档状态更新 + 提交**

`docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md` 中 `- 状态：待评审` 改为 `- 状态：已实现（2026-07-10）`。

```bash
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
git add docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md docs/superpowers/plans/2026-07-10-keyword-recommendation.md
git commit -m "docs: 智能选题设计与实现计划归档"
```

---

## 自查记录（写完计划后核对 spec）

- 设计 §2 四信号 → Task 2（A/B）、Task 3（C/D）；§3 公式 → Task 2-4（归一化为 0-1 后 ×10，属设计允许的尺度细化）；§4 数据模型/落库/adapter/API → Task 6-9；§5 测试 → 各任务 RED 步骤；§6 演示动线 → Task 13 Step 2；§7 自举脚本 → Task 10-11；前端面板 → Task 12；范围外条目均未实现，符合。
- 类型一致性：`plan_keywords(queries, content_stats, crawled_at_by_keyword, now, top_n)`、`KeywordSuggestion.to_dict()`、`get_keyword_suggestions(db, *, days, top, now)`、`record_chat_query(db, *, user_id, message, intent, keyword, hit_count)`、`seed_questions(db, questions, *, user_id, route, now)`、`check_coverage(db, questions, *, route)` 在定义任务与使用任务中签名一致。
- 无占位符；所有命令带工作目录与预期输出。
