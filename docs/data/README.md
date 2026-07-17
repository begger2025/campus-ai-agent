# docs/data — 评测基准结果快照

`scripts/eval_chat_benchmark.py` 的运行结果存档（JSON），用于跨改动对比对话链路的
路由准确率 / 检索命中 / 引用合法性 / 延迟四项指标。

| 文件 | 说明 |
|------|------|
| `eval_benchmark_2026-07-15_baseline.json` | 优化前基线 |
| `eval_benchmark_2026-07-16_mid.json` | 延迟优化中期快照 |

命名约定：`eval_benchmark_<日期>_<标签>.json`。新跑一轮基准后把结果文件加进来，
并在测试报告（[docs/coursework/05](../coursework/05-软件测试与质量保证报告.md)）引用最新数字。
