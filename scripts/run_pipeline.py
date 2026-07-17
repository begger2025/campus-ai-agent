"""一键数据管线：同步 → 清洗 → 向量 → 事件，四步一条命令。

用法：
  # 全量跑通（最常用）
  .venv/Scripts/python.exe scripts/run_pipeline.py
  # 预览不写库（sync/process 走各自 --dry-run，events 走 --preview，vectors 跳过）
  .venv/Scripts/python.exe scripts/run_pipeline.py --dry-run
  # 顺路刷新已入库帖子的互动量（传给 sync 与 process）
  .venv/Scripts/python.exe scripts/run_pipeline.py --refresh
  # 跳过某些步骤（如轻依赖环境没装 sentence-transformers 时跳过向量构建）
  .venv/Scripts/python.exe scripts/run_pipeline.py --skip vectors

设计约定：
- 失败即停：某步非零退出，后续步骤不跑，汇总表标 not-run；
- 事件生成固定 --limit 0 全量分析，避免"静默截断导致陈旧草稿不归档"；
- 各步复用既有脚本的幂等语义，本脚本只做编排，不引入新的写库路径。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

STEP_ORDER = ("sync", "process", "vectors", "events")


class PipelineError(ValueError):
    """编排参数错误（未知步骤名等）。"""


@dataclass
class Step:
    name: str
    argv: list[str]
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class Summary:
    results: list[tuple[str, str]] = field(default_factory=list)
    failed_step: str | None = None
    exit_code: int = 0


def plan_steps(
    *,
    dry_run: bool = False,
    refresh: bool = False,
    skip: list[str] | None = None,
    limit: int = 100000,
    created_by: str = "pipeline",
) -> list[Step]:
    """规划四步命令行。纯逻辑，可单测。"""
    skip_set = set(skip or [])
    unknown = skip_set - set(STEP_ORDER)
    if unknown:
        raise PipelineError(f"未知步骤名: {sorted(unknown)}；可选 {list(STEP_ORDER)}")

    sync_argv = ["scripts/sync_media_to_raw_posts.py", "--platform", "all", "--limit", str(limit)]
    process_argv = ["scripts/process_raw_posts.py", "--limit", str(limit)]
    vectors_argv = ["scripts/build_post_vectors.py"]
    events_argv = [
        "scripts/generate_public_events.py",
        "--limit", "0",
        "--created-by", created_by,
    ]

    if refresh:
        sync_argv.append("--refresh")
        process_argv.append("--refresh")
    if dry_run:
        sync_argv.append("--dry-run")
        process_argv.append("--dry-run")
        events_argv.append("--preview")

    steps = [
        Step("sync", sync_argv),
        Step("process", process_argv),
        Step("vectors", vectors_argv),
        Step("events", events_argv),
    ]

    for step in steps:
        if step.name in skip_set:
            step.skipped = True
            step.skip_reason = "--skip 指定"
    if dry_run:
        vectors = next(s for s in steps if s.name == "vectors")
        if not vectors.skipped:
            vectors.skipped = True
            vectors.skip_reason = "dry-run 下跳过（向量构建会写 npz 文件，无预览语义）"
    return steps


def _subprocess_runner(step: Step) -> int:
    """真实执行：同解释器跑子脚本，输出直通终端。"""
    cmd = [sys.executable, str(ROOT / step.argv[0]), *step.argv[1:]]
    print(f"\n=== [{step.name}] {' '.join(step.argv)} ===", flush=True)
    completed = subprocess.run(cmd, cwd=ROOT)
    return completed.returncode


def run_steps(steps: list[Step], runner: Callable[[Step], int] = _subprocess_runner) -> Summary:
    """按序执行，失败即停。runner 可注入以便测试。"""
    summary = Summary()
    stopped = False
    for step in steps:
        if stopped:
            summary.results.append((step.name, "not-run"))
            continue
        if step.skipped:
            summary.results.append((step.name, "skipped"))
            continue
        code = runner(step)
        if code == 0:
            summary.results.append((step.name, "ok"))
        else:
            summary.results.append((step.name, f"failed({code})"))
            summary.failed_step = step.name
            summary.exit_code = code
            stopped = True
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="一键数据管线：同步→清洗→向量→事件")
    parser.add_argument("--dry-run", action="store_true", help="预览不写库")
    parser.add_argument("--refresh", action="store_true", help="刷新已入库帖子的互动量（sync/process）")
    parser.add_argument("--skip", default="", help="跳过步骤，逗号分隔：sync,process,vectors,events")
    parser.add_argument("--limit", type=int, default=100000, help="sync/process 单步扫描上限")
    parser.add_argument("--created-by", default="pipeline", help="事件生成的 created_by 标记")
    args = parser.parse_args(argv)

    skip = [s.strip() for s in args.skip.split(",") if s.strip()]
    try:
        steps = plan_steps(
            dry_run=args.dry_run,
            refresh=args.refresh,
            skip=skip,
            limit=args.limit,
            created_by=args.created_by,
        )
    except PipelineError as exc:
        parser.error(str(exc))

    started = time.time()
    summary = run_steps(steps)
    elapsed = time.time() - started

    print("\n===== 管线汇总 =====")
    for name, status in summary.results:
        print(f"  {name:<8} {status}")
    print(f"  总耗时 {elapsed:.1f}s")
    if summary.failed_step:
        print(f"[FAIL] 步骤 {summary.failed_step} 失败，后续步骤未执行。")
    else:
        print("[OK] 管线全部完成。")
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main())
