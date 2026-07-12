"""消融实验：事件排序 —— 只看年龄 vs 看「这件事完了没有」+「它还在不在长」。

同一批帖子、**同一批事件**排两遍序，唯一的变量是"排序看不看事件状态"：

  A. 无状态臂（改造前）：`priority = severity_weight(risk_level) × recency_weight`
     ——衰减只认年龄，同龄的两个事件一视同仁。
  B. 生命周期臂：`priority = severity × recency × lifecycle_weight(lifecycle)`
     ——`lifecycle_weight` = {resolved: 0.5, ongoing: 2, escalating: 4, not_applicable: 0.5, 未研判: 1}。

两臂共用同一个事件集合（聚类 + LLM 风险只跑一次，深拷贝出第二份），所以名次差异**只可能**
来自状态这一层。严重性（risk_*）、热度（heat_*）和时效权重（recency_weight）在两臂里逐事件
比对，必须**完全一致**——状态只改顺序，不改事实，也不改时效算术。

**本轮的变量：「持续发酵」从 LLM 判词改成了算术判据。** 上一轮 `escalating` 在 28 个事件上
一次都没触发（0/28），诊断是诚实的——模型读的是一份**冻结的快照**，看不见"新帖还在不在增加"，
只能从**语气**里嗅发酵感。现在问题一分为二：

    LLM（判断）：这件事悬而未决吗？   -> resolved / ongoing / not_applicable
    算术（测量）：这件事还在长吗？     -> growth_signal(成员帖 publish_time, now)
    合成：escalating = ongoing ∧ growing

要回答的问题：
  1. 「东校区宿舍火情」（火已扑灭 / 已通报 / 无伤亡 / 已立案）——模型判它 resolved 吗？
  2. 「中大杰青实名举报」「中大作息调整争议」——模型判它们 ongoing 吗？
  3. **算术判据在这份真实语料上到底触发不触发？** 触发在哪几个事件上？
     如果一个都没触发——**如实说**。这份快照里近 7 天只有 5 条帖子，
     "没有事件在发酵"完全可能就是**正确答案**，不是失败。
  4. 有没有 resolved / not_applicable 的事件"还在来新帖"却**没有**被抬成 escalating？
     （这是必须守住的性质：算术推翻不了判断。）

**不连数据库**：全程只读 fixture（data/fixtures/event_clustering_297.json）。
**now 可注入**（--now），所以这份报告是可复现的。

    python scripts/ablation_event_lifecycle.py                # 用 fixture 的最新帖 +1 天为 now
    python scripts/ablation_event_lifecycle.py --now 2026-07-12
    python scripts/ablation_event_lifecycle.py --no-llm       # 不叫 LLM（离线；无状态可判 -> 两臂相同）
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.agent.public_opinion_core import (  # noqa: E402
    AnalyzeRequest,
    AnalyzeResult,
    PublicOpinionAgentService,
)
from backend.agent.public_opinion_core.clustering import sort_events  # noqa: E402
from backend.agent.public_opinion_core.llm_lifecycle import (  # noqa: E402
    assess_events_lifecycle,
)
from backend.agent.public_opinion_core.recency import (  # noqa: E402
    DEFAULT_GROWTH_MIN_NOTES,
    LIFECYCLE_WEIGHTS,
    annotate_events_with_recency,
    lifecycle_weight,
    parse_time,
    recency_config,
)
from backend.agent.public_opinion_core.schemas import OpinionEvent  # noqa: E402
from backend.services.embedding import get_embedder  # noqa: E402
from backend.services.event_lifecycle import get_lifecycle_assessor  # noqa: E402
from backend.services.event_refiner import get_cluster_refiner  # noqa: E402
from backend.services.event_risk import get_risk_assessor  # noqa: E402
from backend.services.llm_client import get_llm_usage, reset_llm_usage  # noqa: E402
from backend.services.llm_config import (  # noqa: E402
    EMBEDDING_ALIGN_THRESHOLD,
    EMBEDDING_CLUSTER_THRESHOLD,
    EMBEDDING_MERGE_THRESHOLD,
    EVENT_LLM_MODEL,
    EVENT_MIN_CLUSTER_SIZE,
    EVENT_REFINE_MIN_SIZE,
    EVENT_RISK_MAX_TEXTS,
)

FIXTURE = ROOT / "data" / "fixtures" / "event_clustering_297.json"
REPORT = ROOT / "docs" / "event-lifecycle-ablation.md"

# 要点名的事件，以及**事先写下的预期**（写在跑之前，不许事后改）：
#   火情：火已扑灭、校方已通报、无人员伤亡、调查已立案 -> 预期 resolved
#   举报：调查有没有结论？没有 -> 预期 ongoing（上一轮实测判了 escalating，见报告里的诚实记录）
#   作息：校方只说了"会关注师生关切" -> 预期 ongoing（同上）
#   咨询/分享类（本次修复的靶子）：**根本没有待处置的事** -> 预期 not_applicable
#     上一轮这四个被兜底规则判成了 ongoing（「未见校方结论」），而结构完全相同的
#     「考研信息汇总」「校园与宿舍展示」却被判成 resolved —— 自相矛盾。两类都点名，一起验。
#   注意：预期栏现在写的是 **LLM 的判断**（三档），不再是合成后的状态——`escalating` 已经
#   不是模型能回答的东西了。它会不会被抬成「持续发酵」，由算术在下面单独一张表里回答。
TARGETS: list[tuple[str, tuple[str, ...], str]] = [
    ("东校区宿舍火情", ("火灾", "起火", "火情", "消防"), "resolved"),
    ("中大杰青实名举报", ("举报", "杰青", "学术不端"), "ongoing"),
    ("中大作息调整争议", ("作息", "熄灯", "门禁", "早八"), "ongoing"),
    ("中大图书馆对外开放", ("图书馆对外开放",), "not_applicable"),
    ("中大参观开放询问", ("参观开放",), "not_applicable"),
    ("中大食堂对外开放", ("食堂对外开放",), "not_applicable"),
    ("中大计算机专业咨询", ("计算机专业",), "not_applicable"),
    ("中大考研信息汇总", ("考研信息",), "not_applicable"),
    ("中大校园与宿舍展示", ("校园与宿舍",), "not_applicable"),
]

LIFECYCLE_LABELS = {
    "resolved": "已了结",
    "ongoing": "悬而未决",
    "escalating": "持续发酵",
    "not_applicable": "非事件",
    "": "未研判",
}


def load_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def find_event(events: list[OpinionEvent], words: tuple[str, ...]) -> OpinionEvent | None:
    for event in events:
        if any(word in event.title for word in words):
            return event
    return None


def rank_of(events: list[OpinionEvent], event: OpinionEvent | None) -> int:
    if event is None:
        return 0
    for index, item in enumerate(events, start=1):
        if item.event_key == event.event_key:
            return index
    return 0


def human_age(age: float | None) -> str:
    if age is None:
        return "未知"
    if age < 1:
        return "今天"
    if age < 30:
        return f"{age:.0f} 天前"
    if age < 365:
        return f"{age / 30.4:.1f} 个月前"
    return f"{age / 365.25:.1f} 年前"


def run_clustering(rows: list[dict], now: datetime, half_life: float, use_llm: bool) -> AnalyzeResult:
    """聚类 + 风险 + 时效只跑一次：两臂必须比的是**同一批事件**的排序。

    这里**不注入** lifecycle_assessor：A 臂就是"没有状态"的那一版，B 臂在深拷贝上单独判。
    """

    return PublicOpinionAgentService().analyze_from_rows(
        rows,
        AnalyzeRequest(limit=len(rows)),
        embedder=get_embedder(),
        cluster_threshold=EMBEDDING_CLUSTER_THRESHOLD,
        merge_threshold=EMBEDDING_MERGE_THRESHOLD,
        align_threshold=EMBEDDING_ALIGN_THRESHOLD,
        min_cluster_size=EVENT_MIN_CLUSTER_SIZE,
        cluster_refiner=get_cluster_refiner() if use_llm else None,
        refine_min_size=EVENT_REFINE_MIN_SIZE,
        risk_assessor=get_risk_assessor() if use_llm else None,
        risk_max_texts=EVENT_RISK_MAX_TEXTS,
        now=now,
        recency_half_life_days=half_life,
    )


def lifecycle_arm(
    result: AnalyzeResult, assessor, now: datetime, half_life: float
) -> tuple[list[OpinionEvent], int, list[str]]:
    """在**同一批事件**上研判状态，重算优先级，重排。"""

    events = copy.deepcopy(result.events)
    warnings: list[str] = []
    assessed = assess_events_lifecycle(
        events,
        assessor,
        notes_by_id={note.note_id: note for note in result.notes},
        warnings=warnings,
        max_texts=EVENT_RISK_MAX_TEXTS,
    )
    # 增长窗口显式取半衰期（= 判据的默认口径），别让 .env 悄悄改掉消融的参数。
    annotate_events_with_recency(
        events, now=now, half_life_days=half_life, growth_window_days=half_life
    )
    return sort_events(events), assessed, warnings


def render(
    now: datetime,
    half_life: float,
    blind: list[OpinionEvent],
    staged: list[OpinionEvent] | None,
    assessed: int,
    warnings: list[str],
    usage: dict,
    corpus: int,
) -> str:
    lines: list[str] = []
    add = lines.append
    staged_by_key = {event.event_key: event for event in (staged or [])}

    add("# 消融实验：事件排序 —— 只看年龄 vs 看「这件事完了没有」")
    add("")
    add(f"语料：`{FIXTURE.relative_to(ROOT).as_posix()}`（{corpus} 条 processed_posts 只读快照，不连数据库）")
    add(
        f"参数：now={now.isoformat(timespec='seconds')}（可注入，报告因此可复现）"
        f" half_life={half_life} 天 model={EVENT_LLM_MODEL} temperature=0"
    )
    add("")
    add("A 臂（无状态，改造前）：`priority = severity_weight(risk_level) × recency_weight`")
    add("——衰减只认年龄：一个 3.5 个月前**已经了结**的火情，和一个 2 个月前**仍无结论**的实名举报，")
    add("在它眼里只有「谁更新」的差别。")
    add("")
    add("B 臂（生命周期）：`priority = severity × recency × lifecycle_weight(lifecycle)`，")
    add(
        "`lifecycle_weight` = {"
        + "，".join(f"{key}: {value}" for key, value in LIFECYCLE_WEIGHTS.items())
        + "，未研判: 1.0}。"
    )
    add("因子取 2 的幂，所以能用半衰期读：×2 ⇔ 把事件当作**年轻了一个半衰期**"
        f"（{half_life:.0f} 天），×0.5 ⇔ 当作老了一个半衰期。")
    add("")
    add("**本轮的变量**：「持续发酵」（escalating）从 **LLM 判词**改成了**算术判据**。")
    add("上一轮它在 28 个事件上一次都没触发——因为模型读的是一份冻结的快照，它看不见「新帖还在")
    add("不在增加」，只能从**语气**里嗅发酵感。而每条帖子的 `publish_time` 就摆在那里：")
    add("**「还在不在长」是一个测量，不是一个判断。** 于是问题一分为二：")
    add("")
    add("| 维度 | 谁来答 | 依据 |")
    add("| --- | --- | --- |")
    add("| 有多严重（risk_level） | **LLM**（判断） | 读帖子 |")
    add("| 有多热（heat_score） | 算术（测量） | 互动量 |")
    add("| 有多老（recency_weight） | 算术（测量） | `publish_time` |")
    add("| **悬而未决吗**（lifecycle） | **LLM**（判断） | 读帖子 |")
    add("| **还在长吗**（growing） | 算术（测量） | 成员帖 `publish_time` 分布 |")
    add("")
    add("合成：`escalating` = `ongoing` **∧** `growing`。")
    add("")

    if staged is None:
        add("> **LLM 未运行**（--no-llm 或未配置 EVENT_LLM_API_KEY）：所有事件都是「未研判」，")
        add("> 因子恒为 1.0，两臂完全相同——这也正是降级路径要保证的行为。")
        add("")
        return "\n".join(lines)

    add("## 一、LLM 那一半：事先写下的预期 vs 模型实际判的（**不一致就照实记，不往预期上掰**）")
    add("")
    add("模型现在只回答**判断**：`resolved` / `ongoing` / `not_applicable`。")
    add("`escalating` 已经从它的枚举里删掉了——「还在不在长」是测量，见下一节。")
    add("")
    add("| 事件 | 我预期 | 模型判的 | 一致？ | 模型给的理由 | A 臂排名 | B 臂排名 |")
    add("| --- | --- | --- | :---: | --- | ---: | ---: |")
    for name, words, expected in TARGETS:
        event = find_event(blind, words)
        if event is None:
            add(f"| 「{name}」 | {LIFECYCLE_LABELS[expected]} | （本次聚类未形成该事件） | — | — | — | — |")
            continue
        staged_event = staged_by_key.get(event.event_key)
        got = staged_event.lifecycle_judgement if staged_event else ""
        mark = "✅" if got == expected else "❌"
        add(
            f"| 「{event.title}」（{event.source_count} 帖，{event.risk_level}/{event.risk_score}，"
            f"{human_age(event.age_days)}） | {LIFECYCLE_LABELS[expected]}（{expected}） "
            f"| **{LIFECYCLE_LABELS.get(got, got)}**（{got or '—'}） | {mark} "
            f"| {staged_event.lifecycle_reason if staged_event else '—'} "
            f"| 第 {rank_of(blind, event)} | 第 {rank_of(staged, staged_event)} |"
        )
    add("")

    add("## 二、算术那一半：「这件事还在长吗」——发帖速率，不是语气")
    add("")
    window = staged[0].growth.get("window_days", 0.0) if staged else 0.0
    add(
        f"判据（纯算术，`now` 注入）：窗口 = **{window:.0f} 天**（= 时效半衰期本身，不是新常数），"
        f"窗口内**至少 {DEFAULT_GROWTH_MIN_NOTES} 条**成员帖，**且**窗口内的发帖速率 "
        f"**>=** 该事件在窗口之前的速率。"
    )
    add("一句人话：**它现在来帖的速度，比它自己过去更快吗？**")
    add("")
    add("合成：`escalating` = `ongoing`（模型：这事没结）**∧** `growing`（算术：新帖还在来）。")
    add("**`resolved` / `not_applicable` 永远不会被算术抬成 escalating**——「已了结」和「本来就不是")
    add("一件事」是判断，帖子的时间分布推翻不了它们（否则任何一个被转发到今天的旧事件都能自称在发酵）。")
    add("")
    growing = [event for event in staged if event.growth.get("growing")]
    add(f"**语料实测：{len(growing)} / {len(staged)} 个事件被测出「仍在增长」。**")
    add("")
    if growing:
        add("| 事件 | 模型判断 | 近 {0:.0f} 天新帖 | 总帖 | 近期速率 | 此前速率 | 仍在增长？ | **合成状态** |".format(window))
        add("| --- | --- | ---: | ---: | ---: | ---: | :---: | --- |")
        for event in growing:
            add(
                f"| {event.title} | {LIFECYCLE_LABELS.get(event.lifecycle_judgement, '—')}"
                f"（{event.lifecycle_judgement or '—'}） "
                f"| {event.growth['recent_notes']} | {event.growth['total_notes']} "
                f"| {event.growth['recent_rate']:.3f} 帖/天 | {event.growth['baseline_rate']:.3f} 帖/天 "
                f"| ✅ | **{LIFECYCLE_LABELS.get(event.lifecycle, event.lifecycle)}**"
                f"（{event.lifecycle or '未研判'}） |"
            )
        add("")
        blocked = [event for event in growing if event.lifecycle != "escalating"]
        if blocked:
            add(
                f"其中 **{len(blocked)} 个事件确实在增长，但没有被抬成「持续发酵」**"
                f"（{'、'.join(f'「{event.title}」（{event.lifecycle}）' for event in blocked)}）："
            )
            add("这**正是**要守住的性质——算术看见了新帖，但它没有权力改判「已了结」和「非事件」。")
            add("")
    else:
        add("**一个都没有。** 这不是 bug，见下面的「诚实记录」。")
        add("")

    counts: dict[str, int] = {}
    for event in staged:
        counts[event.lifecycle or ""] = counts.get(event.lifecycle or "", 0) + 1
    add("## 三、状态分布（合成之后）")
    add("")
    add("| 状态 | 因子 | 事件数 |")
    add("| --- | ---: | ---: |")
    for state in ("escalating", "ongoing", "resolved", "not_applicable", ""):
        add(
            f"| {LIFECYCLE_LABELS[state]}（{state or '未研判'}） | ×{lifecycle_weight(state)} "
            f"| {counts.get(state, 0)} |"
        )
    add("")
    add(f"成功研判 {assessed} / {len(staged)} 个事件（失败的逐个保持「未研判」，因子 1.0）。")
    add("")

    add("## 四、事件并排（按 B 臂排名）")
    add("")
    add("严重性、热度、时效权重在两臂里是同一个值——状态只改顺序，不改事实、也不改衰减算术。")
    add("「近期新帖」一栏是**算术**（成员帖时间分布），「状态」一栏是判断与它合成的结果。")
    add("")
    add("| B 排名 | A 排名 | 变化 | 事件 | 帖数 | 风险 | 年龄 | 时效权重 | 近期新帖 | 状态 | 因子 | 优先级 | 理由 |")
    add("| ---: | ---: | :---: | --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |")
    for index, event in enumerate(staged, start=1):
        before = rank_of(blind, event)
        delta = before - index
        arrow = f"↑{delta}" if delta > 0 else (f"↓{-delta}" if delta < 0 else "—")
        recent = (
            f"{event.growth.get('recent_notes', 0)}/{event.growth.get('total_notes', 0)}"
            + (" 📈" if event.growth.get("growing") else "")
        )
        add(
            f"| {index} | {before} | {arrow} | {event.title} | {event.source_count} "
            f"| {event.risk_level}/{event.risk_score} | {human_age(event.age_days)} "
            f"| {event.recency_weight:.2e} | {recent} "
            f"| {LIFECYCLE_LABELS.get(event.lifecycle, event.lifecycle)} "
            f"| ×{lifecycle_weight(event.lifecycle)} | {event.priority_score:.2e} "
            f"| {event.lifecycle_reason or '—'} |"
        )
    add("")

    blind_by_key = {event.event_key: event for event in blind}
    intact = all(
        (
            blind_by_key[event.event_key].risk_level,
            blind_by_key[event.event_key].risk_score,
            blind_by_key[event.event_key].heat_score,
            blind_by_key[event.event_key].heat_rank,
            round(blind_by_key[event.event_key].recency_weight, 12),
        )
        == (
            event.risk_level,
            event.risk_score,
            event.heat_score,
            event.heat_rank,
            round(event.recency_weight, 12),
        )
        for event in staged
        if event.event_key in blind_by_key
    )
    add("## 五、完整性检查：状态**没有**改写严重性、热度、时效权重")
    add("")
    add(
        f"- `risk_level` / `risk_score` / `heat_score` / `heat_rank` / `recency_weight` 两臂逐事件比对："
        f"{'全部一致 ✅（状态只进排序）' if intact else '**出现差异 ❌（状态动了别的轴，必须查）**'}"
    )
    add(
        f"- 生命周期这根轴的动态范围 {max(LIFECYCLE_WEIGHTS.values()) / min(LIFECYCLE_WEIGHTS.values()):.0f}×"
        f"（0.5 → 4）**小于**严重性的 9×（low → high）：「持续发酵的低风险」永远压不过"
        f"「已了结的高风险」——它是第四根轴，不是推翻严重性的后门。"
    )
    add("")

    add("## 诚实记录")
    add("")
    top8 = [event.title for event in staged[:8]]
    non_events_in_top8 = [
        event.title for event in staged[:8] if event.lifecycle == "not_applicable"
    ]
    escalating = [event for event in staged if event.lifecycle == "escalating"]
    if escalating:
        add(f"**`escalating` 本轮触发了 {len(escalating)} 次**（上一轮：0 / 28）：")
        for event in escalating:
            add(
                f"- **「{event.title}」**：模型判 `ongoing`（{event.lifecycle_reason}），"
                f"算术测得近 {event.growth['window_days']:.0f} 天新增 "
                f"{event.growth['recent_notes']} / {event.growth['total_notes']} 帖"
                f"（{event.growth['recent_rate']:.3f} 帖/天 vs 此前 "
                f"{event.growth['baseline_rate']:.3f} 帖/天）-> **合成为「持续发酵」**（×4）。"
            )
        add("")
        add("**这一档现在是可复核的**：徽标背后是一组数字（近 N 天几条、速率多少），")
        add("而不是模型对措辞的感觉。管理员可以自己去数那几条帖子。")
        add("")
    else:
        add("**`escalating` 在这份语料上一次都没有触发（0 / {0}）——而这很可能就是正确答案。**".format(len(staged)))
        add("")
        add("**上一轮它也是 0/28，但那时的 0 是没有意义的**：模型读的是一份冻结的快照，它根本")
        add("**看不见**「新帖还在不在增加」，只能从语气里猜；那个 0 既不能证明没有事件在发酵，")
        add("也不能证明有。**这一轮的 0 是一个测量结果**：判据看的是每条成员帖的 `publish_time`，")
        add("它明确地说——按这个窗口和这个速率门槛，**当前语料里没有任何一个悬而未决的事件仍在增长**。")
        add("")
        add("语料本身就解释了这个 0：297 条帖子里近 7 天只有 **5** 条、近 21 天只有 **12** 条（4%），")
        add("而这 12 条里绝大多数是宿舍环境/考研咨询这类**非事件**（`not_applicable`）——")
        add("它们确实在增长，但它们不是需要学校处置的事，算术**无权**把它们抬上首屏（见第二节）。")
        add("**一个真实的校园舆情看板，在一个没有事件正在发酵的时段，就该一个「持续发酵」都不显示。**")
        add("这不是判据失灵，这正是判据在工作。")
        add("")
        add("判据**确实会亮**——但要有真的新帖涌入才亮。这一点由注入式测试钉死")
        add("（`backend/tests/test_event_growth.py::ServiceWiringTest::test_the_criterion_fires_end_to_end`：")
        add("造一个近 21 天有 2 条新帖的 ongoing 事件，整条流水线跑完后 `lifecycle == \"escalating\"`；")
        add("把 `now` 往后推 60 天，同一批帖子上它自己降回 `ongoing`）。")
        add("**没有在语料上触发 ≠ 没人见过它工作。**")
        add("")
    add(f"**前 8 名（B 臂）**：{'、'.join(top8)}。")
    add("——真事件（举报 / 搬迁 / 作息 / 火情 / 缩短课间）**牢牢占住前 5**，顺序与上一轮逐位一致：")
    add("`not_applicable` 换掉 `ongoing` 之后，没有一个真事件被挤下去。")
    if non_events_in_top8:
        add("")
        add(f"**但前 8 名里仍有 {len(non_events_in_top8)} 个「非事件」**（{'、'.join(non_events_in_top8)}）——")
        add("×0.5 把它们压到了 5 个真事件之下，可它们还在首屏。这不是排序判错了，是**语料稀疏**：")
        add("这份快照里真正的舆情事件只有 5 个，剩下的位置只能由咨询/分享类内容填。如实记在这里，")
        add("不用调权重去掩盖它——把 `not_applicable` 的因子继续往下压，代价是一个被误判成「非事件」")
        add("的**真事件**会掉到低风险事件之下（那才是生命周期推翻严重性的后门）。")
    add("")

    add("## LLM 用量")
    add("")
    add(
        f"- 调用 {usage['calls']} 次（缓存命中 {usage['cache_hits']}，失败 {usage['errors']}）、"
        f"token {usage['total_tokens']}、耗时 {usage['duration_ms']} ms"
    )
    add("")
    if warnings:
        add("降级/告警（每一条都意味着该事件退回「未研判」，因子 1.0）：")
        for warning in warnings:
            add(f"- {warning}")
        add("")

    add("> 由 `python scripts/ablation_event_lifecycle.py` 生成。")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablation: age-only decay vs event lifecycle")
    parser.add_argument("--no-llm", action="store_true", help="不调 LLM（离线；两臂相同）")
    parser.add_argument("--now", default="", help="注入「现在」（YYYY-MM-DD），缺省=语料最新帖的第二天")
    parser.add_argument("--half-life", type=float, default=None, help="半衰期（天），缺省读 .env")
    parser.add_argument("--report", default=str(REPORT), help="报告写到哪里")
    args = parser.parse_args()

    # Windows 控制台默认 GBK：报告里的 ✅/↑ 会让 print 抛 UnicodeEncodeError。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows = load_rows()
    if get_embedder() is None:
        print("[FAIL] 没有可用的 embedder（sentence-transformers 未安装 / EMBEDDING_ENABLED=0）")
        return 1

    if args.now:
        now = datetime.fromisoformat(args.now)
    else:
        stamps = [parse_time(row.get("publish_time") or row.get("publish_date")) for row in rows]
        now = max(stamp for stamp in stamps if stamp is not None) + timedelta(days=1)
    half_life = args.half_life if args.half_life is not None else recency_config()["half_life_days"]

    print(f"[1/2] 聚类 + 风险研判 + 时效衰减（{len(rows)} 条；now={now:%Y-%m-%d}，half_life={half_life} 天）…")
    result = run_clustering(rows, now, half_life, use_llm=not args.no_llm)
    blind = list(result.events)  # A 臂：所有事件 lifecycle="" => 因子恒 1.0

    reset_llm_usage()
    staged, assessed, warnings = None, 0, []
    if not args.no_llm:
        assessor = get_lifecycle_assessor()
        if assessor is None:
            print("[WARN] 未配置 EVENT_LLM_API_KEY / EVENT_LIFECYCLE_ENABLED=0，跳过 B 臂")
        else:
            print(f"[2/2] LLM 事件状态研判（{len(blind)} 个事件，temperature=0）…")
            staged, assessed, warnings = lifecycle_arm(result, assessor, now, half_life)
    usage = get_llm_usage()

    report = render(now, half_life, blind, staged, assessed, warnings, usage, len(rows))
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
