"""消融实验：事件风险 —— 规则（关键词 + 互动量） vs LLM 研判。

同一批帖子、**同一批事件**跑两遍风险，唯一的变量是"风险由谁判"：

  A. 规则臂：`sentiment_risk.aggregate_risk_level`——六个电诈词（诈骗/银行卡/验证码/
     陌生人/尾随/缴费链接）+ 评论数/转发数/热度加分。
  B. LLM 臂：`llm_risk.assess_events_risk`——把事件标题和成员帖交给模型，问它
     "学校需要为这件事立即处置吗"。

两臂共用同一个事件集合（聚类只跑一次，深拷贝出第二份），所以差异**只可能**来自风险这一层。

要回答的三个问题（缺陷是在线上实测出来的）：
  1. 「东校区宿舍火灾」在两臂各排第几、各是什么等级？（规则：15 个已发布事件里**垫底**，
     low / 4.0——因为火灾一个电诈词都不命中，只从「宿舍」拿到 +4）
  2. 「本科课业压力争议」（学生吐槽作业多）在两臂各排第几？（规则：**第 1**，medium / 64.0
     ——因为它互动量高，而互动量在给风险加分）
  3. 有多少事件的等级变了？两臂各等级的事件数分布？

**不连数据库**：全程只读 fixture。temperature=0 + call_llm 的 JSON 缓存 ⇒ 重复跑不花钱、
拿到同一份研判（答辩材料要可复现，不是一次性轶事）。

    python scripts/ablation_event_risk.py            # 跑两臂，写报告
    python scripts/ablation_event_risk.py --no-llm   # 只跑规则臂（离线可用）
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
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
from backend.agent.public_opinion_core.llm_risk import assess_events_risk  # noqa: E402
from backend.agent.public_opinion_core.schemas import OpinionEvent  # noqa: E402
from backend.services.embedding import get_embedder  # noqa: E402
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
REPORT = ROOT / "docs" / "event-risk-llm-ablation.md"

# 两个要点名的事件（线上缺陷的两端）。
# 认领口径：先看事件标题命中没有，再在候选里挑"装着最多相关帖"的那个。
# 只按帖子内容认会认错：「课业/作业」这些词在「绩点与辅修保研」里也大量出现，
# 于是"帖子命中最多"的事件并不是我们要点名的那一个。
FIRE_WORDS = ("火灾", "起火", "火情", "浓烟", "消防")
FIRE_TITLE_WORDS = ("火灾", "起火", "火情")
COURSEWORK_WORDS = ("课业", "作业", "学业压力")
COURSEWORK_TITLE_WORDS = ("课业",)

LEVELS = ("high", "medium", "low")


def TARGETS(fire_ids: set[str], coursework_ids: set[str]):
    """要点名的两个事件：(展示名, 相关帖 note_id, 标题关键词)。"""

    return [
        ("东校区宿舍火灾", fire_ids, FIRE_TITLE_WORDS),
        ("本科课业压力争议", coursework_ids, COURSEWORK_TITLE_WORDS),
    ]


def load_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def note_ids_matching(rows: list[dict], words: tuple[str, ...]) -> set[str]:
    return {
        str(row.get("note_id") or "")
        for row in rows
        if any(word in f"{row.get('title') or ''}{row.get('content') or ''}" for word in words)
    }


def event_note_ids(event: OpinionEvent) -> set[str]:
    ids = set(event.extra.get("note_ids") or [])
    return ids or {note.note_id for note in event.representative_notes}


def find_event(
    events: list[OpinionEvent],
    targets: set[str],
    title_words: tuple[str, ...] = (),
) -> OpinionEvent | None:
    """点名一个事件：标题命中的优先，同类里挑装着最多相关帖的那个（0 命中 = 没有这个事件）。"""

    candidates = [event for event in events if any(word in event.title for word in title_words)]
    pool = candidates or events
    best, best_hits = None, 0
    for event in pool:
        hits = len(event_note_ids(event) & targets)
        if hits > best_hits:
            best, best_hits = event, hits
    # 标题认出来了但一条相关帖都没对上（理论上不该发生）：仍然认标题。
    return best or (candidates[0] if candidates else None)


def rank_of(events: list[OpinionEvent], event: OpinionEvent | None) -> int:
    if event is None:
        return 0
    for index, item in enumerate(events, start=1):
        if item.event_key == event.event_key:
            return index
    return 0


def run_clustering(rows: list[dict]) -> AnalyzeResult:
    """聚类只跑一次（含 LLM 精修）：两臂必须比的是**同一批事件**的风险。"""

    return PublicOpinionAgentService().analyze_from_rows(
        rows,
        AnalyzeRequest(limit=len(rows)),
        embedder=get_embedder(),
        cluster_threshold=EMBEDDING_CLUSTER_THRESHOLD,
        merge_threshold=EMBEDDING_MERGE_THRESHOLD,
        align_threshold=EMBEDDING_ALIGN_THRESHOLD,
        min_cluster_size=EVENT_MIN_CLUSTER_SIZE,
        cluster_refiner=get_cluster_refiner(),
        refine_min_size=EVENT_REFINE_MIN_SIZE,
        # 规则臂：风险不交给 LLM。
        risk_assessor=None,
    )


def llm_arm(result: AnalyzeResult, assessor) -> tuple[list[OpinionEvent], int, list[str]]:
    """在**规则臂产出的同一批事件**上重判风险，然后按新风险重排。"""

    events = copy.deepcopy(result.events)
    warnings: list[str] = []
    assessed = assess_events_risk(
        events,
        assessor,
        notes_by_id={note.note_id: note for note in result.notes},
        warnings=warnings,
        max_texts=EVENT_RISK_MAX_TEXTS,
    )
    return sort_events(events), assessed, warnings


def level_counts(events: list[OpinionEvent]) -> dict[str, int]:
    return {level: sum(1 for event in events if event.risk_level == level) for level in LEVELS}


def render(
    corpus: int,
    rule_events: list[OpinionEvent],
    llm_events: list[OpinionEvent] | None,
    fire_ids: set[str],
    coursework_ids: set[str],
    assessed: int,
    warnings: list[str],
    usage: dict,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# 消融实验：事件风险 —— 规则 vs LLM 研判")
    add("")
    add(f"语料：`{FIXTURE.relative_to(ROOT).as_posix()}`（{corpus} 条 processed_posts 只读快照，不连数据库）")
    add(
        f"参数：model={EVENT_LLM_MODEL} temperature=0 risk_max_texts={EVENT_RISK_MAX_TEXTS} "
        f"min_cluster_size={EVENT_MIN_CLUSTER_SIZE}（聚类只跑一次，两臂共用同一批事件）"
    )
    add("")
    add("规则臂 = `sentiment_risk.aggregate_risk_level`：六个电诈高风险词 + 评论数/转发数/热度加分。")
    add("LLM 臂 = `llm_risk.assess_events_risk`：事件标题 + 成员帖交给模型，问「学校要不要立即处置」。")
    add("")

    rule_by_key = {event.event_key: event for event in rule_events}
    llm_by_key = {event.event_key: event for event in (llm_events or [])}
    changed = [
        key
        for key, event in llm_by_key.items()
        if key in rule_by_key and event.risk_level != rule_by_key[key].risk_level
    ]

    add("## 总览")
    add("")
    add("| 指标 | 规则风险 | LLM 研判 |")
    add("| --- | --- | --- |")
    add(f"| 事件数 | {len(rule_events)} | {len(llm_events) if llm_events is not None else '（未运行）'} |")
    rule_counts = level_counts(rule_events)
    if llm_events is not None:
        llm_counts = level_counts(llm_events)
        for level in LEVELS:
            add(f"| {level} 事件数 | {rule_counts[level]} | {llm_counts[level]} |")
        add(f"| 等级发生变化的事件 | — | {len(changed)} / {len(rule_events)} |")
        add(f"| 成功研判的事件（其余退回规则） | — | {assessed} / {len(rule_events)} |")
    else:
        for level in LEVELS:
            add(f"| {level} 事件数 | {rule_counts[level]} | （未运行） |")
    add("")

    add("## 两个要点名的事件")
    add("")
    add("| 事件 | 规则：排名 / 等级 / 分数 | LLM：排名 / 等级 / 分数 |")
    add("| --- | --- | --- |")
    for name, ids, title_words in TARGETS(fire_ids, coursework_ids):
        rule_event = find_event(rule_events, ids, title_words)
        cells = []
        if rule_event is None:
            cells.append("（语料中未形成事件）")
        else:
            cells.append(
                f"第 {rank_of(rule_events, rule_event)} / {len(rule_events)}"
                f" · **{rule_event.risk_level}** · {rule_event.risk_score}"
            )
        if llm_events is None or rule_event is None:
            cells.append("（未运行）")
        else:
            llm_event = llm_by_key.get(rule_event.event_key)
            cells.append(
                f"第 {rank_of(llm_events, llm_event)} / {len(llm_events)}"
                f" · **{llm_event.risk_level}** · {llm_event.risk_score}"
            )
        add(f"| 「{name}」（{len(ids)} 条相关帖） | {cells[0]} | {cells[1]} |")
    add("")

    for name, ids, title_words in TARGETS(fire_ids, coursework_ids):
        rule_event = find_event(rule_events, ids, title_words)
        if rule_event is None or llm_events is None:
            continue
        llm_event = llm_by_key.get(rule_event.event_key)
        add(f"「{rule_event.title}」（{rule_event.source_count} 帖，heat_score={rule_event.heat_score}）")
        add("")
        add(f"- 规则依据：{'；'.join(rule_event.risk_reasons) or '（无）'}")
        add(f"- LLM 依据：{'；'.join(llm_event.risk_reasons) or '（无）'}")
        add("")

    add("## 事件风险并排")
    add("")
    add("排名按 `sort_events`（风险等级优先，同风险按 ranking_score）。")
    add("")
    add("| 规则排名 | 事件 | 帖数 | heat_score | 规则等级/分 | LLM 等级/分 | LLM 排名 | 变化 |")
    add("| ---: | --- | ---: | ---: | --- | --- | ---: | --- |")
    for index, event in enumerate(rule_events, start=1):
        llm_event = llm_by_key.get(event.event_key)
        if llm_event is None:
            add(
                f"| {index} | {event.title} | {event.source_count} | {event.heat_score} "
                f"| {event.risk_level} / {event.risk_score} | （未运行） | — | — |"
            )
            continue
        moved = "" if llm_event.risk_level == event.risk_level else f"{event.risk_level} → {llm_event.risk_level}"
        add(
            f"| {index} | {event.title} | {event.source_count} | {event.heat_score} "
            f"| {event.risk_level} / {event.risk_score} "
            f"| {llm_event.risk_level} / {llm_event.risk_score} "
            f"| {rank_of(llm_events, llm_event)} | {moved or '—'} |"
        )
    add("")

    if llm_events is not None:
        # 严重性与热度解耦的直接检验：热度是算术，LLM 不许碰。
        heat_intact = all(
            (llm_by_key[key].heat_score, llm_by_key[key].heat_rank, llm_by_key[key].ranking_score)
            == (event.heat_score, event.heat_rank, event.ranking_score)
            for key, event in rule_by_key.items()
            if key in llm_by_key
        )
        add("## 热度不变（严重性 ≠ 流行度）")
        add("")
        add(
            f"- `heat_score` / `heat_rank` / `ranking_score` 两臂逐事件比对："
            f"{'全部一致 ✅' if heat_intact else '**出现差异 ❌（LLM 动了热度，必须查）**'}"
        )
        add("")
        add("## LLM 用量")
        add("")
        add(
            f"- 调用 {usage['calls']} 次（缓存命中 {usage['cache_hits']}，失败 {usage['errors']}）、"
            f"token {usage['total_tokens']}、耗时 {usage['duration_ms']} ms"
        )
        add(f"- 成功研判 {assessed} / {len(rule_events)} 个事件（失败的逐个退回规则风险）")
        add("")
        if warnings:
            add("降级/告警：")
            for warning in warnings:
                add(f"- {warning}")
            add("")

    add("> 由 `python scripts/ablation_event_risk.py` 生成。")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablation: rule risk vs LLM risk on the same events")
    parser.add_argument("--no-llm", action="store_true", help="只跑规则臂（无网络时用）")
    parser.add_argument("--report", default=str(REPORT), help="报告写到哪里")
    args = parser.parse_args()

    rows = load_rows()
    corpus = len(rows)
    if get_embedder() is None:
        print("[FAIL] 没有可用的 embedder（sentence-transformers 未安装 / EMBEDDING_ENABLED=0）")
        return 1

    fire_ids = note_ids_matching(rows, FIRE_WORDS)
    coursework_ids = note_ids_matching(rows, COURSEWORK_WORDS)
    print(f"[1/2] 聚类 + 规则风险（{corpus} 条；火灾帖 {len(fire_ids)}，课业帖 {len(coursework_ids)}）…")
    result = run_clustering(rows)
    rule_events = list(result.events)

    llm_events, assessed, warnings = None, 0, []
    reset_llm_usage()
    if not args.no_llm:
        assessor = get_risk_assessor()
        if assessor is None:
            print("[WARN] 未配置 EVENT_LLM_API_KEY / EVENT_RISK_ENABLED=0，跳过 LLM 臂")
        else:
            print(f"[2/2] LLM 事件风险研判（model={EVENT_LLM_MODEL}, temperature=0, {len(rule_events)} 个事件）…")
            llm_events, assessed, warnings = llm_arm(result, assessor)
    usage = get_llm_usage()

    report = render(
        corpus, rule_events, llm_events, fire_ids, coursework_ids, assessed, warnings, usage
    )
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
