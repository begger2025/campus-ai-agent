# docs/experiments — 消融实验报告

每篇对应 [docs/design/](../design/) 的一项设计：**关掉这个能力,指标掉多少**。
实验脚本在 [scripts/](../../scripts/)（`ablation_*.py`），输入用固定语料快照
[data/fixtures/event_clustering_297.json](../../data/fixtures/) 保证各臂逐位可比、结果可复现。

| 报告 | 对照 | 对应设计 |
|------|------|----------|
| [event-clustering-llm-refine-ablation.md](event-clustering-llm-refine-ablation.md) | 纯 embedding vs +LLM 精修 | 聚类精修 |
| [event-risk-llm-ablation.md](event-risk-llm-ablation.md) | 规则风险 vs LLM 研判 | 风险研判 |
| [event-recency-ablation.md](event-recency-ablation.md) | 时间盲 vs 时效衰减 | 时效性 |
| [event-lifecycle-ablation.md](event-lifecycle-ablation.md) | 只看年龄 vs +生命周期 | 生命周期 |
| [keyword-event-ablation.md](keyword-event-ablation.md) | 看不看得见事件 | 智能选题 |

对话链路的持续评测（非消融）：`scripts/eval_chat_benchmark.py`（单轮金标四项判分）与
`scripts/eval_chat_dialogue.py`（多轮回归），基准快照存于 [docs/data/](../data/)。
