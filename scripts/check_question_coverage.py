"""问题清单覆盖率验收：逐条检索站内数据，报告命中率（开发期目标 ≥ 80%）。

用法：
  .venv/Scripts/python.exe scripts/check_question_coverage.py --file questions.txt [--no-llm]

覆盖率低于 COVERAGE_TARGET 时退出码为 1（可作验收门）。

设计见 docs/superpowers/specs/2026-07-10-keyword-recommendation-design.md 第 7.3 节。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, interpolate=False)

from backend.database import SessionLocal, init_db  # noqa: E402

# _route_by_rules 是私有函数；开发期 CLI 借它实现 --no-llm 离线路由，属可接受的取舍。
from backend.services.intent_router import _route_by_rules, route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402

COVERAGE_TARGET = 0.8  # 开发期验收线：问题清单站内覆盖率


@dataclass
class CoverageReport:
    total: int = 0
    hits: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


def check_coverage(db, questions, *, route=route_intent) -> CoverageReport:
    """逐条问题：路由提取话题词（空则用全句）检索，命中≥1 条算覆盖。"""

    report = CoverageReport()
    for question in questions:
        question = (question or "").strip()
        if not question or question.startswith("#"):
            continue
        report.total += 1
        routed = route(question)
        keyword = (routed.keyword or "").strip() or question
        rows = query_agent_rows(db, keyword=keyword, platforms=None, limit=1)
        if rows:
            report.hits += 1
        else:
            report.misses.append(question)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="问题清单站内覆盖率验收")
    parser.add_argument("--file", required=True, help="问题清单文件，每行一个问题")
    parser.add_argument("--no-llm", action="store_true", help="只用规则路由，不发 LLM 调用")
    args = parser.parse_args()

    route = _route_by_rules if args.no_llm else route_intent
    print(f"路由方式：{'规则（离线）' if args.no_llm else 'LLM 优先（无 key 时自动规则兜底）'}")

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        report = check_coverage(db, questions, route=route)
    finally:
        db.close()

    print(f"覆盖率：{report.hits}/{report.total} = {report.rate:.0%}（开发期目标 ≥ {COVERAGE_TARGET:.0%}）")
    if report.misses:
        print("未命中的问题（优先安排爬取）：")
        for question in report.misses:
            print(f"  ✗ {question}")
    # 验收门：低于目标返回非零，供 CI/脚本判定
    return 0 if report.rate >= COVERAGE_TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
