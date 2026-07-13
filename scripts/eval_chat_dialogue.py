"""多轮对话评测：话题连续性 + 话语行为分类，七轮真实对话回归。

评测集来自 2026-07-13 用户的真实七轮对话（当时四处翻车：省略背景词后话题丢失、
陈述被当成风险问题、新名词劫持话题、泛问被旧话题绑架）。每次改路由提示词或
话题状态机后跑一遍，防止修东墙塌西墙。

temperature=0 + JsonLlmCache => 同版本提示词下任何人重跑结果一致。

    python scripts/eval_chat_dialogue.py
    python scripts/eval_chat_dialogue.py --json > docs/data/eval_chat_dialogue.json

只读，不写任何表。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import SessionLocal  # noqa: E402
from backend.services.opinion_chat_service import OpinionChatService, reset_chat_memory  # noqa: E402


def _kw_has(fragment):
    return lambda r: fragment in (r["keyword"] or "")


def _kw_empty(r):
    return not r["keyword"]


def _intent_is(name):
    return lambda r: r["intent"] == name


def _intent_not(name):
    return lambda r: r["intent"] != name


def _events_eq(n):
    return lambda r: r["event_count"] == n


# (提问, [(期望描述, 断言)])——期望针对的是**路由与检索层**的可判定结果，
# 不评判生成文本的措辞（那由人读）。
CONVERSATION = [
    (
        "最近有什么热点？",
        [("泛问检索全部（8 个已发布事件）", _events_eq(8)), ("话题为空", _kw_empty)],
    ),
    (
        "请给我一份东校宿舍搬迁的舆情简报",
        [("切换到搬迁话题", _kw_has("搬迁")), ("简报意图", _intent_is("report"))],
    ),
    (
        "你觉得为什么学生会产生负面的情绪",
        [
            ("省略背景词仍延续搬迁话题（continue）", _kw_has("搬迁")),
            ("检索聚焦单事件", _events_eq(1)),
        ],
    ),
    (
        "关键是我搬到的新宿舍，条件比原来的还差",
        [
            ("陈述处境不进风险预警", _intent_not("risk_analysis")),
            ("「新宿舍」不劫持话题", _kw_has("搬迁")),
        ],
    ),
    (
        "我能和辅导员反馈吗",
        [
            ("求助不进风险预警", _intent_not("risk_analysis")),
            ("话题仍是搬迁", _kw_has("搬迁")),
        ],
    ),
    (
        "可是辅导员不理我怎么办",
        [("追问不进风险预警", _intent_not("risk_analysis")), ("话题仍是搬迁", _kw_has("搬迁"))],
    ),
    (
        "最近有什么热点？",
        [("聊天中途的泛问跳出话题（global）", _kw_empty), ("检索回到全部", _events_eq(8))],
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON 供报告引用")
    args = parser.parse_args()

    # 预热 embedding（语义层样例会用到），别让第一问白背 26 秒模型加载
    from backend.services.embedding import get_embedder

    embedder = get_embedder()
    if embedder is not None:
        embedder(["预热"])

    reset_chat_memory()
    db = SessionLocal()
    turns = []
    passed = total = 0
    try:
        service = OpinionChatService(db)
        for message, expectations in CONVERSATION:
            started = time.perf_counter()
            data = service.chat(message, user_id="eval-dialogue")
            record = {
                "message": message,
                "seconds": round(time.perf_counter() - started, 1),
                "intent": data.get("intent"),
                "keyword": data.get("keyword") or "",
                "event_count": len(data.get("events") or []),
                "checks": [],
            }
            for label, check in expectations:
                ok = bool(check(record))
                record["checks"].append({"label": label, "pass": ok})
                passed += ok
                total += 1
            turns.append(record)
    finally:
        db.close()

    if args.json:
        print(json.dumps({"score": f"{passed}/{total}", "turns": turns}, ensure_ascii=False, indent=2))
        return

    print(f"七轮对话评测：{passed}/{total} 项通过\n")
    for turn in turns:
        marks = "  ".join(("PASS" if c["pass"] else "FAIL") + " " + c["label"] for c in turn["checks"])
        print(f"[{turn['intent']:<16s} 话题:{turn['keyword'] or '-':<8s} 事件:{turn['event_count']}] "
              f"{turn['message']}  ->  {marks}")


if __name__ == "__main__":
    main()
