"""消融实验：事件聚类 —— 纯 embedding vs embedding + LLM 精修。

同一批帖子（data/fixtures/event_clustering_297.json，297 条 processed_posts 的只读快照）
跑两遍，唯一的变量是"有没有把大簇交给 LLM 重新审校"，并排打出：

  - 事件数、簇大小分布；
  - 每个事件的标题与帖子数；
  - **巨簇**（> 20% 语料）还剩几个——这是"把不相干的话题堆成一个桶"的直接证据；
  - 「作息调整」这件真实争议有没有作为**独立事件**浮出来（纯 embedding 下它被埋在
    一个 91 帖、标题叫「饭堂相关讨论」而里面没有一条食堂帖的桶里）。

**不连数据库**：全程只读 fixture。实验因此可复现（答辩材料，不是一次性轶事），
也不给共用的 MySQL 添一份负载。temperature=0 + call_llm 的 JSON 缓存 ⇒ 重复跑不再花钱、
且拿到同一份划分。

    python scripts/ablation_event_refine.py            # 跑两臂，写报告
    python scripts/ablation_event_refine.py --no-llm   # 只跑 embedding 臂（离线可用）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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
from backend.services.embedding import get_embedder  # noqa: E402
from backend.services.event_refiner import get_cluster_refiner  # noqa: E402
from backend.services.llm_client import get_llm_usage, reset_llm_usage  # noqa: E402
from backend.services.llm_config import (  # noqa: E402
    EMBEDDING_ALIGN_THRESHOLD,
    EMBEDDING_CLUSTER_THRESHOLD,
    EMBEDDING_MERGE_THRESHOLD,
    EVENT_LLM_MODEL,
    EVENT_MIN_CLUSTER_SIZE,
    EVENT_REFINE_MIN_SIZE,
)

FIXTURE = ROOT / "data" / "fixtures" / "event_clustering_297.json"
REPORT = ROOT / "docs" / "event-clustering-llm-refine-ablation.md"

# 离群剔除要证的那件事：「东校区宿舍火灾」的 4 条代表内容里混着一张 2023 年的宿舍照片，
# 它把事件的时间跨度从 2 天撑到 900 多天（时间衰减特性就是被这种帖子毁掉的）。
FIRE_KEYWORDS = ("火灾", "火情", "起火")

# **线上已发布事件**「东校区宿舍火灾」的 4 条代表内容（note_id 抄自线上库，帖子本身都在
# 这份 fixture 里，所以这一节仍然不连数据库）。
#
# 为什么要单列这一节：这份 297 条的 fixture **复现不出**线上那个缺陷——同一批帖子在
# 当前阈值下，那张 2023 年的照片被 embedding 分到了「零散杂项帖」，压根没进火灾簇
# （线上事件是另一批语料、另一次运行的产物）。可缺陷本身是真的、页面上看得见的。
# 所以这里把**线上事件原样的成员构成**（这 4 条）交给真实模型，直接回答那个问题：
# 「把这个已发布的事件给模型看，它会不会把照片摘出去？」
PUBLISHED_FIRE_EVENT = [
    "ks:3x2s7cqucwecq3e",  # 2026-03-24 东校区宿舍发生火情
    "ks:3xitfk98jumerag",  # 2026-03-26 广州校区宿舍发生火灾
    "ks:3xwndx335wdnw4y",  # 2026-03-26 宿舍起火 校方通报
    "ks:3xzvr3spd3kfcki",  # 2023-08-31 #中大宿舍实拍  <- 与火灾无关的离群帖
]

# 巨簇judge：一个事件吃掉超过 20% 的语料，基本可以断定它不是"一件事"。
MEGA_RATIO = 0.20

# 要找回的那件真实事件（20 帖的校园争议，纯 embedding 下从未独立出现过）。
BURIED_EVENT_KEYWORD = "作息"

# 当前缺陷的指纹：词频 top-1 命名法产出的套话标题。
BOILERPLATE = "相关讨论"


# note_id -> 帖子标题：报告里要能指名道姓地说"被剔走的是哪一条"。
TEXTS: dict[str, str] = {}


def load_rows() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run_arm(rows: list[dict], *, refiner) -> AnalyzeResult:
    return PublicOpinionAgentService().analyze_from_rows(
        rows,
        AnalyzeRequest(limit=len(rows)),
        # previous_snapshot=None：不读记忆快照，两臂都从零开始（否则旧标题会被继承进来）。
        embedder=get_embedder(),
        cluster_threshold=EMBEDDING_CLUSTER_THRESHOLD,
        merge_threshold=EMBEDDING_MERGE_THRESHOLD,
        align_threshold=EMBEDDING_ALIGN_THRESHOLD,
        min_cluster_size=EVENT_MIN_CLUSTER_SIZE,
        cluster_refiner=refiner,
        refine_min_size=EVENT_REFINE_MIN_SIZE,
    )


def without_ejection(refiner):
    """把模型的剔除桶丢掉 —— 复现"没有离群剔除"的旧行为。

    第三臂的意义：它和第二臂用的是**同一次模型输出**（temperature=0 + call_llm 缓存，
    第二臂全是缓存命中），唯一的差别是"unrelated 名单是被执行还是被无视"。于是两臂之差
    就干净地等于**离群剔除这一个能力**，而不掺杂模型换了个说法之类的噪声。
    """

    if refiner is None:
        return None

    def stripped(texts: list[str]):
        topics = refiner(texts)
        if topics is None:
            return None
        return [topic for topic in topics if not topic.get("unrelated")]

    return stripped


def event_span_days(note_ids: list[str], times: dict[str, str]) -> tuple[int, str, str]:
    """事件的时间跨度：成员发帖时间的 max - min（天）。

    事件的时间戳是从成员推出来的——一条 2023 年的无关帖子会把 2026 年的火灾"拉长"成
    一个持续三年的事件，下一步要做的时间衰减因此会彻底失真。
    """

    stamps = sorted(times[note_id] for note_id in note_ids if times.get(note_id))
    if not stamps:
        return 0, "", ""
    first, last = stamps[0], stamps[-1]
    span = (
        datetime.fromisoformat(last[:19]) - datetime.fromisoformat(first[:19])
    ).days
    return span, first[:10], last[:10]


def fire_event(item: dict) -> tuple[str, list[str]] | None:
    """找到那个火灾事件（标题里带火灾/火情/起火）。"""

    for title, note_ids in item["note_ids_by_event"]:
        if any(keyword in title for keyword in FIRE_KEYWORDS):
            return title, note_ids
    return None


def buried_note_ids(rows: list[dict]) -> set[str]:
    """语料里真正在谈「作息调整」的帖子（标题/正文命中）。

    只看事件标题会被骗：纯 embedding 那一臂的消歧标题里也带着「作息调整」四个字，
    可它的簇里只捞到一部分作息帖，其余的还埋在 91 帖的巨桶里。**要数的是帖子，不是标题。**
    """

    return {
        str(row.get("note_id") or "")
        for row in rows
        if BURIED_EVENT_KEYWORD in f"{row.get('title') or ''}{row.get('content') or ''}"
    }


def stats(result: AnalyzeResult, corpus: int, buried_ids: set[str]) -> dict:
    sizes = sorted((event.source_count for event in result.events), reverse=True)
    mega = [event for event in result.events if event.source_count > corpus * MEGA_RATIO]
    buried = [event for event in result.events if BURIED_EVENT_KEYWORD in event.title]
    # 召回口径：标题带「作息」的事件里，真正装着多少条作息帖（帖子级，不是标题级）。
    captured = {
        note_id
        for event in buried
        for note_id in event.extra.get("note_ids", [])
        if note_id in buried_ids
    }
    # 巨桶里还埋着多少条作息帖 —— 这是"被埋"的直接度量。
    in_mega = {
        note_id
        for event in mega
        for note_id in event.extra.get("note_ids", [])
        if note_id in buried_ids
    }
    return {
        "buried_captured": len(captured),
        "buried_total": len(buried_ids),
        "buried_in_mega": len(in_mega),
        "event_count": len(result.events),
        "sizes": sizes,
        "largest": sizes[0] if sizes else 0,
        "largest_share": (sizes[0] / corpus) if sizes else 0.0,
        "covered": sum(sizes),
        "mega": [(event.title, event.source_count) for event in mega],
        "boilerplate_titles": [e.title for e in result.events if BOILERPLATE in e.title],
        "buried_event": [(event.title, event.source_count) for event in buried],
        "refined_clusters": result.run_log.extra.get("refined_clusters", 0),
        "clustering_mode": result.run_log.extra.get("clustering_mode"),
        "suppressed": result.run_log.extra.get("suppressed_clusters", 0),
        "ejected": result.run_log.extra.get("ejected_notes", 0),
        # 事件 -> 成员 note_id：两臂相减就能精确指出"哪条帖子从哪个事件里被剔走了"。
        "note_ids_by_event": [
            (event.title, list(event.extra.get("note_ids", [])))
            for event in sorted(result.events, key=lambda e: -e.source_count)
        ],
        "covered_ids": {
            note_id for event in result.events for note_id in event.extra.get("note_ids", [])
        },
        "warnings": list(result.warnings),
        "events": [
            (event.title, event.source_count, bool(event.extra.get("refined_by")))
            for event in sorted(result.events, key=lambda e: -e.source_count)
        ],
    }


def render_ejection(add, refine_only: dict, llm: dict, times: dict[str, str]) -> None:
    """离群剔除的证据：谁被剔了、从哪个事件剔的、火灾事件的时间跨度变成了多少。

    对照的是**同一次模型输出**（第二臂无视 unrelated，第三臂执行 unrelated），
    因此这一节的每一处差异都只能由离群剔除造成。
    """

    add("## 离群剔除（本次新增能力）")
    add("")
    add(
        "对照口径：第二臂与第三臂共用**同一次 LLM 输出**（temperature=0 + 缓存），"
        "唯一区别是模型给出的 `unrelated` 名单**被无视**还是**被执行**。"
    )
    add("")

    ejected = refine_only["covered_ids"] - llm["covered_ids"]
    add(f"- run_log 报告的剔除帖数：**{llm['ejected']}**")
    add(f"- 两臂事件成员相减，实际从事件里消失的帖子：**{len(ejected)}**")
    add("")

    before = {title: set(ids) for title, ids in refine_only["note_ids_by_event"]}
    after = {title: set(ids) for title, ids in llm["note_ids_by_event"]}
    add("| 事件（剔除前） | 剔除前帖数 | 剔除后帖数 | 被剔走的帖子 |")
    add("| --- | ---: | ---: | --- |")
    for title, ids in before.items():
        lost = ids - after.get(title, set())
        if not lost:
            continue
        add(
            f"| {title} | {len(ids)} | {len(after.get(title, set()))} | "
            + "；".join(f"`{note_id}` {TEXTS.get(note_id, '')[:24]}" for note_id in sorted(lost))
            + " |"
        )
    add("")

    add("### 火灾事件的成员与时间跨度")
    add("")
    add("| 臂 | 事件标题 | 帖数 | 时间跨度 | 起止 |")
    add("| --- | --- | ---: | ---: | --- |")
    for name, item in [("+LLM 精修（无剔除）", refine_only), ("+LLM 精修 + 离群剔除", llm)]:
        found = fire_event(item)
        if not found:
            add(f"| {name} | （未找到火灾事件） | | | |")
            continue
        title, note_ids = found
        span, first, last = event_span_days(note_ids, times)
        add(f"| {name} | {title} | {len(note_ids)} | **{span} 天** | {first} ~ {last} |")
    add("")


def render_published_defect(add, rows: list[dict], refiner, times: dict[str, str]) -> None:
    """把**线上已发布的**那个火灾事件（4 条代表内容）原样交给真实模型，看它剔不剔。

    走的是核心包真实的 refine_clusters 通道（同一套编号校验 + 剔除上限），不是"直接问模型"
    ——要证的是**这条流水线**会把照片摘掉，而不只是"模型分得清"。
    """

    from backend.agent.public_opinion_core.adapter import processed_posts_to_notes
    from backend.agent.public_opinion_core.llm_refine import refine_clusters
    from backend.agent.public_opinion_core.semantic_clustering import (
        _make_cluster,
        strip_social_noise,
    )
    from backend.agent.public_opinion_core.clustering import note_text

    add("## 缺陷复现：线上已发布事件「东校区宿舍火灾」")
    add("")
    add(
        "这份 fixture 在当前阈值下**复现不出**线上那个簇（照片被 embedding 分到了「零散杂项帖」，"
        "没进火灾簇），但缺陷在线上页面里是真实存在的。因此这里把**线上事件原样的 4 条成员**"
        "喂给真实模型，走核心包真实的精修通道（含编号校验与剔除上限）。"
    )
    add("")

    by_id = {str(row.get("note_id")): row for row in rows}
    picked = [by_id[note_id] for note_id in PUBLISHED_FIRE_EVENT if note_id in by_id]
    notes = processed_posts_to_notes(picked)
    embedder = get_embedder()
    vectors = embedder([strip_social_noise(note_text(note)) for note in notes])
    cluster = _make_cluster([(note, i, list(vec)) for i, (note, vec) in enumerate(zip(notes, vectors))])

    warnings: list[str] = []
    groups, refined, ejected = refine_clusters(
        [cluster], refiner, make_cluster=_make_cluster, min_size=2, warnings=warnings
    )

    span, first, last = event_span_days([n.note_id for n in cluster["notes"]], times)
    add(f"- **剔除前**（线上现状）：{len(cluster['notes'])} 帖，时间跨度 **{span} 天**（{first} ~ {last}）")
    for note in cluster["notes"]:
        add(f"    - {times.get(note.note_id, '?')[:10]} `{note.note_id}` {note.title[:34]}")
    add("")
    add(f"- 模型剔除了 **{ejected}** 条；精修出 {len(groups)} 个子簇：")
    for group in groups:
        ids = [note.note_id for note in group["notes"]]
        span, first, last = event_span_days(ids, times)
        title = group.get("llm_title") or "（无标题：被剔除的离群帖 / 残余簇）"
        kept = "事件" if len(ids) >= EVENT_MIN_CLUSTER_SIZE else f"**不成事件**（< min_cluster_size={EVENT_MIN_CLUSTER_SIZE}，被压制）"
        add(f"    - **{title}** — {len(ids)} 帖，跨度 **{span} 天**（{first} ~ {last}）→ {kept}")
        for note_id in ids:
            add(f"        - {times.get(note_id, '?')[:10]} `{note_id}` {TEXTS.get(note_id, '')[:34]}")
    add("")
    if warnings:
        add("warnings：")
        for warning in warnings:
            add(f"- {warning}")
        add("")


def render(
    corpus: int,
    base: dict,
    refine_only: dict | None,
    llm: dict | None,
    usage: dict,
    times: dict[str, str],
    rows: list[dict],
    refiner=None,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# 消融实验：事件聚类的 LLM 精修 + 离群剔除")
    add("")
    add(f"语料：`{FIXTURE.relative_to(ROOT).as_posix()}`（{corpus} 条 processed_posts 只读快照，不连数据库）")
    add(
        f"参数：cluster={EMBEDDING_CLUSTER_THRESHOLD} merge={EMBEDDING_MERGE_THRESHOLD} "
        f"align={EMBEDDING_ALIGN_THRESHOLD} min_cluster_size={EVENT_MIN_CLUSTER_SIZE} "
        f"refine_min_size={EVENT_REFINE_MIN_SIZE} model={EVENT_LLM_MODEL} temperature=0"
    )
    add("")
    add("## 总览")
    add("")
    add("| 指标 | 纯 embedding | + LLM 精修（无剔除） | + LLM 精修 + 离群剔除 |")
    add("| --- | --- | --- | --- |")
    columns = [item for item in (base, refine_only, llm) if item]

    def row(name: str, values: list[str]) -> None:
        cells = " | ".join(values + ["（未运行）"] * (3 - len(values)))
        add(f"| {name} | {cells} |")

    row("事件数", [str(item["event_count"]) for item in columns])
    row("最大事件（帖数 / 占比）", [f"{item['largest']}（{item['largest_share']:.0%}）" for item in columns])
    row(f"巨簇（>{MEGA_RATIO:.0%} 语料）", [str(len(item["mega"])) for item in columns])
    row("「…相关讨论」套话标题数", [str(len(item["boilerplate_titles"])) for item in columns])
    row(
        f"「{BURIED_EVENT_KEYWORD}调整」独立成事件",
        [("是：" + "、".join(f"{t}（{c} 帖）" for t, c in item["buried_event"])) if item["buried_event"] else "否"
         for item in columns],
    )
    row(
        f"　└ 捞回的作息帖 / 全语料作息帖",
        [f"{item['buried_captured']} / {item['buried_total']}" for item in columns],
    )
    row("　└ 仍埋在巨簇里的作息帖", [str(item["buried_in_mega"]) for item in columns])
    row("被压制的小簇（< min_cluster_size）", [str(item["suppressed"]) for item in columns])
    row("被 LLM 精修的簇数", [str(item["refined_clusters"]) for item in columns])
    row("**被剔除的离群帖**", [str(item["ejected"]) for item in columns])
    row("聚类模式（run_log）", [str(item["clustering_mode"]) for item in columns])
    add("")

    if refine_only and llm:
        render_ejection(add, refine_only, llm, times)
    if refiner is not None:
        render_published_defect(add, rows, refiner, times)

    arms = [("纯 embedding", base)]
    if refine_only:
        arms.append(("embedding + LLM 精修（无剔除）", refine_only))
    if llm:
        arms.append(("embedding + LLM 精修 + 离群剔除", llm))
    for name, item in arms:
        add(f"## 事件列表：{name}")
        add("")
        add(f"簇大小分布：`{item['sizes']}`（覆盖 {item['covered']}/{corpus} 帖）")
        add("")
        add("| 帖数 | 事件标题 | 来源 |")
        add("| ---: | --- | --- |")
        for title, count, refined in item["events"]:
            add(f"| {count} | {title} | {'LLM 精修' if refined else 'embedding'} |")
        add("")
        if item["warnings"]:
            add("降级/告警：")
            for warning in item["warnings"]:
                add(f"- {warning}")
            add("")

    if llm:
        add("## LLM 用量")
        add("")
        add(
            f"- 调用 {usage['calls']} 次（缓存命中 {usage['cache_hits']}，失败 {usage['errors']}）、"
            f"token {usage['total_tokens']}、耗时 {usage['duration_ms']} ms"
        )
        add(f"- 精修簇数：{llm['refined_clusters']}（只精修 ≥ {EVENT_REFINE_MIN_SIZE} 帖的簇）")
        add("")
    add("> 由 `python scripts/ablation_event_refine.py` 生成。")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ablation: embedding-only vs embedding+LLM event clustering")
    parser.add_argument("--no-llm", action="store_true", help="只跑 embedding 臂（无网络时用）")
    parser.add_argument("--report", default=str(REPORT), help="报告写到哪里")
    args = parser.parse_args()

    rows = load_rows()
    corpus = len(rows)
    if get_embedder() is None:
        print("[FAIL] 没有可用的 embedder（sentence-transformers 未安装 / EMBEDDING_ENABLED=0）")
        return 1

    TEXTS.update({str(row.get("note_id") or ""): str(row.get("title") or row.get("content") or "") for row in rows})
    times = {
        str(row.get("note_id") or ""): str(row.get("publish_time") or "")
        for row in rows
        if row.get("publish_time")
    }

    buried_ids = buried_note_ids(rows)
    print(f"[1/3] 纯 embedding（{corpus} 条，其中作息帖 {len(buried_ids)} 条）…")
    base = stats(run_arm(rows, refiner=None), corpus, buried_ids)

    refine_only = llm = refiner = None
    reset_llm_usage()
    if not args.no_llm:
        refiner = get_cluster_refiner()
        if refiner is None:
            print("[WARN] 未配置 EVENT_LLM_API_KEY，跳过 LLM 臂")
        else:
            print(f"[2/3] embedding + LLM 精修（无离群剔除，model={EVENT_LLM_MODEL}, temperature=0）…")
            refine_only = stats(run_arm(rows, refiner=without_ejection(refiner)), corpus, buried_ids)
            # 同一批帖子、同一个模型、temperature=0 -> 全部命中 call_llm 的缓存：
            # 这一臂不再花钱，且拿到的是**同一份模型输出**，差异只可能来自离群剔除本身。
            print("[3/3] embedding + LLM 精修 + 离群剔除…")
            llm = stats(run_arm(rows, refiner=refiner), corpus, buried_ids)
    usage = get_llm_usage()

    report = render(corpus, base, refine_only, llm, usage, times, rows, refiner)
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
