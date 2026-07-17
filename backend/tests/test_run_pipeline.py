"""一键数据管线 scripts/run_pipeline.py 的编排逻辑测试。

只测纯逻辑（步骤规划 / 跳过 / dry-run 映射 / 失败即停），不真跑子进程。
"""

import unittest

from scripts.run_pipeline import PipelineError, plan_steps, run_steps


class PlanStepsTests(unittest.TestCase):
    def test_default_plan_has_four_steps_in_pipeline_order(self):
        steps = plan_steps()
        self.assertEqual(
            [s.name for s in steps],
            ["sync", "process", "vectors", "events"],
            "管线顺序必须是 同步→清洗→向量→事件",
        )
        by_name = {s.name: s for s in steps}
        self.assertIn("scripts/sync_media_to_raw_posts.py", by_name["sync"].argv[0])
        self.assertIn("--platform", by_name["sync"].argv)
        self.assertIn("all", by_name["sync"].argv)
        self.assertIn("scripts/process_raw_posts.py", by_name["process"].argv[0])
        self.assertIn("scripts/build_post_vectors.py", by_name["vectors"].argv[0])
        self.assertIn("scripts/generate_public_events.py", by_name["events"].argv[0])
        # 事件生成必须全量（--limit 0），避免静默截断
        events_argv = by_name["events"].argv
        self.assertEqual(events_argv[events_argv.index("--limit") + 1], "0")

    def test_dry_run_maps_to_each_scripts_own_preview_flag(self):
        steps = plan_steps(dry_run=True)
        by_name = {s.name: s for s in steps}
        self.assertIn("--dry-run", by_name["sync"].argv)
        self.assertIn("--dry-run", by_name["process"].argv)
        self.assertIn("--preview", by_name["events"].argv)
        self.assertNotIn("--dry-run", by_name["events"].argv)
        # 向量构建没有 dry-run 语义（会写 npz），dry-run 下整步跳过
        self.assertTrue(by_name["vectors"].skipped)

    def test_refresh_only_touches_sync_and_process(self):
        steps = plan_steps(refresh=True)
        by_name = {s.name: s for s in steps}
        self.assertIn("--refresh", by_name["sync"].argv)
        self.assertIn("--refresh", by_name["process"].argv)
        self.assertNotIn("--refresh", by_name["vectors"].argv)
        self.assertNotIn("--refresh", by_name["events"].argv)

    def test_skip_removes_named_steps_and_keeps_order(self):
        steps = plan_steps(skip=["vectors", "events"])
        active = [s.name for s in steps if not s.skipped]
        self.assertEqual(active, ["sync", "process"])

    def test_unknown_skip_name_raises(self):
        with self.assertRaises(PipelineError):
            plan_steps(skip=["no_such_step"])

    def test_limit_flows_into_sync_and_process(self):
        steps = plan_steps(limit=500)
        by_name = {s.name: s for s in steps}
        sync_argv = by_name["sync"].argv
        proc_argv = by_name["process"].argv
        self.assertEqual(sync_argv[sync_argv.index("--limit") + 1], "500")
        self.assertEqual(proc_argv[proc_argv.index("--limit") + 1], "500")


class RunStepsTests(unittest.TestCase):
    def test_fail_fast_stops_at_first_nonzero_and_reports(self):
        calls = []

        def fake_runner(step):
            calls.append(step.name)
            return 0 if step.name != "process" else 2

        steps = plan_steps()
        summary = run_steps(steps, runner=fake_runner)
        self.assertEqual(calls, ["sync", "process"], "process 失败后不得继续跑 vectors/events")
        self.assertEqual(summary.failed_step, "process")
        self.assertEqual(summary.exit_code, 2)
        results = {name: status for name, status in summary.results}
        self.assertEqual(results["sync"], "ok")
        self.assertEqual(results["process"], "failed(2)")
        self.assertEqual(results["vectors"], "not-run")

    def test_all_green_summary(self):
        steps = plan_steps()
        summary = run_steps(steps, runner=lambda step: 0)
        self.assertIsNone(summary.failed_step)
        self.assertEqual(summary.exit_code, 0)
        self.assertTrue(all(status == "ok" for _, status in summary.results))

    def test_skipped_steps_are_not_executed_but_reported(self):
        executed = []
        steps = plan_steps(dry_run=True)
        summary = run_steps(steps, runner=lambda step: executed.append(step.name) or 0)
        self.assertNotIn("vectors", executed)
        results = dict(summary.results)
        self.assertEqual(results["vectors"], "skipped")
        self.assertEqual(summary.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
