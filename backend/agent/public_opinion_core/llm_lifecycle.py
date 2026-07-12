"""事件状态研判（生命周期）：**悬而未决的事不该随时间沉底**。

**缺陷**（承接 17d5ef2 的时效衰减）：衰减只认年龄——`0.5 ** (age_days / 21)`。可两个同龄的
事件完全可以处在**完全不同的状态**，而时间戳分不出它们：

- 「东校区宿舍火情」（3.5 个月）：明火已扑灭、校方已通报、无人员伤亡、调查已立案。
  **这件事结束了**。它作为记录仍然严重（high / 95），但学校已经不需要再对它做任何动作。
- 「中大作息调整争议」：校方说「会关注师生关切」——**然后呢？作息真的改了吗？学生认了吗？**
  如果没有结论，它就还活着，哪怕最后一条帖子是两个月前的。
- 「中大杰青实名举报」（2.1 个月）：调查有结论了吗？没有的话，这不是历史，是一个**还开着的口子**。

**「已了结」vs「悬而未决」是对内容的判断，不是时间的函数。** 时间戳答不了它（发帖停了既可能
是因为事情解决了，也可能是因为没人再关注但问题还在）；关键词表更答不了（「通报」既出现在
"校方已通报处理结果"里，也出现在"至今未见校方通报"里——同一个词，相反的状态）。读一遍帖子的
模型答得了。**这是时间这根轴上唯一该上 LLM 的地方**——衰减本身是算术，一个字节都不许 LLM 碰。

**第四根正交轴。** 前三根：严重性（risk_*，LLM 判"多严重"）、流行度（heat_*，算术，实测）、
时效性（recency_weight，算术，只看年龄）。本模块判的是第四个、也是和它们都不重合的问题：
**这件事完了没有**。它只写 `lifecycle` / `lifecycle_reason` 两个新字段，然后经由
`recency.lifecycle_weight` 进入排序键：

    priority = severity_weight(risk_level) × recency_weight × lifecycle_weight(lifecycle)

因子（2 的幂，所以能用半衰期读）：escalating 4（≈ 年轻两个半衰期 = 42 天）、ongoing 2
（≈ 年轻 21 天）、resolved 0.5（≈ 老了 21 天）、not_applicable 0.5、未研判 1.0（**恒等**）。

**四档，为什么是这四档**：`resolved` 是终态（学校无需再动作）；`ongoing` 是"没有结论"；
`escalating` 是"没有结论 + 还在扩大"——后两者都该抗衰减，但程度不同：一个还在涨的舆情比一个
冷下来但没结论的事更急，把它们压成一档就等于承认"我们分不出急和不急"。

`not_applicable`（非事件）是**实测逼出来的第四档**：前三档全都预设了"存在一件待处置的事"，
可语料里「中大图书馆对外开放咨询」「中大参观开放询问」这类帖子是在**提问**，不是在提诉求——
它们没有"待处置的事"，"结没结"这个问题对它们无意义。旧提示词的兜底（「拿不准就选 ongoing」）
把它们全塞进了「悬而未决」，看板于是对着一个提问贴挂出「悬而未决」徽标：一句假话。改判
`resolved` 同样是假话（「已处置完毕」≠「本来就不需要处置」）。所以它必须是一个**独立的状态**。
（再多的档——如 `monitoring`——在这份语料上没有可靠证据支撑，模型只会瞎猜。）

**模型会失败，失败不许拖垮流水线**：assessor 抛异常 / 返回 None / 编一个不在枚举里的状态
（"dormant"）/ 给不出理由 —— 一律**逐事件**作废，该事件退回"未研判"（因子 1.0 = 改造前的
行为，而**不是**当成 resolved 沉底），记一条 warning 进 agent_run_logs。一个事件判砸不影响
别的事件；一个都没判成时，服务层如实把 `lifecycle_mode` 记成 `none`（不许假装 AI 上过）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .llm_risk import DEFAULT_MAX_TEXTS, event_input_texts
from .recency import VALID_LIFECYCLES
from .schemas import OpinionEvent, OpinionNote


# (事件标题, 成员帖文本) -> 状态研判；由运行环境注入（见 backend/services/event_lifecycle.py），
# 核心不认识 HTTP、模型名和 API key（同 RiskAssessor / Embedder / ClusterRefiner）。
#   {"lifecycle": "resolved"|"ongoing"|"escalating"|"not_applicable", "lifecycle_reason": "一句人话"}
# 返回 None / 抛异常 = 本次研判不可用，调用方保留"未研判"（因子 1.0）。
LifecycleAssessor = Callable[[str, list[str]], "Mapping[str, Any] | None"]

# 理由是要显示在看板上的（「悬而未决 · 举报两月未见调查结论」），别让模型写论文。
REASON_MAX_CHARS = 60


def assess_events_lifecycle(
    events: list[OpinionEvent],
    assessor: LifecycleAssessor | None,
    *,
    notes_by_id: Mapping[str, OpinionNote] | None = None,
    warnings: list[str] | None = None,
    max_texts: int = DEFAULT_MAX_TEXTS,
) -> int:
    """逐事件研判状态；返回成功研判的事件数（0 = 全部退回"未研判"）。

    输入与风险研判**完全相同**（事件标题 + 成员帖，`llm_risk.event_input_texts`）：判"这件事
    完了没有"和判"这件事多严重"读的是同一批证据，只是问题不同。

    就地只写 `lifecycle` / `lifecycle_reason`（+ `extra["lifecycle_assessed_by"]`）。
    risk_*（严重性是事实）、heat_*（实测量）、event_time / recency_weight（时效算术）
    一个字节都不碰。调用方负责在此之后重排（priority 的第三个因子变了）。
    """

    warnings = warnings if warnings is not None else []
    if assessor is None or not events:
        return 0

    assessed = 0
    for event in events:
        texts = event_input_texts(event, notes_by_id, max_texts=max_texts)
        if not texts:  # 无正文可读：没有输入就没有判断（不许模型凭标题硬猜"结没结"）
            continue
        try:
            raw = assessor(event.title, texts)
        except Exception as exc:  # 超时、网络、SDK 里任何东西
            warnings.append(
                f"llm lifecycle unavailable for event 「{event.title}」, "
                f"left unassessed (factor 1.0): {type(exc).__name__}: {exc}"
            )
            continue

        verdict = _validate(raw)
        if verdict is None:
            warnings.append(
                f"llm lifecycle returned unusable output for event 「{event.title}」, "
                f"left unassessed (factor 1.0)"
            )
            continue

        lifecycle, reason = verdict
        event.lifecycle = lifecycle
        event.lifecycle_reason = reason
        event.extra["lifecycle_assessed_by"] = "llm"
        assessed += 1
    return assessed


def _validate(raw: Any) -> tuple[str, str] | None:
    """验模型输出；None = 不可信，调用方保留"未研判"。

    这是本模块的安全边界。状态会改变一个事件在看板上的位置（最多 8 倍的优先级差），所以：
    编造的状态（"dormant"、"持续发酵"）不许进；**没有理由的状态也不许进**——管理员看到
    「悬而未决」时必须能看到"凭什么"，一个说不出理由的判断在答辩里也辩护不了。
    """

    if not isinstance(raw, Mapping):
        return None

    lifecycle = str(raw.get("lifecycle") or "").strip().lower()
    if lifecycle not in VALID_LIFECYCLES:  # 包括模型自创的状态与空值
        return None

    reason = raw.get("lifecycle_reason")
    if not isinstance(reason, str):
        return None
    reason = reason.strip()[:REASON_MAX_CHARS]
    if not reason:
        return None
    return lifecycle, reason


__all__ = [
    "REASON_MAX_CHARS",
    "VALID_LIFECYCLES",
    "LifecycleAssessor",
    "assess_events_lifecycle",
]
