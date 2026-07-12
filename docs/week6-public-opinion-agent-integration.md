# Week6 舆情 Agent 子项目集成（第一轮：分析链路升级）

## 1. 这次集成做了什么

把 `campus-opinion-agent` 子项目 week3~week6 的能力接入主项目分析链路：

| 能力 | 说明 |
|---|---|
| 核心同步 | `backend/agent/public_opinion_core/` 从 week2 版（9 文件）升级到 week6 版（12 文件），新增记忆、可视化、语义聚类模块，并修复"快"字误中正面词表的 bug |
| LLM 情绪分析 | 批量分类（20 条/次），LLM 优先覆盖、规则逐条兜底；黄金集准确率 75% → 100% |
| 跨次运行记忆 | 事件趋势标注（new/rising/falling/stable）、风险升级标记；快照存 `data/public_opinion_memory.json` |
| 可视化数据层 | 分析响应直接返回 6 组图表数据（日趋势/词云/情绪/风险/平台分布/事件趋势） |
| 语义聚类（可选） | 装 `sentence-transformers` 后自动启用 bge-small-zh 向量聚类；不装走规则聚类 |
| LLM 调用基建 | 重试、退避、本地响应缓存（`data/llm_cache.json`）、用量统计、提示注入防御 |

**审核流、权限、前端、个人事项 Agent 均未改动。** 对话 Agent（chat/ReAct）属于第二轮。

## 2. API 变化（全部向后兼容）

`POST /api/agent/public/analyze` 请求体新增可选字段：

```json
{ "use_llm": true }
```

未配 OPENAI_API_KEY 时 use_llm=true 也自动退回规则，行为与升级前一致。

响应新增字段：

```json
{
  "events": [{ "...原有字段": "...", "trend": "stable", "heat_delta": 0.0, "risk_escalated": false }],
  "visualization": { "daily_trend": [], "keyword_cloud": [], "sentiment_distribution": {}, "risk_distribution": {}, "platform_distribution": {}, "event_trends": [] },
  "trend_counts": { "new": 0, "stable": 6 },
  "analysis_modes": { "sentiment": "llm", "clustering": "rules", "sentiment_overridden": 30 }
}
```

`agent_run_logs.output_summary` JSON 同步记录 trend_counts 和两个 mode（public_events 表无 extra 列，趋势不落事件表）。

**用量监控**（2026-06-13 新增）：`GET /api/agent/public/usage`（仅管理员）返回进程级 LLM 计数器（calls/cache_hits/errors/tokens/duration_ms）、当前模型、缓存条目数。注意 `scope: process`——服务重启归零，用于演示前检查额度消耗，不是账单。测试：`backend/tests/test_usage_endpoint.py`。

## 3. 配置

`.env`（已更新）：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` 换成已验证可用的配置（原配置 key 为空、从未生效，已注释保留）。可选项及默认值见 `backend/services/llm_config.py`。

依赖：`requirements.txt` 新增 `openai`（已装入 .venv）。语义聚类需手动 `pip install sentence-transformers`（约 500MB，国内网络配 `HF_ENDPOINT=https://hf-mirror.com`）。

## 4. 核心同步纪律

`backend/agent/public_opinion_core/` 的**唯一改动源是子项目**（那边有 207 个测试守护），不要在主项目直接改这些文件。子项目更新后运行：

```text
scripts\sync_opinion_core.bat
```

> **⚠️ 2026-07-12 现状更新：两边已经分叉，上面这条纪律事实上已经作废，`sync_opinion_core.py` 现在是把危险的枪。**
>
> 主项目自己往核心里加了 `platform_weights.py`（commit `45efe86` / `e494f85` 的 heat_rank 排序分），
> 子项目**没有这个文件**；13 个核心文件里有 7 个（`clustering` / `semantic_clustering` / `scoring` /
> `sentiment_risk` / `schemas` / `adapter` / `__init__`）两边哈希不同，主项目更新。
>
> **现在跑 `scripts/sync_opinion_core.py` 会 (1) 删掉 `platform_weights.py`（脚本会删所有"子项目没有的文件"）、
> (2) 用旧版覆盖主项目的 heat_rank 改动 → 直接把两个 commit 的工作回滚掉，且测试会红。**
>
> 结论：**主项目已经是核心的事实改动源**。要么把 heat_rank / min_cluster_size 这批改动反向移植回子项目
> 再恢复"子项目为源"的纪律，要么正式宣布主项目为唯一源、把 `sync_opinion_core.py` 停用或改成双向核对。
> 在做出决定之前，**不要运行这个同步脚本**。（本次 `min_cluster_size` 的改动按现状直接改在主项目核心里。）

## 4.5 语义聚类启用与阈值标定（2026-06-13 补充）

主项目已安装 `sentence-transformers`，语义聚类激活（`clustering_mode=semantic`）。**阈值按真实数据重新标定**：

| cluster_threshold | 事件数（182 条 DB 数据） | 结论 |
|---|---|---|
| 0.60（fixture 默认） | 7（出现 143 条的过合并大簇） | 真实帖带话题标签/表情，基线相似度偏高 |
| **0.68（.env 现值）** | **27（课表 61 / 课程 32 / 宿舍 31 / 压力 12…）** | **平台期，结构合理** |
| 0.75 | 87（66 个单帖事件） | 过碎 |

效果对比：同一批数据规则聚类把 **85% 帖子塞进"其他校园公共信息"兜底桶**；语义聚类分出 27 个可读主题，并把游记、同人文等无关帖正确留为单帖。无关键词长帖的事件标题已截断（核心 `semantic_clustering.py` 修复并同步）。第二次运行全部事件经簇中心对齐 trend=stable，热加载单轮约 3 秒。

**注意——事件身份切换**：语义事件的 `event_key` 是 `sem:*`，与旧规则事件不同。下一次 `persist=true` 的分析会在 `public_events` 新增一批语义草稿事件（旧已发布事件不受影响，但审核队列会变长），建议先和负责审核的队友同步。不想启用时在 `.env` 设 `EMBEDDING_ENABLED=false` 即可整体退回规则聚类。

`scripts/sync_opinion_core.bat` 已重写为调用 `sync_opinion_core.py`（bat 直接写中文路径有 cmd 代码页问题）。同步脚本覆盖两部分：核心 12 文件原样复制；**服务层白名单 7 文件**（llm_client/prompt_guard/sentiment_llm/embedding/intent_router/react_loop/critic）复制时自动改写导入前缀（`app.config`→`backend.services.llm_config`、`app.services.*`→`backend.services.*`）。主项目专属服务（opinion_chat_service/opinion_report/llm_config/adapter）不在白名单内，不会被覆盖；子项目新增共享服务时在脚本的 `PORTED_SERVICES` 登记。

## 4.6 事件生成的两条底线：单帖不成事件 + 输入不许静默截断（2026-07-12）

### 输入截断（原缺陷：静默丢数据）

`scripts/generate_public_events.py` 原来默认 `--limit 200`，而 `query_agent_rows` 用
`ORDER BY id DESC LIMIT 200` 取数。库里 297 条时，**最旧的 97 条被无声丢掉**，日志、返回值、
`agent_run_logs` 里都没有任何痕迹——"全量分析"其实只看了最新的一段。

现在：

- **脚本默认 `--limit 0` = 全量**（`DEFAULT_LIMIT`），默认运行不可能丢数据。
- limit 仍然可传（API 侧默认 50 不变）；一旦真的截断，`run_public_opinion_analysis` 会
  **数出来并喊出来**：`logger.warning` + 返回值里的 `input_truncated={matched, analyzed, dropped}`
  + `warnings` 里一条中文告警（这条同时进 `agent_run_logs.input_summary`），脚本打印
  `[WARN] 输入被截断！匹配 297 条，仅分析 200 条，丢弃最旧 97 条`。
- 「看全了」的判定（陈旧草稿归档的前提）也改用 `dropped == 0`，不再靠 `len(rows) < limit` 猜。

### 单帖不成事件（`EVENT_MIN_CLUSTER_SIZE`，默认 2）

原来贪心聚类的**每一个簇**都会变成一个 `public_event`，包括只有一条帖子的簇——事件列表里
于是塞满「<某条帖子的标题>相关讨论」，点进去只有一条内容。297 条真实数据下（阈值 0.65）
22 个事件里有 **15 个是单帖事件**。

现在 `backend/services/llm_config.py` 增加 `EVENT_MIN_CLUSTER_SIZE`（`.env` 可覆盖，默认 **2**），
一路传到核心的 `cluster_notes_semantic(min_cluster_size=…)` 和 `cluster_notes(min_cluster_size=…)`
（规则路径的 `keyword:*` 兜底桶同样会造单帖事件，两条路径口径必须一致）。不够大的簇：
不产出事件、**也不写簇中心到记忆快照**（否则下一轮会被对齐成"老事件"复活）。压制条数进
`warnings` 和 `agent_run_logs.output_summary`（`suppressed_clusters`），不是悄悄扔掉。

默认取 2 而不是 3 的依据（297 条真实数据，阈值 0.65）：单帖簇 15 个，2 帖簇只有 2 个。
min=2 干掉全部 15 个单帖事件、保留 7 个事件；min=3 只多干掉 2 个事件却把事件数压到 5——
在只有 297 条帖子的数据量下，"至少两个人在说"已经是"公共事件"的合理下限，再抬只会让列表空掉。

### 「71% 的帖子不属于任何事件」是**度量口径问题**，不是数据丢失

用 `event_post_links` 去数"帖子有没有进事件"会得到 86/297（29%）——这个数字是假的。
`event_post_links` 存的是 **代表帖**，不是簇成员：`build_event_from_group` 里
`representative_notes=sorted_notes[:5]`，**每个事件最多只落 5 条链接**。一个 191 条的事件在
链接表里也只有 5 行。

实测（`--preview`，297 条全量）：`sum(source_count) == 297`，**每条帖子都属于且只属于一个簇**，
聚类阶段一条都没丢。所以：

- 事件 = **值得看的簇**（≥ `EVENT_MIN_CLUSTER_SIZE` 条帖子），不是全体帖子的一个划分；
- 落库的 `public_events.source_count` 是**真实簇大小**，`event_post_links` 是 **top-5 代表帖**；
- 唯一真正"不属于任何事件"的帖子，是被 `EVENT_MIN_CLUSTER_SIZE` 压制的单帖簇（全量下 15 条 / 5%），
  这是设计意图，不是 bug。**不要为了把覆盖率做高去硬造事件。**

### 遗留问题：阈值 0.65 在 297 条数据上出现过合并大簇（未改，需负责人决策）

`.env` 现值 `EMBEDDING_CLUSTER_THRESHOLD=0.65` 是在 182 条数据上标定的，数据涨到 297 条后
贪心聚类的簇中心漂移，出现 **191 条和 71 条两个巨簇**（占全部帖子的 88%）。同一批数据实测
（`min_cluster_size=2`）：

| cluster_threshold | 事件数 | 最大簇 | 进事件的帖子 |
|---|---|---|---|
| 0.60 | 4 | **282** | 292/297 |
| **0.65（.env 现值）** | **7** | **191** | 282/297 |
| 0.70 | 15 | 90 | 254/297 |
| 0.75 | 26 | 43 | 191/297 |
| 0.80 | 33 | 22 | 135/297 |

看上去 0.70~0.75 才是当前数据量下的合理区间。这只需要改 `.env`（不改代码、不改库），
但会换掉事件身份（`sem:*` key 变化 → 新一批草稿），**留给负责人决定**，本次未改。

## 5. 真实数据验证记录（2026-06-13，共享 MySQL，182 条小红书数据）

- 预览运行（persist=false，limit=30）：6 个事件，`sentiment_mode=llm`（30/30 条 LLM 覆盖，2 次批量调用，22 秒），可视化 6 组数据齐全
- 第一次落库：6 事件 upsert，全部 trend=new
- 第二次落库：全部 trend=stable（跨次记忆生效）；已 published 的事件**审核状态未被覆盖**；public_events 总数不变（upsert 未产生重复行）
- `scripts/check_wp4.py` 验收全部通过

## 6. 给前端队友

`visualization` 字段是现成的图表数据源（ECharts 可直接映射）：`daily_trend`（折线）、`keyword_cloud`（词云）、`sentiment_distribution`/`risk_distribution`/`platform_distribution`（饼图）、`event_trends`（事件趋势列表，含 trend/heat_delta/risk_escalated）。SentimentView 目前在前端本地算情绪，建议改为消费该字段（后端已是 LLM 级精度）。

## 7. 改前备份

升级前的旧文件在 `backup_before_agent_upgrade/`（含旧版核心、adapter、router、requirements），确认稳定后可删除。
