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

# 巨簇judge：一个事件吃掉超过 20% 的语料，基本可以断定它不是"一件事"。
MEGA_RATIO = 0.20

# 要找回的那件真实事件（20 帖的校园争议，纯 embedding 下从未独立出现过）。
BURIED_EVENT_KEYWORD = "作息"

# 当前缺陷的指纹：词频 top-1 命名法产出的套话标题。
BOILERPLATE = "相关讨论"


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
        "warnings": list(result.warnings),
        "events": [
            (event.title, event.source_count, bool(event.extra.get("refined_by")))
            for event in sorted(result.events, key=lambda e: -e.source_count)
        ],
    }


def render(corpus: int, base: dict, llm: dict | None, usage: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add("# 消融实验：事件聚类的 LLM 精修")
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
    add("| 指标 | 纯 embedding | embedding + LLM 精修 |")
    add("| --- | --- | --- |")
    columns = [base, llm] if llm else [base]

    def row(name: str, values: list[str]) -> None:
        cells = " | ".join(values + ["（未运行）"] * (2 - len(values)))
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
    row("聚类模式（run_log）", [str(item["clustering_mode"]) for item in columns])
    add("")

    for name, item in [("纯 embedding", base)] + ([("embedding + LLM 精修", llm)] if llm else []):
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

    buried_ids = buried_note_ids(rows)
    print(f"[1/2] 纯 embedding（{corpus} 条，其中作息帖 {len(buried_ids)} 条）…")
    base = stats(run_arm(rows, refiner=None), corpus, buried_ids)

    llm = None
    reset_llm_usage()
    if not args.no_llm:
        refiner = get_cluster_refiner()
        if refiner is None:
            print("[WARN] 未配置 EVENT_LLM_API_KEY，跳过 LLM 臂")
        else:
            print(f"[2/2] embedding + LLM 精修（model={EVENT_LLM_MODEL}, temperature=0）…")
            llm = stats(run_arm(rows, refiner=refiner), corpus, buried_ids)
    usage = get_llm_usage()

    report = render(corpus, base, llm, usage)
    Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    print(f"[OK] 报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
