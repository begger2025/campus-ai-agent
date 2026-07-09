"""问题清单覆盖率验收：逐条检索站内数据，报告命中率（开发期目标 ≥ 80%）。

用法：
  .venv/Scripts/python.exe scripts/check_question_coverage.py --file questions.txt

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
from backend.services.intent_router import route_intent  # noqa: E402
from backend.services.public_opinion_adapter import query_agent_rows  # noqa: E402


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
    args = parser.parse_args()

    questions = Path(args.file).read_text(encoding="utf-8").splitlines()
    init_db()
    db = SessionLocal()
    try:
        report = check_coverage(db, questions)
    finally:
        db.close()

    print(f"覆盖率：{report.hits}/{report.total} = {report.rate:.0%}（开发期目标 ≥ 80%）")
    if report.misses:
        print("未命中的问题（优先安排爬取）：")
        for question in report.misses:
            print(f"  ✗ {question}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
