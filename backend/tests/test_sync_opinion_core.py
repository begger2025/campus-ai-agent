"""同步脚本的安全性回归测试。

核心不变量（这些断言存在的原因是一次真实事故）：主项目是唯一运行源，
`scripts/sync_opinion_core.py` 只能把主项目的改动**反向移植**到子项目，
**任何情况下都不允许写入 / 删除主项目的文件**。

所有用例都在 tmp 目录上跑，不碰任何一个真实仓库。
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.sync_opinion_core import (
    IMPORT_REWRITES,
    apply_plan,
    build_plan,
    find_residual_main_imports,
    render_plan,
    rewrite_imports,
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def tree_digest(root: Path) -> dict[str, str]:
    """目录内容指纹：用于断言主项目一个字节都没被改过。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class Layout:
    """一个假的双仓布局：main/ 是源，sub/ 是被写入的镜像。"""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.core_main = tmp / "main" / "backend" / "agent" / "public_opinion_core"
        self.services_main = tmp / "main" / "backend" / "services"
        self.core_sub = tmp / "sub" / "backend" / "app" / "public_opinion_core"
        self.services_sub = tmp / "sub" / "backend" / "app" / "services"
        for d in (self.core_main, self.services_main, self.core_sub, self.services_sub):
            d.mkdir(parents=True, exist_ok=True)

    def plan(self, ported_services=("llm_client.py",)):
        return build_plan(
            core_main=self.core_main,
            core_sub=self.core_sub,
            services_main=self.services_main,
            services_sub=self.services_sub,
            ported_services=list(ported_services),
        )


class RewriteImportsTest(unittest.TestCase):
    """MAIN -> SUB 的导入前缀改写（与旧脚本方向相反）。"""

    def test_llm_config_maps_to_app_config_not_app_services(self):
        # 顺序陷阱：若先套用 backend.services.* -> app.services.*，
        # llm_config 会被改成 app.services.llm_config —— 子项目没有这个模块。
        text = "from backend.services.llm_config import (\n    OPENAI_MODEL,\n)\n"
        self.assertEqual(
            rewrite_imports(text),
            "from app.config import (\n    OPENAI_MODEL,\n)\n",
        )

    def test_llm_config_single_line_import(self):
        text = "from backend.services.llm_config import REACT_MAX_STEPS\n"
        self.assertEqual(rewrite_imports(text), "from app.config import REACT_MAX_STEPS\n")

    def test_other_services_map_to_app_services(self):
        text = "from backend.services.prompt_guard import guard_payload\n"
        self.assertEqual(rewrite_imports(text), "from app.services.prompt_guard import guard_payload\n")

    def test_indented_function_local_import_is_rewritten(self):
        text = "    def f():\n        from backend.services.citations import CITATION_INSTRUCTION\n"
        self.assertIn("from app.services.citations import CITATION_INSTRUCTION", rewrite_imports(text))

    def test_relative_core_imports_are_untouched(self):
        # 核心包两边都只用相对导入，改写必须是恒等变换。
        text = "from .schemas import OpinionNote\nfrom .normalizer import note_text\n"
        self.assertEqual(rewrite_imports(text), text)

    def test_prose_comment_mentioning_backend_is_not_rewritten(self):
        # platform_weights.py 的注释里出现 "backend.services.llm_config"，
        # 但那不是 import 语句，改写不能碰它（改写必须锚定 "from X import"）。
        text = "# .env 由 backend.database / backend.services.llm_config 在进程启动时加载\n"
        self.assertEqual(rewrite_imports(text), text)

    def test_rewrite_output_has_no_residual_main_imports(self):
        text = (
            "from backend.services.llm_config import OPENAI_MODEL\n"
            "from backend.services.prompt_guard import guard_payload\n"
        )
        self.assertEqual(find_residual_main_imports(rewrite_imports(text)), [])

    def test_residual_detector_flags_unmapped_main_import(self):
        # 没有映射规则的主项目导入（如 backend.database）必须被检出，而不是悄悄写进子项目。
        self.assertEqual(
            find_residual_main_imports("from backend.database import Base\n"),
            ["from backend.database import Base"],
        )

    def test_rewrites_are_main_to_sub(self):
        # 旧脚本的方向（app.* -> backend.*）必须已经不存在。
        for old, new in IMPORT_REWRITES:
            self.assertTrue(old.startswith("from backend."), f"源前缀必须是主项目: {old}")
            self.assertTrue(new.startswith("from app."), f"目标前缀必须是子项目: {new}")


class PlanTest(unittest.TestCase):
    def test_main_only_file_is_copied_into_sub_not_deleted_from_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "platform_weights.py", "from .schemas import OpinionNote\n")
            plan = lay.plan(ported_services=[])

            actions = {a.name: a for a in plan.actions}
            self.assertIn("platform_weights.py", actions)
            act = actions["platform_weights.py"]
            self.assertEqual(act.action, "create")
            self.assertEqual(act.target, lay.core_sub / "platform_weights.py")
            self.assertEqual(act.source, lay.core_main / "platform_weights.py")

    def test_no_action_ever_targets_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "scoring.py", "x = 1\n")
            write(lay.core_sub / "scoring.py", "x = 0\n")
            write(lay.services_main / "llm_client.py", "from backend.services.prompt_guard import g\n")
            plan = lay.plan()

            main_root = Path(tmp) / "main"
            for act in plan.actions:
                self.assertFalse(
                    act.target.is_relative_to(main_root),
                    f"同步动作把主项目当成了写入目标: {act.target}",
                )
                self.assertTrue(act.source.is_relative_to(main_root))

    def test_sub_only_file_is_reported_stale_but_not_an_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_sub / "legacy_only_in_sub.py", "x = 1\n")
            plan = lay.plan(ported_services=[])
            self.assertEqual([p.name for p in plan.stale_in_sub], ["legacy_only_in_sub.py"])
            self.assertEqual(plan.actions, [])

    def test_identical_file_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "memory.py", "x = 1\n")
            write(lay.core_sub / "memory.py", "x = 1\n")
            plan = lay.plan(ported_services=[])
            self.assertEqual([a.action for a in plan.actions], ["unchanged"])


class ApplyPlanTest(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "platform_weights.py", "from .schemas import OpinionNote\n")
            write(lay.core_main / "scoring.py", "new = 1\n")
            write(lay.core_sub / "scoring.py", "old = 1\n")
            before = tree_digest(Path(tmp))

            plan = lay.plan(ported_services=[])
            written = apply_plan(plan, dry_run=True)

            self.assertEqual(tree_digest(Path(tmp)), before, "dry-run 不允许产生任何文件变化")
            self.assertEqual(
                sorted(p.name for p in written),
                ["platform_weights.py", "scoring.py"],
                "dry-run 必须报告将要写入的文件",
            )

    def test_apply_writes_sub_and_leaves_main_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "platform_weights.py", "from .schemas import OpinionNote\n")
            write(lay.services_main / "llm_client.py", "from backend.services.llm_config import OPENAI_MODEL\n")
            write(lay.services_sub / "llm_client.py", "stale\n")
            main_before = tree_digest(Path(tmp) / "main")

            plan = lay.plan()
            apply_plan(plan, dry_run=False)

            self.assertEqual(tree_digest(Path(tmp) / "main"), main_before, "主项目必须一个字节都没变")
            # 主项目独有文件被复制进子项目（而不是从主项目删掉）
            self.assertTrue((lay.core_main / "platform_weights.py").exists())
            self.assertEqual(
                (lay.core_sub / "platform_weights.py").read_text(encoding="utf-8"),
                "from .schemas import OpinionNote\n",
            )
            # 服务层写入的是子项目风格的导入
            ported = (lay.services_sub / "llm_client.py").read_text(encoding="utf-8")
            self.assertEqual(ported, "from app.config import OPENAI_MODEL\n")
            self.assertEqual(find_residual_main_imports(ported), [])

    def test_sub_only_file_survives_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "scoring.py", "x = 1\n")
            legacy = write(lay.core_sub / "legacy_only_in_sub.py", "keep me\n")

            apply_plan(lay.plan(ported_services=[]), dry_run=False)

            self.assertTrue(legacy.exists(), "默认不得删除子项目独有文件（破坏性默认正是要修掉的 bug）")
            self.assertEqual(legacy.read_text(encoding="utf-8"), "keep me\n")

    def test_prune_is_opt_in_and_only_touches_sub(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "scoring.py", "x = 1\n")
            legacy = write(lay.core_sub / "legacy_only_in_sub.py", "bye\n")
            plan = lay.plan(ported_services=[])

            # dry-run + prune：只报告，不删
            apply_plan(plan, dry_run=True, prune_sub=True)
            self.assertTrue(legacy.exists())

            apply_plan(plan, dry_run=False, prune_sub=True)
            self.assertFalse(legacy.exists())

    def test_apply_refuses_action_targeting_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "scoring.py", "x = 1\n")
            plan = lay.plan(ported_services=[])
            # 人为把目标指回主项目：脚本必须拒绝执行，而不是照做。
            plan.actions[0].target = lay.core_main / "scoring.py"
            with self.assertRaises(ValueError):
                apply_plan(plan, dry_run=False)

    def test_render_plan_lists_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "platform_weights.py", "x = 1\n")
            text = render_plan(lay.plan(ported_services=[]))
            self.assertIn("platform_weights.py", text)


class CliTest(unittest.TestCase):
    def test_default_invocation_is_dry_run(self):
        """不加参数就跑 = 只预演。真实同步必须显式 --apply。"""
        from scripts import sync_opinion_core as mod

        with tempfile.TemporaryDirectory() as tmp:
            lay = Layout(Path(tmp))
            write(lay.core_main / "platform_weights.py", "x = 1\n")
            before = tree_digest(Path(tmp))

            rc = mod.main(
                [],
                core_main=lay.core_main,
                core_sub=lay.core_sub,
                services_main=lay.services_main,
                services_sub=lay.services_sub,
                ported_services=[],
            )

            self.assertEqual(rc, 0)
            self.assertEqual(tree_digest(Path(tmp)), before, "默认调用必须是 dry-run")


class SourceSafetyTest(unittest.TestCase):
    """脚本源码本身不得再具备"删除/写入主项目"的能力。"""

    def test_script_source_has_no_unlink_of_main(self):
        src = Path(__file__).resolve().parents[2] / "scripts" / "sync_opinion_core.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("CORE_MAIN / name", text)
        self.assertNotIn("SERVICES_MAIN / name", text)
        # 唯一允许出现的删除必须发生在子项目侧，且由 prune 开关保护
        self.assertNotIn("shutil.rmtree", text)


if __name__ == "__main__":
    unittest.main()
