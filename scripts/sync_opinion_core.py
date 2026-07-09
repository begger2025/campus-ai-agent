"""从舆情子项目单向同步核心与服务层（子项目是唯一改动源）。

- public_opinion_core/：13 个核心文件原样复制（多余文件删除）
- services 白名单文件（见 PORTED_SERVICES）：复制时自动改写导入前缀
    from app.config import ...      -> from backend.services.llm_config import ...
    from app.services.X import ...  -> from backend.services.X import ...
  主项目专属服务（opinion_chat_service / opinion_report / llm_config /
  public_opinion_adapter 等）不在白名单内，永远不会被覆盖。

用 Python 而不是 bat 做同步：中文路径在 cmd 批处理里有代码页问题。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SUB_ROOT = Path(r"D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\app")
MAIN_ROOT = Path(__file__).resolve().parent.parent / "backend"

CORE_SUB = SUB_ROOT / "public_opinion_core"
CORE_MAIN = MAIN_ROOT / "agent" / "public_opinion_core"

SERVICES_SUB = SUB_ROOT / "services"
SERVICES_MAIN = MAIN_ROOT / "services"

# 子项目改动会自动跟过来的服务文件；新增共享服务时在这里登记。
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

IMPORT_REWRITES = [
    ("from app.config import", "from backend.services.llm_config import"),
    ("from app.services.", "from backend.services."),
]


def sync_core() -> tuple[int, int]:
    sub_files = {p.name for p in CORE_SUB.glob("*.py")}
    for name in sorted(sub_files):
        shutil.copy2(CORE_SUB / name, CORE_MAIN / name)
    removed = 0
    for p in CORE_MAIN.glob("*.py"):
        if p.name not in sub_files:
            p.unlink()
            removed += 1
    return len(sub_files), removed


def sync_services() -> tuple[int, list[str]]:
    changed = []
    for name in PORTED_SERVICES:
        source = SUB_ROOT.joinpath("services", name)
        if not source.exists():
            print(f"  WARNING: 子项目缺少 {name}，跳过")
            continue
        text = source.read_text(encoding="utf-8")
        for old, new in IMPORT_REWRITES:
            text = text.replace(old, new)
        target = SERVICES_MAIN / name
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
            changed.append(name)
    return len(PORTED_SERVICES), changed


def main() -> int:
    for path in (CORE_SUB, SERVICES_SUB):
        if not path.is_dir():
            print(f"source not found: {path}")
            return 1
    core_count, removed = sync_core()
    service_count, changed = sync_services()
    print(f"core: copied {core_count}, removed {removed}")
    print(f"services: {service_count} 个白名单文件，{'更新 ' + '、'.join(changed) if changed else '全部已是最新'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
