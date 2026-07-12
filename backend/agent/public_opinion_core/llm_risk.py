"""事件级风险研判：把"这件事有多严重"从关键词表和互动量里解放出来，交给 LLM。

**为什么规则到这里就到头了。** 线上 15 个已发布事件里，「东校区宿舍火灾」（宿舍着火、
楼道浓烟、消防到场）拿到的是 `risk_level=low` / `risk_score=4.0`——**全库最低**；
而「本科课业压力争议」（学生吐槽作业多）拿到 `medium` / 64.0，**全库最高**。

根因在 `sentiment_risk.py` 的两行：

    HIGH_RISK_WORDS = {"诈骗", "银行卡", "验证码", "陌生人", "尾随", "缴费链接"}

系统对"高风险"的全部认识，就是**六个电信诈骗词**。没有火灾、起火、消防、伤亡、坠楼、
食物中毒、性骚扰、学术不端。于是火灾一个高风险词都不命中，只从 `RISK_TOPIC_WORDS` 的
「宿舍」拿到 +4 分，就这样成了最低风险事件。

两个复合缺陷，各自都是结构性的：

1. **闭集词表**。往表里加个「火灾」是治不了的：下一次是食物中毒、电梯困人、宿舍盗窃、
   导师霸凌——**校园出事的方式穷举不完**。这正是必须上 LLM 的地方：它不需要词表里有
   「火灾」，它读得懂「楼道浓烟滚滚」。
2. **风险被互动量污染**。`analyze_note_sentiment_and_risk` 里评论≥25 加 8 分、转发≥10
   加 10 分、热度高再加 8 分——于是这个分数量的是**流行度**，不是**严重性**。火情播报
   是事实通报，没人点赞（三条帖 heat 5/9/3），风险因此隐形；而一条 10 万赞的宿舍日常
   vlog 反倒"高风险"。

本模块只做**严重性**。热度（`heat_score` / `heat_rank` / `ranking_score`）是另一个量，
是可测量的算术，一个字节都不许 LLM 碰——见 `_apply`：只写 risk_* 四个字段。

**判在事件级，不判在帖子级**：37 个事件 vs 297 条帖子，便宜一个数量级，而且事件才是
UI 上展示、管理员要处置的那个东西。返回的字段就是 `aggregate_risk_level` 本来那四个
（level / score / reasons / concerns），下游（落库、排序、前端）一行都不用改。

**模型会失败，失败不许拖垮流水线。** assessor 抛异常 / 返回 None / 编出一个不在枚举里的
风险等级 / 给一个 0-100 之外的分数 / 给不出任何依据 —— 一律**逐事件**作废，退回该事件的
规则结果（它已经在 build_event_from_group 里算好了），并记一条 warning 进 agent_run_logs。
一个事件判砸不影响别的事件（见 `assess_events_risk` 的 try 边界）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .clustering import build_agent_summary
from .schemas import OpinionEvent, OpinionNote


# (事件标题, 成员帖文本) -> 风险研判；由运行环境注入（见 backend/services/event_risk.py），
# 核心不认识 HTTP、模型名和 API key（同 Embedder / SentimentClassifier / ClusterRefiner）。
#   {"risk_level": "high"|"medium"|"low", "risk_score": 0-100,
#    "risk_reasons": [str, ...], "concerns": [str, ...]}
# 返回 None / 抛异常 = 本次研判不可用，调用方保留规则风险。
RiskAssessor = Callable[[str, list[str]], "Mapping[str, Any] | None"]

VALID_RISK_LEVELS = ("low", "medium", "high")

# 一个事件最多送多少条帖子给模型：判"这件事有多严重"不需要读完 91 条，代表帖已经够。
DEFAULT_MAX_TEXTS = 20

# 每条帖子截断长度（比聚类精修的 60 长：严重性藏在细节里——"无人员伤亡"和"多人送医"
# 是同一个开头、完全不同的两件事）。
TEXT_MAX_CHARS = 120

# 依据/关注点的清洗口径：模型话痨或复读时不让它撑爆 UI 和 public_events 的列。
MAX_REASONS = 6
MAX_CONCERNS = 6
REASON_MAX_CHARS = 60


def event_input_texts(
    event: OpinionEvent,
    notes_by_id: Mapping[str, OpinionNote] | None = None,
    *,
    max_texts: int = DEFAULT_MAX_TEXTS,
) -> list[str]:
    """送给模型的帖子文本：代表帖优先，再补其余成员帖，去重、截断。

    代表帖是按 ranking_score（=流行度）挑的 top-5。**只看它们是不够的**：一个事件里
    真正严重的那条帖子完全可能没人点赞（火情播报正是如此），排在第 6 位。所以在
    representative_notes 之后，把其余成员帖（semantic 路径的 extra["note_ids"]）也补进来，
    直到 max_texts。拿不到成员帖时退回代表帖——比不判强。
    """

    texts: list[str] = []
    seen: set[str] = set()

    def push(note: OpinionNote) -> None:
        if note.note_id in seen:
            return
        seen.add(note.note_id)
        text = (note.title or note.content or "").strip()
        if text:
            texts.append(text[:TEXT_MAX_CHARS])

    for note in event.representative_notes:
        push(note)
    for note_id in event.extra.get("note_ids") or []:
        if len(texts) >= max_texts:
            break
        note = (notes_by_id or {}).get(str(note_id))
        if note is not None:
            push(note)
    return texts[:max_texts]


def assess_events_risk(
    events: list[OpinionEvent],
    assessor: RiskAssessor | None,
    *,
    notes_by_id: Mapping[str, OpinionNote] | None = None,
    warnings: list[str] | None = None,
    max_texts: int = DEFAULT_MAX_TEXTS,
) -> int:
    """逐事件用 LLM 重判风险；返回成功研判的事件数（0 = 全部退回规则结果）。

    就地改写 events 的 risk_level / risk_score / risk_reasons / concerns（以及跟着风险
    走的 agent_summary）。**不动任何热度字段**，也不动 event_key / 成员 / 标题。
    调用方负责在此之后按新风险重排事件（sort_events 的第一排序键就是风险）。
    """

    warnings = warnings if warnings is not None else []
    if assessor is None or not events:
        return 0

    assessed = 0
    for event in events:
        texts = event_input_texts(event, notes_by_id, max_texts=max_texts)
        if not texts:  # 无正文可读：没有输入就没有判断（不许模型凭标题硬编）
            continue
        try:
            raw = assessor(event.title, texts)
        except Exception as exc:  # 超时、网络、SDK 里任何东西
            warnings.append(
                f"llm risk unavailable for event 「{event.title}」, "
                f"kept rule risk: {type(exc).__name__}: {exc}"
            )
            continue

        judgement = _validate(raw)
        if judgement is None:
            warnings.append(
                f"llm risk returned unusable output for event 「{event.title}」, kept rule risk"
            )
            continue

        _apply(event, judgement)
        assessed += 1
    return assessed


def _apply(event: OpinionEvent, judgement: tuple[str, float, list[str], list[str]]) -> None:
    """只写风险四件套 + 跟着风险走的 agent_summary。

    热度是**另一个量**：heat_score / heat_rank / ranking_score / source_count 都由算术
    算出来，是可测量的事实。这次改的是"这件事有多严重"，不是"这件事有多火"——
    模型即使在 JSON 里塞了 heat_score，也永远走不到这里。
    """

    level, score, reasons, concerns = judgement
    event.risk_level = level
    event.risk_score = score
    event.risk_reasons = reasons
    event.concerns = concerns
    # agent_summary 里明文写着"风险等级为 X、主要关注点为 Y"：不重算就会和 risk_level 打架。
    event.agent_summary = build_agent_summary(event.category, level, concerns)
    event.extra["risk_assessed_by"] = "llm"


def _validate(raw: Any) -> tuple[str, float, list[str], list[str]] | None:
    """把模型的原始输出验一遍；None = 不可信，调用方退回规则风险。

    这是本模块的安全边界。风险等级是要落库、要在事件列表里排序、管理员要照着它处置的值——
    编造的等级（"critical"）、越界的分数（140）、没有任何依据的判决，一个都不许进真实数据。
    """

    if not isinstance(raw, Mapping):
        return None

    level = str(raw.get("risk_level") or "").strip().lower()
    if level not in VALID_RISK_LEVELS:  # 包括模型自创的 "critical" / "严重" / 空
        return None

    score = raw.get("risk_score")
    # bool 是 int 的子类：True 不是"1 分"。
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    score = float(score)
    if not 0.0 <= score <= 100.0:  # NaN 也在这里出局（任何比较都是 False）
        return None

    reasons = _clean_list(raw.get("risk_reasons"), MAX_REASONS)
    if not reasons:
        # 无依据的判决不算判决：管理员看到 high 时必须能看到"凭什么"，
        # 而且没有依据的 high 也无法在答辩里辩护。退回规则结果（它至少给得出理由）。
        return None
    concerns = _clean_list(raw.get("concerns"), MAX_CONCERNS)
    return level, score, reasons, concerns


def _clean_list(value: Any, limit: int) -> list[str]:
    """字符串列表清洗：非列表 -> 空；去空白、去空串、去重、限长、限条数。"""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()[:REASON_MAX_CHARS]
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items
