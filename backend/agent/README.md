# backend/agent — 舆情核心算法包

唯一内容是 `public_opinion_core/`：舆情分析的核心算法，**只依赖 Python 标准库**，
不 import FastAPI/SQLAlchemy/requests。LLM 调用与 embedding 向量以**函数注入**方式
进入（依赖倒置），因此整包可独立测试、可整体移植。

评测子仓（campus-opinion-agent）就是靠这一性质工作的：
`scripts/sync_opinion_core.py` 把本包反向移植过去独立评测。
**改动本包后记得同步子仓**（`scripts/sync_opinion_core.bat`）。

## public_opinion_core 模块地图

| 模块 | 职责 |
|------|------|
| `service.py` | 核心服务入口：把下列组件编排成完整分析流水线 |
| `schemas.py` | 可移植 dataclass（OpinionNote / 事件 / 研判结果） |
| `adapter.py` / `normalizer.py` | 行数据 → OpinionNote；文本与标签归一化 |
| `clustering.py` | 规则聚类（关键词/相似度） |
| `semantic_clustering.py` | 语义聚类（注入的 embedding 向量上做） |
| `llm_refine.py` | LLM 精修：拆 embedding 误合并的大桶，起具体标题 |
| `llm_merge.py` | 近重簇合并裁决（灰区相似度交给判断) |
| `llm_risk.py` | 事件级风险研判（严重性≠流行度） |
| `llm_lifecycle.py` | 生命周期研判（悬而未决的事不随时间沉底) |
| `llm_keywords.py` | 从事件生成爬取检索词 |
| `keyword_planner.py` | 智能选题：需求/缺口五路信号 → 推荐关键词 |
| `recency.py` | 时效性衰减（只进排序，不改严重性/热度） |
| `scoring.py` / `sentiment_risk.py` | 热度计算；规则情感与风险兜底 |
| `platform_weights.py` | 平台先验权重（排序分 = 权重 × heat_rank） |
| `concurrency.py` | 注入调用的并发执行（结果逐位与串行一致） |
| `memory.py` | 跑批间的事件记忆（run-to-run） |
| `payload_builder.py` / `visualization.py` | 入库载荷 / 图表数据构建 |

## 修改守则

- **不准引入第三方依赖**——这是本包的立身之本，`check.ps1` 的子仓测试会守住它;
- 需要模型/网络/数据库的逻辑放 `backend/services/`，以函数参数注进来;
- 每个模块的详细设计见各自 docstring 与 [docs/design/](../../docs/design/)。
