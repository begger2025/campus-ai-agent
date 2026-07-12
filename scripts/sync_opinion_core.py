"""把主项目的核心/服务层反向移植（back-port）到舆情子项目。

方向：**主项目 -> 子项目**，且只有这一个方向。

    主项目 backend/agent/public_opinion_core   = 唯一运行源（single source of truth）
    子项目 campus-opinion-agent                 = 算法参考 / 回归测试镜像

历史教训（2026-07-12）：本脚本原来是反着的——它把子项目当源，
`shutil.copy2(SUB -> MAIN)` 之后还会把"子项目没有的文件"从主项目**删掉**。
真跑一次就会删掉 `platform_weights.py`、并用旧版覆盖 heat_rank / 质心合并 /
min_cluster_size 等一整天的主项目改动。现在这个能力已经从文件里彻底移除：
本脚本不含任何写入或删除主项目路径的代码，`apply_plan()` 还会在运行时
校验每个写入目标都落在子项目目录内，否则直接 ValueError。

安全默认值：
- 不加参数 = dry-run，只打印将要在子项目里创建/覆盖的文件，不写任何东西。
- 真正执行需要显式 `--apply`。
- 子项目里"主项目没有的文件"**默认保留**，只在报告里列出；确实要删必须显式 `--prune-sub`。

导入前缀改写（主项目写法 -> 子项目写法，与旧脚本相反）：

    from backend.services.llm_config import ...  -> from app.config import ...
    from backend.services.X import ...           -> from app.services.X import ...

注意顺序：llm_config 规则必须排在前面，否则会被泛化规则改成
`app.services.llm_config`（子项目没有这个模块）。核心包两边都只用相对导入，
改写对它是恒等变换，保留只是为了将来有人在核心里写绝对导入时能兜住。

用 Python 而不是 bat 做同步：中文路径在 cmd 批处理里有代码页问题。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SUB_ROOT = Path(r"D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\app")
MAIN_ROOT = Path(__file__).resolve().parent.parent / "backend"

# 源（只读）
CORE_MAIN = MAIN_ROOT / "agent" / "public_opinion_core"
SERVICES_MAIN = MAIN_ROOT / "services"

# 目标（唯一可写的一侧）
CORE_SUB = SUB_ROOT / "public_opinion_core"
SERVICES_SUB = SUB_ROOT / "services"

# 两边共享的服务文件；主项目新增共享服务时在这里登记。
# 主项目专属服务（opinion_chat_service / opinion_report / llm_config /
# public_opinion_adapter 等）不在白名单内，永远不会被移植到子项目。
PORTED_SERVICES = [
    "llm_client.py",
    "prompt_guard.py",
    "sentiment_llm.py",
    "embedding.py",
    "intent_router.py",
    "react_loop.py",
    "critic.py",
    "citations.py",
]

# 主项目写法 -> 子项目写法。顺序敏感：更具体的 llm_config 必须在前。
IMPORT_REWRITES = [
    ("from backend.services.llm_config import", "from app.config import"),
    ("from backend.services.", "from app.services."),
]

# 改写后仍残留的主项目绝对导入（例如 backend.database）——没有映射规则，
# 写进子项目就是坏代码，必须报出来让人处理。
_RESIDUAL_MAIN_IMPORT = re.compile(r"^[ \t]*(?:from|import)[ \t]+backend\..*$", re.MULTILINE)


def rewrite_imports(text: str) -> str:
    """把主项目的导入前缀改写成子项目的写法。"""
    for old, new in IMPORT_REWRITES:
        text = text.replace(old, new)
    return text


def find_residual_main_imports(text: str) -> list[str]:
    """返回改写后仍然指向主项目包的 import 行（应为空）。"""
    return [m.group(0).strip() for m in _RESIDUAL_MAIN_IMPORT.finditer(text)]


@dataclass
class FileAction:
    kind: str  # "core" | "service"
    name: str
    source: Path  # 主项目（只读）
    target: Path  # 子项目（唯一写入侧）
    action: str  # "create" | "overwrite" | "unchanged"
    payload: str  # 已完成导入改写、将要写入的内容
    residual: list[str] = field(default_factory=list)


@dataclass
class SyncPlan:
    actions: list[FileAction]
    stale_in_sub: list[Path]  # 子项目有、主项目没有的文件（默认只报告，不删）
    sub_roots: tuple[Path, ...]
    missing_sources: list[str] = field(default_factory=list)

    @property
    def writes(self) -> list[FileAction]:
        return [a for a in self.actions if a.action in ("create", "overwrite")]


def _plan_file(kind: str, source: Path, target: Path) -> FileAction:
    text = rewrite_imports(source.read_text(encoding="utf-8"))
    if not target.exists():
        action = "create"
    elif target.read_text(encoding="utf-8") != text:
        action = "overwrite"
    else:
        action = "unchanged"
    return FileAction(
        kind=kind,
        name=source.name,
        source=source,
        target=target,
        action=action,
        payload=text,
        residual=find_residual_main_imports(text),
    )


def build_plan(
    core_main: Path,
    core_sub: Path,
    services_main: Path,
    services_sub: Path,
    ported_services: list[str] | None = None,
) -> SyncPlan:
    """只读地算出"要往子项目里写什么"。不碰磁盘。"""
    ported = list(PORTED_SERVICES if ported_services is None else ported_services)

    actions: list[FileAction] = []
    missing: list[str] = []

    main_core_names = sorted(p.name for p in core_main.glob("*.py"))
    for name in main_core_names:
        actions.append(_plan_file("core", core_main / name, core_sub / name))

    for name in ported:
        source = services_main / name
        if not source.exists():
            missing.append(f"services/{name}")
            continue
        actions.append(_plan_file("service", source, services_sub / name))

    # 子项目独有的核心文件：只报告。删除是 opt-in（--prune-sub），
    # 因为"默认删除"正是这个脚本原来的致命缺陷。
    stale = [p for p in sorted(core_sub.glob("*.py")) if p.name not in set(main_core_names)]

    return SyncPlan(
        actions=actions,
        stale_in_sub=stale,
        sub_roots=(core_sub.resolve(), services_sub.resolve()),
        missing_sources=missing,
    )


def _assert_targets_sub(plan: SyncPlan, paths: list[Path]) -> None:
    for target in paths:
        resolved = target.resolve()
        if not any(resolved.is_relative_to(root) for root in plan.sub_roots):
            raise ValueError(
                f"拒绝执行：写入/删除目标不在子项目目录内 -> {resolved}。"
                "本脚本永远不会改动主项目。"
            )


def apply_plan(plan: SyncPlan, dry_run: bool = True, prune_sub: bool = False) -> list[Path]:
    """执行计划。dry_run=True 时不产生任何磁盘变化，只返回将要写入的路径。

    无论如何都只会写子项目：每个目标路径先过 `_assert_targets_sub` 校验。
    """
    writes = plan.writes
    prunable = list(plan.stale_in_sub) if prune_sub else []
    _assert_targets_sub(plan, [a.target for a in writes] + prunable)

    if dry_run:
        return [a.target for a in writes]

    written: list[Path] = []
    for act in writes:
        act.target.parent.mkdir(parents=True, exist_ok=True)
        act.target.write_text(act.payload, encoding="utf-8")
        shutil.copystat(act.source, act.target)
        written.append(act.target)
    for path in prunable:
        path.unlink()
    return written


def render_plan(plan: SyncPlan, prune_sub: bool = False) -> str:
    lines: list[str] = []
    for kind, label in (("core", "public_opinion_core"), ("service", "services（白名单）")):
        group = [a for a in plan.actions if a.kind == kind]
        if not group:
            continue
        writes = [a for a in group if a.action != "unchanged"]
        lines.append(f"[{label}] {len(group)} 个源文件，{len(writes)} 个需要回移")
        for act in group:
            mark = {"create": "NEW      ", "overwrite": "OVERWRITE", "unchanged": "same     "}[act.action]
            lines.append(f"  {mark}  {act.name:<24} -> {act.target}")
            if act.residual:
                lines.append(f"            !! 残留主项目导入（无映射规则，请人工处理）: {act.residual}")
    for name in plan.missing_sources:
        lines.append(f"  WARNING: 主项目缺少 {name}，跳过")

    if plan.stale_in_sub:
        verb = "将删除" if prune_sub else "保留（未删除；如需删除加 --prune-sub）"
        lines.append(f"[子项目独有文件] {len(plan.stale_in_sub)} 个，{verb}：")
        for path in plan.stale_in_sub:
            lines.append(f"  {'DELETE' if prune_sub else 'KEEP  '}  {path}")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    core_main: Path = CORE_MAIN,
    core_sub: Path = CORE_SUB,
    services_main: Path = SERVICES_MAIN,
    services_sub: Path = SERVICES_SUB,
    ported_services: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="把主项目 public_opinion_core / 白名单服务反向同步到舆情子项目（主项目是唯一源，只读）。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写入子项目。不加此参数只做 dry-run（默认，安全）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="显式声明 dry-run（默认行为，仅为可读性）。",
    )
    parser.add_argument(
        "--prune-sub",
        action="store_true",
        help="删除子项目里主项目没有的核心文件（默认不删；只影响子项目）。",
    )
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        print("--apply 与 --dry-run 互斥")
        return 2
    dry_run = not args.apply

    for path in (core_main, services_main):
        if not path.is_dir():
            print(f"source (MAIN) not found: {path}")
            return 1
    for path in (core_sub, services_sub):
        if not path.is_dir():
            print(f"target (SUB) not found: {path}")
            return 1

    plan = build_plan(
        core_main=core_main,
        core_sub=core_sub,
        services_main=services_main,
        services_sub=services_sub,
        ported_services=ported_services,
    )

    print("方向：主项目（源，只读） -> 子项目（目标）")
    print(f"  MAIN core     : {core_main}")
    print(f"  MAIN services : {services_main}")
    print(f"  SUB  core     : {core_sub}")
    print(f"  SUB  services : {services_sub}")
    print()
    print(render_plan(plan, prune_sub=args.prune_sub))
    print()

    written = apply_plan(plan, dry_run=dry_run, prune_sub=args.prune_sub)
    if dry_run:
        print(f"DRY-RUN：未写入任何文件。将会在子项目里写 {len(written)} 个文件。")
        print("确认无误后加 --apply 真正执行。")
    else:
        print(f"已写入子项目 {len(written)} 个文件。主项目未被改动。")
        print("请到子项目跑一遍它自己的测试套件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
