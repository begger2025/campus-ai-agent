"""消融：LLM 裁决层对检索准确率的贡献。

    纯字面（LIKE）        -> 基线
    + 语义（余弦）        -> 认得出改写
    + LLM 裁决（级联）    -> 判得出「像」和「是」的区别

在真实的已发布事件上跑，用 temperature=0 + JsonLlmCache，任何人重跑都得到同样结果。

    python scripts/ablation_event_judge.py
    python scripts/ablation_event_judge.py --json > docs/data/ablation_event_judge.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from backend.database import SessionLocal  # noqa: E402
from backend.services import event_read_model  # noqa: E402
from backend.services.event_read_model import query_published_events  # noqa: E402


# 评测集：9 个「该命中的改写」+ 5 个「该拒绝的」。
# 改写覆盖四种真实的说法差异：少字（东校 vs 东校区）、换词（着火 vs 火情）、
# 词序（搬宿舍 vs 宿舍搬迁）、完全换说法（论文造假 vs 康某论文调查）。
EVAL_SET: list[tuple[str, str | None]] = [
    ("东校宿舍搬迁", "东校区宿舍搬迁"),  # 少一个「区」字
    ("东校区换宿舍", "东校区宿舍搬迁"),  # 换词
    ("搬宿舍", "东校区宿舍搬迁"),  # 词序颠倒
    ("宿舍着火", "中大宿舍火情通报"),  # 着火 vs 火情
    ("宿舍起火", "中大宿舍火情通报"),
    ("宿舍火灾", "中大宿舍火情通报"),
    ("课间时间缩短", "中大课间缩短争议"),
    ("论文造假", "中大康某论文调查"),  # 完全换说法 —— 余弦 0.54，栽在这
    ("举报副院长", "耿同学举报副院长"),
    ("食堂", None),  # 库里没有食堂事件
    ("图书馆", None),
    ("宿舍热水", None),  # 余弦 0.56 —— 比「论文造假」还高，但它不该命中
    ("天气", None),
    ("考研", None),
]

ARMS = [
    ("① 纯字面 LIKE", {"semantic": False, "judge": False}),
    ("② + 语义（余弦）", {"semantic": True, "judge": False}),
    ("③ + LLM 裁决（级联）", {"semantic": True, "judge": True}),
]


def run_arm(db, semantic: bool, judge: bool) -> tuple[int, float, list[str]]:
    """跑一个消融臂，返回（正确数, 总耗时秒, 错例）。"""

    import unittest.mock as mock

    event_read_model.reset_title_embeddings()
    wrong: list[str] = []
    correct = 0
    started = time.perf_counter()

    with mock.patch.object(event_read_model, "EVENT_SEMANTIC_MATCH_ENABLED", semantic), mock.patch.object(
        event_read_model, "EVENT_JUDGE_ENABLED", judge
    ):
        for question, expected in EVAL_SET:
            events = query_published_events(db, keyword=question, limit=1)
            got = events[0].title if events else None
            if got == expected:
                correct += 1
            else:
                wrong.append(f"{question} → {got or '（拒绝）'}（应为 {expected or '拒绝'}）")

    return correct, time.perf_counter() - started, wrong


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON 供报告引用")
    args = parser.parse_args()

    db = SessionLocal()
    published = db.execute(
        text("SELECT COUNT(*) FROM public_events WHERE status='published'")
    ).scalar()

    # 先把 embedding 模型加载好，再计时。不预热的话，第一个用到它的臂会白背 26 秒的
    # 模型冷加载，跑出「做的事更多的臂反而更快」这种一看就假的数——那种数拿去答辩
    # 会被当场拆穿。（生产里这 26 秒由应用启动时的后台预热吸收，见 embedding.warm_up。）
    from backend.services.embedding import get_embedder

    embedder = get_embedder()
    if embedder is not None:
        started = time.perf_counter()
        embedder(["预热"])
        print(f"（embedding 模型预热完毕，耗时 {time.perf_counter() - started:.1f}s，不计入下表）\n")

    results = []
    for label, flags in ARMS:
        correct, elapsed, wrong = run_arm(db, **flags)
        results.append(
            {
                "arm": label,
                "correct": correct,
                "total": len(EVAL_SET),
                "seconds": round(elapsed, 1),
                "wrong": wrong,
            }
        )
    db.close()

    if args.json:
        print(
            json.dumps(
                {"published_events": published, "eval_size": len(EVAL_SET), "arms": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(f"评测集 {len(EVAL_SET)} 条（9 个该命中的改写 + 5 个该拒绝的）")
    print(f"候选事件 {published} 个（已发布）\n")
    print(f"{'消融臂':<22s} {'准确率':>8s} {'总耗时':>8s}  错例")
    print("-" * 84)
    for r in results:
        wrong = "；".join(r["wrong"][:2]) if r["wrong"] else "全对"
        print(f"{r['arm']:<22s} {r['correct']}/{r['total']:<6d} {r['seconds']:>7.1f}s  {wrong}")
    print("-" * 84)
    print(
        "\n结论：算术（余弦）救得了「改写」，救不了「像 vs 是」——"
        "「论文造假」0.54 分该命中，「宿舍热水」0.56 分该拒绝，"
        "**该命中的比该拒绝的分还低**，没有阈值能分开。这一层必须由判断来做。"
    )


if __name__ == "__main__":
    main()
