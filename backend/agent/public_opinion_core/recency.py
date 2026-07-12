"""事件时效性（recency）：近期舆情优先，**严重性不随时间打折**。

**缺陷**（2026-07-12 在线上库实测）：整条流水线**时间盲**。热度是互动量的算术、风险是
LLM 研判的严重性、排序是 `风险等级 -> ranking_score`——没有任何一处看过 `publish_time`。
一条 2016 年的帖子和昨天的帖子权重完全相同。

后果就摆在首页：已发布事件「中大学生诽谤被开除」是 high / 90.0、排进前三，作为"当前校园舆情"
推给用户——而它的两条帖子都发于 **2021-06-18，1849 天（五年）前**。评委点开一看，平台在
把一桩五年前的处分当今天的新闻报。语料的年龄分布解释了它为什么能排上去：297 条帖子里
近 7 天只有 2 条（0.7%）、近 30 天 12 条（4%），而 2016–2021 的老帖有 63 条。

**为什么这里不叫 LLM。** 我们有精确的 `publish_time`：「这件事多老」是减法，「多老算旧」是
指数衰减。LLM 更慢、更贵、不确定，而且算术更差。更要命的是**它没法解释**：答辩时
「这个事件 107 天前发生，半衰期 30 天，所以时效权重 = 0.5^(107/30) = 0.084」是站得住的答案，
「模型觉得它不够新」不是。（严重性研判和离群剔除该用 LLM 的地方已经在用了——这里不是那种地方。）

**四根正交的轴，互不改写：**

    严重性 risk_level / risk_score  —— LLM 研判「学校要不要立即处置」。**不衰减**：
                                       宿舍火灾不会因为过了三个月就变得不严重。
    流行度 heat_score / heat_rank   —— 互动量的算术，是实测事实，展示给用户。**不改写**。
    时效性 recency_weight（本模块） —— 事件多新。纯算术，只进排序。
    生命周期 lifecycle（第四根轴） —— 这件事**完了没有**。LLM 研判（见 llm_lifecycle.py），
                                       让「悬而未决」抗衰减、「已了结」加速沉底。因子表在本模块，
                                       因为它是**排序算术**的一部分（同 SEVERITY_WEIGHTS 的分工）。

排序键 = `severity_weight(risk_level) × recency_weight × lifecycle_weight(lifecycle)`
（= `priority_score`）。生命周期未研判时因子恒为 1.0，公式逐位退化回改造前的两轴版本。
`severity_weight` 是 low/medium/high -> 1/3/9 的单调映射：**权重全为 1 时（未标注 /
关掉衰减 / 全无时间戳），排序逐位退化回改造前的「风险等级优先」口径**——不是巧合，是设计约束。
而衰减的动态范围（1 -> 1e-6）远大于严重性的（1 -> 9），所以一个足够旧的 high 一定会被
今天的 low 压下去：这正是要修的那件事。

**时间必须外部注入**：本模块任何一个函数里都不出现 `datetime.now()`。`now` 一律由调用方
传进来（API 请求处理函数、服务层、消融脚本），否则单测不可重复、消融不可复现。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .schemas import OpinionEvent, OpinionNote


# 半衰期（天）。校园舆情衰减很快：一个月前的食堂涨价投诉已经是旧闻。
#
# **为什么是 21 天**（区间 14–30 内取中）：
#   - 语料的真实节奏：离群剔除（b62abaa）之后，「东校区宿舍火灾」这类真实事件的成员帖
#     跨度是 **42 天**量级——半衰期取跨度的一半，意味着一个还在持续发帖的事件在它的活跃期内
#     始终保住 ≥ 0.5 的权重，不会被自己的"前半段"拖下去；而事件一停更，两三周就掉出首屏。
#   - 校园的信息周期以周计（课表、周考、周末）：14 天太短，一个仍在发酵的争议第二周就被腰斩两次；
#     30 天太长，上个月的食堂投诉还能压住本周的新事。21 天 = 三周，一个议题从爆发到学院回应
#     再到被忘记的典型长度。
#   - 具体到刻度：7 天前 0.79，21 天前 0.50，42 天前 0.25，90 天前 0.05，一年前 6e-6。
# `.env` 里可调（EVENT_RECENCY_HALF_LIFE_DAYS）；<= 0 表示**关掉衰减**（消融对照臂 / 应急开关）。
DEFAULT_HALF_LIFE_DAYS = 21.0

# 权重地板：**防下溢，不是语义阈值**。1e-6 ≈ 20 个半衰期 ≈ 14 个月。
# 意义有二：
#   1. 权重永远 > 0，`priority_score` 不会整列塌成 0.0 而让陈旧事件之间的顺序变成随机；
#   2. 地板之下不再按年龄区分——14 个月前和 5 年前的事件，对一个"当前舆情"看板来说是同一种旧，
#      它们之间按严重性（severity_weight）和热度排，这是有意义的区分，年龄不是。
DEFAULT_MIN_WEIGHT = 1e-6

# 事件的代表时间取成员帖的哪一个：median（默认）| latest。见 event_reference_time 的注释。
DEFAULT_STRATEGY = "median"
VALID_STRATEGIES = ("median", "latest")

HALF_LIFE_ENV = "EVENT_RECENCY_HALF_LIFE_DAYS"
MIN_WEIGHT_ENV = "EVENT_RECENCY_MIN_WEIGHT"
STRATEGY_ENV = "EVENT_RECENCY_TIMESTAMP"

# 严重性 -> 排序权重。**必须在 low<medium<high 上单调**，否则"权重全 1 时退化回旧排序"这条
# 兼容性保证就断了。3 倍一档（1/3/9）：跨两档需要 9 倍差距，而衰减的动态范围是 1e6，
# 所以时效性可以把一个足够旧的 high 压到今天的 low 之下——这是**要的**行为，不是副作用。
SEVERITY_WEIGHTS: dict[str, float] = {"high": 9.0, "medium": 3.0, "low": 1.0}
UNKNOWN_SEVERITY_WEIGHT = 1.0

# ---- 生命周期（第四根轴）：状态 -> 排序权重。研判本身在 llm_lifecycle.py，这里只有算术。----
#
# 衰减只看年龄，可年龄答不了这个问题：3.5 个月前的「东校区宿舍火情」（火已扑灭、校方已通报、
# 无伤亡、已立案）**事情结束了**；2.1 个月前的「中大杰青实名举报」（调查无结论）**口子还开着**。
# 同样的年龄、同样的 high，看板对它们的态度不该一样——「已了结」和「悬而未决」是对内容的判断。
#
# **为什么是 2 的幂**：因子可以直接翻译成半衰期，这是答辩上唯一站得住的解释方式——
#   ×2   ⇔ 把事件当作**年轻了一个半衰期（21 天）**：0.5**((age-21)/21) == 2 × 0.5**(age/21)
#   ×4   ⇔ 年轻两个半衰期（42 天）
#   ×0.5 ⇔ 当作老了一个半衰期
# 于是「悬而未决」的含义是精确的：它抵得过 3 周的沉底，不多不少。
#
# **量级的上界是刻意压住的**：整根轴的动态范围 8×（0.5 -> 4）**小于**严重性的 9×（low -> high），
# 所以「持续发酵的低风险」永远压不过「已了结的高风险」——生命周期是第四根轴，不是推翻严重性的后门。
# （它确实能翻转相邻档：一个持续发酵的 medium 可以压过一个已了结的 high——这是**要的**行为：
#  火已经灭了、通报也发了，学校不需要再对它做动作；那个还在发酵的争议需要。）
#
# 未研判（"" / None / LLM 挂了 / 库里是脏值）-> 1.0：**恒等**。不知道结没结 ≠ 已经结了，
# 不许凭空把一个事件打折沉底（同 recency_weight 对未知年龄、platform_weights 对未知平台的口径）。
LIFECYCLE_WEIGHTS: dict[str, float] = {"escalating": 4.0, "ongoing": 2.0, "resolved": 0.5}
UNKNOWN_LIFECYCLE_WEIGHT = 1.0
VALID_LIFECYCLES = tuple(LIFECYCLE_WEIGHTS)

SECONDS_PER_DAY = 86400.0


def parse_time(value: Any) -> datetime | None:
    """把语料里各种写法的时间解析成 **naive UTC** datetime；解析不了返回 None。

    库里的 `publish_time` 是 "2026-03-24 15:20:40" 这种朴素本地串，而调用方传进来的 `now`
    通常是 `datetime.now(UTC)`（带时区）。两边不统一，相减会直接抛
    `TypeError: can't subtract offset-naive and offset-aware datetimes`——
    所以在这里一律归一到 naive UTC。
    """

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # "2026-03-24 15:20:40" 之外的写法（如只有日期、或带斜杠）再试两种常见格式。
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def note_time(note: OpinionNote) -> datetime | None:
    """一条帖子的时间：`publish_time` 优先，退回 `publish_date`（同 `_date_range` 的口径）。"""

    return parse_time(note.publish_time) or parse_time(note.publish_date)


def event_reference_time(
    notes: list[OpinionNote],
    *,
    strategy: str = DEFAULT_STRATEGY,
) -> str:
    """事件的代表时间（ISO 串；一条能解析的时间都没有时返回 ""）。

    **取中位数，不取最新。** 两种口径的取舍是实打实的：

    - `latest`（最新）：只要有**一条**掉队的新帖——今天有人转发一句五年前的旧事、或者一条
      蹭话题的帖子被聚进来——整个事件就"变新"了。这恰恰是最危险的失败模式：它让**旧事件
      伪装成新事件**，而修这个缺陷的全部意义就是不让旧事件冒充新闻。
    - `median`（中位数）：要**过半**成员帖是新的，事件才会前移。代价是一个正在发酵的事件
      会滞后——10 条帖子里有 6 条是上周的，中位数就还停在上周，尽管今天又新增了 4 条。

    选 median，因为两种错误的代价不对称：把正在发酵的事件晚一两天推上首页，损失的是一点
    及时性；把五年前的处分当今天的新闻推上首页，损失的是整个平台的可信度。

    离群剔除（b62abaa）落地后成员表干净了很多（火灾事件的跨度从 938 天缩到 42 天），
    中位数因此稳定，而 latest 的劫持风险也小了——但小不等于没有，口径该守住还是守住。
    偶数个成员取**偏旧**的那个中位（`values[(n - 1) // 2]`）：宁可低估新鲜度，不可高估。

    `EVENT_RECENCY_TIMESTAMP=latest` 可切到最新口径（消融脚本两种都会打出来）。
    """

    values = sorted(time for time in (note_time(note) for note in notes) if time is not None)
    if not values:
        return ""
    if strategy == "latest":
        chosen = values[-1]
    else:
        chosen = values[(len(values) - 1) // 2]
    return chosen.isoformat()


def age_in_days(event_time: str | datetime | None, now: datetime) -> float | None:
    """事件的年龄（天）。`now` **必须**由调用方传入（可注入 = 可复现）。没有时间戳返回 None。"""

    parsed = parse_time(event_time)
    if parsed is None:
        return None
    reference = parse_time(now)
    if reference is None:
        return None
    return (reference - parsed).total_seconds() / SECONDS_PER_DAY


def recency_weight(
    age_days: float | None,
    *,
    half_life_days: float | None = None,
    min_weight: float | None = None,
) -> float:
    """时效权重 = `0.5 ** (age_days / half_life_days)`，钳在 [min_weight, 1.0]。

    纯算术、可解释：107 天 / 半衰期 30 天 -> 0.5 ** (107/30) = 0.084。

    三种边界：
      - `age_days is None`（没有时间戳）-> 1.0。**不知道多老 ≠ 很老**：不许凭空把一条帖子
        打成地板价沉底（同 platform_weights 对未知平台的口径：宁可多冒头，不可凭空消失）。
      - 未来时间戳（年龄为负，爬虫/平台偶尔给出）-> 钳成 1.0，不许拿到 > 1 的权重。
      - `half_life_days <= 0` -> 1.0，即**关掉衰减**（消融对照臂、答辩现场的应急开关）。
    """

    if age_days is None:
        return 1.0

    config = recency_config()
    half_life = config["half_life_days"] if half_life_days is None else float(half_life_days)
    floor = config["min_weight"] if min_weight is None else float(min_weight)

    if half_life <= 0.0:
        return 1.0
    if age_days <= 0.0:
        return 1.0

    weight = 0.5 ** (float(age_days) / half_life)
    return max(min(weight, 1.0), floor)


def severity_weight(risk_level: str) -> float:
    """严重性的排序权重（low/medium/high -> 1/3/9）。**只用于排序，不改写 risk_score**。"""

    return SEVERITY_WEIGHTS.get(str(risk_level or "").strip().lower(), UNKNOWN_SEVERITY_WEIGHT)


def lifecycle_weight(lifecycle: str | None) -> float:
    """生命周期的排序权重（resolved/ongoing/escalating -> 0.5/2/4；未研判 -> 1.0）。

    **只用于排序**：不改写 risk_*（严重性）、heat_*（流行度）、recency_weight（时效性）。
    模型自创的状态（"dormant"/"持续发酵"）落到 1.0 —— 编出来的状态不许变成一个因子。
    """

    return LIFECYCLE_WEIGHTS.get(
        str(lifecycle or "").strip().lower(), UNKNOWN_LIFECYCLE_WEIGHT
    )


def priority_score(risk_level: str, weight: float, lifecycle: str | None = None) -> float:
    """展示优先级 = 严重性权重 × 时效权重 × 生命周期权重。事件排序的第一排序键。

    四根正交的轴，每根都能单独解释给管理员听：

        severity_weight(risk_level)  这件事有多严重（LLM 研判，不随时间打折）
        recency_weight(age_days)     这件事多新（纯算术，0.5 ** (age/半衰期)）
        lifecycle_weight(lifecycle)  这件事完了没有（LLM 研判，让悬而未决的事抗衰减）
        （ranking_score 作为同优先级时的兜底键，见 sort_events）

    `lifecycle=None`（未研判 / LLM 不可用 / 老数据）-> 因子 1.0 -> 逐位退化回改造前的
    `severity × recency`。这是降级保证：AI 不可用时排序不变，而不是变成随机。

    不做 round：地板价 1e-6 × 1.0 = 1e-6，四舍五入到几位小数都会把陈旧事件之间的顺序压平。
    """

    return severity_weight(risk_level) * float(weight) * lifecycle_weight(lifecycle)


def annotate_events_with_recency(
    events: list[OpinionEvent],
    *,
    now: datetime,
    half_life_days: float | None = None,
    min_weight: float | None = None,
) -> list[OpinionEvent]:
    """给事件盖上时效性三件套：`age_days` / `recency_weight` / `priority_score`。

    **只写这三个新字段**：risk_*（严重性）、heat_*（流行度）一个字节都不碰——这是本次改造的
    核心约束，也是 test_event_recency 里钉死的断言。`event_time` 在造事件时就算好了
    （`build_event_from_group`），这里只做"相对于 now 有多老"。
    """

    for event in events:
        event.age_days = age_in_days(event.event_time, now)
        event.recency_weight = recency_weight(
            event.age_days, half_life_days=half_life_days, min_weight=min_weight
        )
        # 生命周期（第四根轴）已经由 llm_lifecycle 盖在事件上（未研判时是 ""，因子 1.0）：
        # 它进 priority_score，不进 recency_weight —— 时效权重必须保持"只是年龄的函数"，
        # 否则「这个事件 64 天前发生，半衰期 21 天，所以权重 0.12」这句话就不再成立了。
        event.priority_score = priority_score(
            event.risk_level, event.recency_weight, event.lifecycle
        )
    return events


def recency_config() -> dict[str, Any]:
    """当前生效的时效性配置（`.env` 可调；写坏了整体退回默认，不炸流水线）。

    降级口径与 `HEAT_PLATFORM_WEIGHTS` 一致：配置非法 -> 用默认值继续跑，而不是让
    整条分析流水线挂掉。
    """

    return {
        "half_life_days": _read_float(HALF_LIFE_ENV, DEFAULT_HALF_LIFE_DAYS, minimum=0.0),
        "min_weight": _read_float(MIN_WEIGHT_ENV, DEFAULT_MIN_WEIGHT, minimum=0.0, maximum=1.0),
        "strategy": _read_strategy(),
    }


def _read_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _read_strategy() -> str:
    raw = (os.getenv(STRATEGY_ENV) or "").strip().lower()
    return raw if raw in VALID_STRATEGIES else DEFAULT_STRATEGY


def event_time_from_payload(date_range_json: str | None) -> str:
    """从 `public_events.date_range_json` 里取事件代表时间（读时算年龄用）。

    `age_days` / `recency_weight` **不落库**：它们是 `now` 的函数，冻进数据库第二天就是错的。
    库里只存 `event_time` 这个事实，年龄在读时（API 请求处理函数）用请求时刻现算。
    老数据没有 `event_time` 时退回 `last_seen_at`（比没有强），再没有就返回 ""（-> 年龄未知）。
    """

    if not date_range_json:
        return ""
    try:
        data = json.loads(date_range_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("event_time", "last_seen_at"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def lifecycle_from_payload(date_range_json: str | None) -> tuple[str, str]:
    """从 `public_events.date_range_json` 里取事件状态 + 理由（读侧排序与展示用）。

    落在 `date_range_json` 里的理由和 `event_time` 一样：**public_events 不加列**（加列要改
    共享 MySQL 的表结构，而这个库是全组共用的），而这个字段本来就装着事件的"时间维度"——
    状态正是时间这根轴上的修饰量（它决定事件抗不抗衰减）。

    库里的脏值（人手改过、老版本写的、模型自创的状态）一律当作**未研判**返回 ""：
    不在枚举里的状态永远不许变成一个排序因子。
    """

    if not date_range_json:
        return "", ""
    try:
        data = json.loads(date_range_json)
    except (TypeError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    lifecycle = str(data.get("lifecycle") or "").strip().lower()
    if lifecycle not in VALID_LIFECYCLES:
        return "", ""
    return lifecycle, str(data.get("lifecycle_reason") or "").strip()


__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "DEFAULT_MIN_WEIGHT",
    "DEFAULT_STRATEGY",
    "HALF_LIFE_ENV",
    "LIFECYCLE_WEIGHTS",
    "MIN_WEIGHT_ENV",
    "SEVERITY_WEIGHTS",
    "STRATEGY_ENV",
    "VALID_LIFECYCLES",
    "VALID_STRATEGIES",
    "age_in_days",
    "annotate_events_with_recency",
    "event_reference_time",
    "event_time_from_payload",
    "lifecycle_from_payload",
    "lifecycle_weight",
    "note_time",
    "parse_time",
    "priority_score",
    "recency_config",
    "recency_weight",
    "severity_weight",
]
