"""从**事件**生成检索词：一条规则生不出语言的地方。

**为什么规则到这里就到头了——而且不是"词表不够长"那种到头。**

事件「中大杰青实名举报」（high/91、悬而未决、全库第一优先级）应该让系统想去爬
「学术不端」。可 `keyword_planner` 的候选池只有两个来源：用户提问过的词、已爬内容的标签。
**而「学术不端」这四个字不出现在任何一个里面。** 线上实测该事件的 `top_tags` 是：

    学术、热点、新闻、热点新闻事件、社会新闻、学术论文、真实案件、医学、上海、广州

「热点」「新闻」「上海」——一个能拿去搜的都没有。所以现行 planner **结构上永远**排不出
「学术不端」：它只会给**字面上已经出现过**的词排序，而排序器不会创造它没见过的词。

这不是一条僵化的规则，这是一条**生不出语言**的规则。往黑名单/白名单里再加一百个词也修不了它——
下一个事件是导师霸凌、食物中毒、电梯困人，需要的词是「师德」「食物中毒」「电梯故障」，
**校园出事的方式穷举不完**（同 llm_risk.py 顶部那个论证）。这才是 LLM 真正该站的地方：
它读得懂「耿同学继续举报中山大学另一位杰青」讲的是学术不端，然后**说出**这个词。

**分工，一如既往：**

    这个词有多值得爬（demand / heat / 事件优先级）—— **算术**（keyword_planner）
    这件事该用什么词去搜                       —— **LLM**（本模块）

本模块**不认识** HTTP、模型名和 API key：能力由运行环境注入（见 backend/services/event_keywords.py），
和 llm_risk.py / llm_lifecycle.py 是同一个 seam。核心包保持 stdlib-only。

**安全边界（模型的产物一个字都不被信任）：**

1. **走 planner 现有的卫生规则**（`normalize_keyword` / `GENERIC_BLACKLIST` / `MAX_KEYWORD_LEN`）。
   LLM 提「校园生活」，和用户提「校园生活」被**同一条规则**拒掉——AI 不享有绕过校验的特权。
   顺带也剥掉学校名前缀：爬虫会自己拼 `CRAWL_TOPIC_QUALIFIER`（「中山大学」），关键词里再带
   一遍是浪费长度（`compose_topic_keyword("学术不端", "中山大学") -> "中山大学 学术不端"`）。
2. **逐事件降级**。模型超时 / 返回 None / 返回一坨垃圾 / 提的词全被拒 —— 该事件不贡献生成词，
   记一条 warning，**别的事件照常工作**，而且该事件的标签词（算术那一路）一个都不少。
3. **只在算术已经说它重要的事件上花钱**（`top_events`，按 `event_priority` 降序）。
   一个 low / not_applicable 的事件即使生成了词，`event_norm` 也会把它压到 0.1 分以下——
   为它调一次 LLM 是纯烧钱。
4. **不自动入队**。生成的词是**建议**，和用户提问、内容标签一样进同一个候选池、由同一个
   打分器排序，最后由管理员点击才进爬取队列（`GET /api/admin/keyword-suggestions`）。
   **AI 提议，人来决定**——和证据投递、事件发布同一条纪律。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from .keyword_planner import EventRecord, event_priority, normalize_keyword


# (事件标题, 代表帖正文, 风险等级, 生命周期) -> 检索词列表；由运行环境注入。
# 返回 None / 抛异常 = 本次不可用，调用方逐事件降级。
KeywordProposer = Callable[[str, list[str], str, str], "Sequence[str] | Mapping[str, Any] | None"]

# 一个事件最多贡献几个生成词。5 个足够覆盖一件事的不同说法（「学术不端」「论文造假」
# 「杰青 举报」…），再多就是同义词灌水，只会挤掉别的事件和用户的真实提问。
DEFAULT_MAX_KEYWORDS_PER_EVENT = 5

# 只给**算术已经说它重要**的前 N 个事件花 LLM 的钱（按 event_priority 降序）。
DEFAULT_TOP_EVENTS = 5


def generate_event_keywords(
    events: list[EventRecord],
    proposer: KeywordProposer | None,
    *,
    now: datetime,
    half_life_days: float | None = None,
    warnings: list[str] | None = None,
    top_events: int = DEFAULT_TOP_EVENTS,
    max_per_event: int = DEFAULT_MAX_KEYWORDS_PER_EVENT,
) -> dict[str, int]:
    """逐事件让 LLM 提检索词，就地写进 `event.generated_keywords`。

    返回统计：`{"events": 实际调用的事件数, "accepted": 过关的词数, "rejected": 被卫生规则拒掉的词数}`。
    **不动** EventRecord 的任何别的字段（risk / lifecycle / event_time 都是别人算好的事实）。
    """

    warnings = warnings if warnings is not None else []
    stats = {"events": 0, "accepted": 0, "rejected": 0}
    if proposer is None or not events:
        return stats

    ranked = sorted(
        events,
        key=lambda event: -event_priority(event, now, half_life_days=half_life_days),
    )
    for event in ranked[: max(top_events, 0)]:
        if not event.texts:  # 没有正文就没有输入（同 llm_risk：不许模型凭标题硬编）
            continue
        stats["events"] += 1
        try:
            raw = proposer(event.title, list(event.texts), event.risk_level, event.lifecycle)
        except Exception as exc:  # 超时、网络、SDK 里任何东西
            warnings.append(
                f"llm keyword proposer unavailable for event 「{event.title}」: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        proposed = _extract(raw)
        if proposed is None:
            warnings.append(
                f"llm keyword proposer returned unusable output for event 「{event.title}」"
            )
            continue

        accepted: list[str] = []
        rejected: list[str] = []
        for candidate in proposed:
            word = normalize_keyword(candidate)
            # 归一化后重复（「中大食堂」和「食堂」归一到同一个词）也算一次拒绝：
            # 它没有给候选池带来任何新东西。
            if not word or word in accepted:
                rejected.append(candidate)
                continue
            accepted.append(word)
            if len(accepted) >= max_per_event:
                break

        stats["accepted"] += len(accepted)
        stats["rejected"] += len(rejected)
        if rejected:
            warnings.append(
                f"llm keyword hygiene rejected {len(rejected)} proposal(s) for event "
                f"「{event.title}」: {'、'.join(repr(word) for word in rejected)}"
            )
        if not accepted:
            warnings.append(
                f"llm keyword proposals for event 「{event.title}」 全部被卫生规则拒绝，"
                f"该事件不贡献生成词"
            )
            continue
        event.generated_keywords = accepted
    return stats


def _extract(raw: Any) -> list[str] | None:
    """把模型的原始输出收成一个字符串列表；None = 不可用（调用方记 warning 并跳过该事件）。

    接受两种形状：`["学术不端", ...]` 和 `{"keywords": ["学术不端", ...]}`。
    **裸字符串不接受**——"学术不端" 和 ["学"，"术"，...] 在 Python 里长得一样，一个字符
    一个关键词地喂进候选池是灾难。空列表也不接受（= 模型什么都没说）。
    """

    if isinstance(raw, Mapping):
        raw = raw.get("keywords")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        return None
    words = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    return words or None


__all__ = [
    "DEFAULT_MAX_KEYWORDS_PER_EVENT",
    "DEFAULT_TOP_EVENTS",
    "KeywordProposer",
    "generate_event_keywords",
]
