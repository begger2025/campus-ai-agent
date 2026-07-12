"""消融实验：事件排序 —— 时间盲 vs 时效性衰减。

同一批帖子、**同一批事件**排两遍序，唯一的变量是"排序看不看时间"：

  A. 时间盲臂（改造前）：`priority = severity_weight(risk_level) × 1.0`
     ——等价于旧口径「风险等级优先，同风险按 ranking_score」。
  B. 时效臂（改造后）：`priority = severity_weight(risk_level) × 0.5 ** (age_days / half_life)`

两臂共用同一个事件集合（聚类 + LLM 风险只跑一次，深拷贝出第二份），所以名次差异**只可能**
来自时效性这一层。严重性（risk_level/risk_score）和热度（heat_score）在两臂里逐事件比对，
必须**完全一致**——衰减只改顺序，不改事实。

要回答的问题（缺陷是在线上实测出来的）：
  1. 「中大学生诽谤被开除」（两条帖子都发于 2021-06-18，1849 天前，线上 high/90.0 排进前三）
     在两臂各排第几？
  2. 真正近期的事件有没有升上来？
  3. 代表时间取 median 还是 latest，对每个事件的年龄差多少？（latest 会不会被掉队新帖劫持？）
  4. 语料只有 4% 来自近 30 天——衰减之后是不是"所有事件权重都很小"？还排得动吗？

**不连数据库**：全程只读 fixture（data/fixtures/event_clustering_297.json）。
**now 可注入**（--now），所以这份报告是可复现的，不是"今天跑出来是这样"。

    python scripts/ablation_event_recency.py                      # 用 fixture 的最新帖为 now
    python scripts/ablation_event_recency.py --now 2026-07-12
    python scripts/ablation_event_recency.py --no-llm             # 不叫 LLM（离线；风险回退规则）
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
from backend.agent.public_opinion_core.recency import (  # noqa: E402
    DEFAULT_MIN_WEIGHT,
    annotate_events_with_recency,
    event_reference_time,
    note_time,
    parse_time,
    recency_config,
    severity_weight,
)
from backend.agent.public_opinion_core.schemas import OpinionEvent  # noqa: E402
from backend.services.embedding import get_embedder  # noqa: E402
from backend.services.event_refiner import get_cluster_refiner  # noqa: E402
from backend.services.event_risk import get_risk_assessor  # noqa: E402
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
REPORT = ROOT / "docs" / "event-recency-ablation.md"

# 线上缺陷要点名的事件：两条帖子都发于 2021-06-18（1849 天前），却是 high / 90.0、排进前三。
STALE_TITLE_WORDS = ("诽谤", "开除")
STALE_POST_WORDS = ("诽谤",)


def load_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def event_note_ids(event: OpinionEvent) -> set[str]:
    ids = set(event.extra.get("note_ids") or [])
    return ids or {note.note_id for note in event.representative_notes}


def find_event(events: list[OpinionEvent], title_words: tuple[str, ...]) -> OpinionEvent | None:
    for event in events:
        if any(word in event.title for word in title_words):
            return event
    return None


def rank_of(events: list[OpinionEvent], event: OpinionEvent | None) -> int:
    if event is None:
        return 0
    for index, item in enumerate(events, start=1):
        if item.event_key == event.event_key:
            return index
    return 0


def run_clustering(rows: list[dict], now: datetime, use_llm: bool) -> AnalyzeResult:
    """聚类 + 风险只跑一次：两臂必须比的是**同一批事件**的排序。"""

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
        # A 臂（对照）：半衰期 0 = 关掉衰减，权重恒为 1.0 —— 改造前的时间盲排序。
        recency_half_life_days=0.0,
    )


def decayed_arm(
    result: AnalyzeResult, now: datetime, half_life: float
) -> list[OpinionEvent]:
    """在**同一批事件**上盖时效性，然后重排。"""

    events = copy.deepcopy(result.events)
    annotate_events_with_recency(events, now=now, half_life_days=half_life)
    return sort_events(events)


def age_of(event_time: str, now: datetime) -> float | None:
    parsed = parse_time(event_time)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86400.0


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


def member_times(event: OpinionEvent, notes_by_id: dict) -> list[datetime]:
    times = []
    for note_id in sorted(event_note_ids(event)):
        note = notes_by_id.get(note_id)
        if note is None:
            continue
        stamp = note_time(note)
        if stamp is not None:
            times.append(stamp)
    return sorted(times)


def corpus_profile(rows: list[dict], now: datetime) -> dict:
    ages = []
    for row in rows:
        stamp = parse_time(row.get("publish_time") or row.get("publish_date"))
        if stamp is not None:
            ages.append((now - stamp).total_seconds() / 86400.0)
    ages.sort()
    return {
        "total": len(rows),
        "dated": len(ages),
        "last_7": sum(1 for age in ages if age <= 7),
        "last_30": sum(1 for age in ages if age <= 30),
        "last_365": sum(1 for age in ages if age <= 365),
        "median_age": ages[len(ages) // 2] if ages else None,
        "oldest": ages[-1] if ages else None,
        "newest": ages[0] if ages else None,
    }


def render(
    rows: list[dict],
    now: datetime,
    half_life: float,
    blind: list[OpinionEvent],
    decayed: list[OpinionEvent],
    notes_by_id: dict,
    risk_mode: str,
) -> str:
    lines: list[str] = []
    add = lines.append
    profile = corpus_profile(rows, now)

    add("# 消融实验：事件排序 —— 时间盲 vs 时效性衰减")
    add("")
    add(f"语料：`{FIXTURE.relative_to(ROOT).as_posix()}`（{profile['total']} 条 processed_posts 只读快照，不连数据库）")
    add(
        f"参数：now={now.isoformat(timespec='seconds')}（可注入，报告因此可复现）"
        f" half_life={half_life} 天 min_weight={DEFAULT_MIN_WEIGHT} 代表时间=median"
        f" risk_mode={risk_mode} model={EVENT_LLM_MODEL}"
    )
    add("")
    add("A 臂（时间盲，改造前）：`priority = severity_weight(risk_level) × 1.0`，等价于旧口径")
    add("「风险等级优先，同风险按 ranking_score」——整条流水线没有一处看过 `publish_time`。")
    add("")
    add("B 臂（时效性）：`priority = severity_weight(risk_level) × 0.5 ** (age_days / half_life)`，")
    add("`severity_weight` = {low: 1, medium: 3, high: 9}。**纯算术，零 LLM 调用。**")
    add("")

    add("## 语料的年龄（这是个数据问题，不是排序问题）")
    add("")
    add("| 指标 | 值 |")
    add("| --- | ---: |")
    add(f"| 帖子总数 / 有时间戳 | {profile['total']} / {profile['dated']} |")
    add(f"| 近 7 天 | {profile['last_7']}（{profile['last_7'] / profile['total']:.1%}） |")
    add(f"| 近 30 天 | {profile['last_30']}（{profile['last_30'] / profile['total']:.1%}） |")
    add(f"| 近 1 年 | {profile['last_365']}（{profile['last_365'] / profile['total']:.1%}） |")
    add(f"| 帖子年龄中位数 | {profile['median_age']:.0f} 天 |")
    add(f"| 最新 / 最旧 | {profile['newest']:.0f} 天前 / {profile['oldest']:.0f} 天前 |")
    add("")

    stale_blind = find_event(blind, STALE_TITLE_WORDS)
    add("## 要点名的那个事件")
    add("")
    add("| 事件 | 代表时间 | 年龄 | 时效权重 | A 臂（时间盲）排名 | B 臂（时效）排名 |")
    add("| --- | --- | ---: | ---: | ---: | ---: |")
    if stale_blind is None:
        add("| 「中大学生诽谤被开除」 | （本次聚类未形成该事件） | — | — | — | — |")
    else:
        stale_decayed = next(
            (item for item in decayed if item.event_key == stale_blind.event_key), None
        )
        add(
            f"| 「{stale_blind.title}」（{stale_blind.source_count} 帖，{stale_blind.risk_level}/"
            f"{stale_blind.risk_score}） | {stale_blind.event_time} "
            f"| {human_age(stale_decayed.age_days)} | {stale_decayed.recency_weight:.2e} "
            f"| **第 {rank_of(blind, stale_blind)} / {len(blind)}** "
            f"| **第 {rank_of(decayed, stale_decayed)} / {len(decayed)}** |"
        )
    add("")

    add("## 事件并排（按 B 臂排名）")
    add("")
    add("热度与严重性在两臂里是同一个值——衰减只改顺序，不改事实。")
    add("")
    add("| B 排名 | A 排名 | 名次变化 | 事件 | 帖数 | 风险 | heat | 代表时间(median) | 年龄 | 时效权重 | 优先级 |")
    add("| ---: | ---: | :---: | --- | ---: | --- | ---: | --- | ---: | ---: | ---: |")
    for index, event in enumerate(decayed, start=1):
        before = rank_of(blind, event)
        delta = before - index
        arrow = f"↑{delta}" if delta > 0 else (f"↓{-delta}" if delta < 0 else "—")
        add(
            f"| {index} | {before} | {arrow} | {event.title} | {event.source_count} "
            f"| {event.risk_level}/{event.risk_score} | {event.heat_score} "
            f"| {(event.event_time or '未知')[:10]} | {human_age(event.age_days)} "
            f"| {event.recency_weight:.2e} | {event.priority_score:.2e} |"
        )
    add("")

    add("## 代表时间：median vs latest（为什么不取最新）")
    add("")
    add("`latest` 只要有**一条**掉队的新帖就会让整个事件「变新」——旧事件伪装成新闻，正是要修的失败模式。")
    add("")
    add("| 事件 | 帖数 | 跨度(天) | median 年龄 | latest 年龄 | latest 少算了 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for event in decayed:
        times = member_times(event, notes_by_id)
        if not times:
            continue
        span = (times[-1] - times[0]).total_seconds() / 86400.0
        median_age = age_of(event.event_time, now)
        latest_age = age_of(
            event_reference_time(
                [notes_by_id[nid] for nid in sorted(event_note_ids(event)) if nid in notes_by_id],
                strategy="latest",
            ),
            now,
        )
        gap = (median_age or 0) - (latest_age or 0)
        add(
            f"| {event.title} | {event.source_count} | {span:.0f} "
            f"| {human_age(median_age)} | {human_age(latest_age)} | {gap:.0f} 天 |"
        )
    add("")

    add("## 完整性检查：严重性与热度**没有**被时间打折")
    add("")
    blind_by_key = {event.event_key: event for event in blind}
    intact = all(
        (blind_by_key[event.event_key].risk_level, blind_by_key[event.event_key].risk_score,
         blind_by_key[event.event_key].heat_score, blind_by_key[event.event_key].heat_rank)
        == (event.risk_level, event.risk_score, event.heat_score, event.heat_rank)
        for event in decayed
        if event.event_key in blind_by_key
    )
    add(
        f"- `risk_level` / `risk_score` / `heat_score` / `heat_rank` 两臂逐事件比对："
        f"{'全部一致 ✅（衰减只进排序）' if intact else '**出现差异 ❌（时间打折了严重性，必须查）**'}"
    )
    weights = sorted(event.recency_weight for event in decayed)
    floored = sum(1 for weight in weights if weight <= DEFAULT_MIN_WEIGHT)
    add(
        f"- 权重没有塌成 0：最小 {weights[0]:.2e}，最大 {weights[-1]:.2e}，"
        f"触及地板（{DEFAULT_MIN_WEIGHT:.0e}，≈20 个半衰期≈14 个月）的事件 {floored} / {len(decayed)} 个。"
        f"地板之下不再按年龄区分，按严重性/热度排——14 个月前和 5 年前，对「当前舆情」看板是同一种旧。"
    )
    add("")
    add("> 由 `python scripts/ablation_event_recency.py` 生成。")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablation: time-blind ranking vs recency decay")
    parser.add_argument("--no-llm", action="store_true", help="不调 LLM（离线；风险退回规则）")
    parser.add_argument("--now", default="", help="注入「现在」（YYYY-MM-DD），缺省=语料最新帖的当天")
    parser.add_argument("--half-life", type=float, default=None, help="半衰期（天），缺省读 .env")
    parser.add_argument("--report", default=str(REPORT), help="报告写到哪里")
    args = parser.parse_args()

    # Windows 控制台默认 GBK，报告里有 ✅/↑ 之类的字符会直接把脚本崩掉（报告文件本身是 UTF-8，
    # 只有 stdout 有这个问题）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows = load_rows()
    if get_embedder() is None:
        print("[FAIL] 没有可用的 embedder（sentence-transformers 未安装 / EMBEDDING_ENABLED=0）")
        return 1

    if args.now:
        now = datetime.fromisoformat(args.now)
    else:
        # 缺省的"现在" = 语料里最新一条帖子的第二天。**不用 datetime.now()**：报告要可复现，
        # 而 fixture 是冻结的——用真实时钟的话，同一份 fixture 明天会给出不同的年龄。
        stamps = [
            parse_time(row.get("publish_time") or row.get("publish_date")) for row in rows
        ]
        now = max(stamp for stamp in stamps if stamp is not None) + timedelta(days=1)
    half_life = args.half_life if args.half_life is not None else recency_config()["half_life_days"]

    print(f"[1/2] 聚类 + 风险研判（{len(rows)} 条；now={now:%Y-%m-%d}，half_life={half_life} 天）…")
    result = run_clustering(rows, now, use_llm=not args.no_llm)
    blind = list(result.events)  # A 臂：half_life=0 => 权重恒 1.0 => 时间盲排序
    risk_mode = result.run_log.extra.get("risk_mode", "rules")

    print(f"[2/2] 时效性衰减 + 重排（{len(blind)} 个事件）…")
    decayed = decayed_arm(result, now, half_life)

    notes_by_id = {note.note_id: note for note in result.notes}
    report = render(rows, now, half_life, blind, decayed, notes_by_id, risk_mode)
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
