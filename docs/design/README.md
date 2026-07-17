# docs/design — 功能设计文档

AI 能力的设计文档：每篇讲清**要解决什么失败模式、方案是什么、为什么这样取舍**。
每篇设计都有对应的消融实验证明有效性，见 [docs/experiments/](../experiments/)。

| 文档 | 解决的问题 |
|------|------------|
| [event-clustering-llm-refine.md](event-clustering-llm-refine.md) | 纯 embedding 聚类把 31% 语料压成一个杂桶 → LLM 精修拆桶并起具体标题 |
| [event-risk-llm.md](event-risk-llm.md) | 规则风险量的是流行度不是严重性（宿舍火灾垫底）→ 事件级 LLM 研判 |
| [event-recency.md](event-recency.md) | 流水线时间盲，五年前的处分排进前三 → 半衰期时效衰减（只进排序） |
| [event-lifecycle.md](event-lifecycle.md) | 年龄分不出"已了结 vs 悬而未决" → 生命周期研判进排序 |
| [keyword-event-design.md](keyword-event-design.md) | 智能选题看不见"事件" → 五路信号 + 事件级检索词生成 |
| [evidence-collector.md](evidence-collector.md) | 报告需要站外佐证且不可编造 → 联网检索 + 确定性核验 + 人工审核 |

共同设计原则（各篇反复出现，答辩可引用）：

1. **失败方向可控**：LLM 挂掉/幻觉一律逐项退回规则值，不拖垮流水线；
2. **判断与算术分离**：能算的不问模型（时效衰减是纯算术），要判断的才花调用；
3. **可解释**：每个分数能用一句话向非技术评审解释来源。
