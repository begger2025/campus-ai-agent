# 联网证据采集子项目设计

## 1. 目标与边界

新增独立子项目 `evidence-collector`，通过已开通且具备联网检索能力的 AI 供应商 API，收集中山大学校园公共信息的可追溯证据。它的产出进入现有 `raw_posts → processed_posts → public_events` 主链，但不改变或依赖 `MediaCrawler`。

第一版只接收两类来源：

- 中山大学官方网页和公告；
- 具备稳定 URL、可引用摘录的公开新闻。

第一版不采集社交讨论页面、不进行网页抓取、不模拟浏览器、不启用定时任务，也不自动向主库写入任何未审核数据。

`MediaCrawler/` 保持零改动、零依赖。新服务不得导入其模块、修改其配置、调用其脚本或复用其数据库原生表。

## 2. 已确认的产品决策

- 管理员从现有后台按需创建采集任务。
- 每个任务先写入独立证据区，管理员审核通过后才能导入主库 `raw_posts`。
- 现有后台新增“联网证据采集”入口；采集服务本体独立运行，通过内部 API 协作。
- 对 DeepSeek、GLM、Kimi、豆包、通义千问保留统一适配接口；第一版只启用已配置 API Key 且已确认具备联网检索权限的供应商。
- 任一供应商不可用时，记录失败原因并尝试其他已启用供应商；没有可用供应商时任务失败且不产生主库数据。

## 3. 系统边界与数据流

```text
管理员后台创建任务
  → evidence-collector：查询规划
  → 供应商联网检索 API
  → 结果标准化、范围判定、证据抽取、复核、去重、评分
  → evidence_* 独立证据区
  → 管理员审核
  → 主项目受控导入接口
  → raw_posts
  → 现有 processed_posts / public_events 链路
```

新服务只使用供应商返回的搜索结果、引用 URL、摘要和引用片段。它不对返回 URL 发起 HTTP 抓取请求，因此不把联网证据采集实现为另一套爬虫。

主项目对最终入库保留所有权。`evidence-collector` 不直接 SQL 写入 `raw_posts`；管理员的导入操作调用主后端受保护的内部接口，由主后端完成校验、幂等写入与返回回执。

## 4. 中山大学范围准入规则

模型生成或返回的自由文本不是证据。每条候选记录必须通过以下全部校验。

### 4.1 查询限定

查询规划器生成的每条检索式必须含有“中山大学”、`Sun Yat-sen University`，或可确定归属的校区、学院、附属机构名称。不得单独使用“中大”作为主体锚点。

### 4.2 来源限定

官方来源由可维护的中山大学官方域名/账号来源表识别并优先评分。新闻来源必须位于可维护的允许来源列表中；不在名单中的来源只能保留为 `uncertain`，不能自动进入待审核队列。

### 4.3 原文限定

候选记录必须有规范 URL 与能证明中山大学关联的原文引用片段。只有模型摘要、没有 URL、没有引用片段，或引用片段不能证明主体时，直接拒绝。

### 4.4 复核限定

规则校验器与复核模型使用同一份已保存证据输入。复核模型不得补充未在输入中出现的事实；它只能输出 `verified`、`rejected` 或 `uncertain`，以及对应理由。规则与复核模型冲突时状态为 `uncertain`。

只有同时满足以下条件的记录可供管理员批准：

```text
scope_decision = accepted
verification_status = verified
source_url 与 evidence_quote 非空
```

“中大”而没有进一步主体说明、发布时间无法判断、来源不可引用、或内容与中山大学无直接关系的记录均不能导入主库。

## 5. 供应商适配层

建立 `ProviderRegistry` 和统一 `SearchProvider` 抽象。每个供应商适配器只处理自身认证、请求格式、联网工具调用和响应解析；业务流程只依赖统一模型。

```python
class SearchProvider:
    async def search(self, query, time_range, source_policy) -> list[SearchHit]:
        ...
```

`SearchHit` 至少包含：标题、URL、引用摘录、来源发布者、可得的发布时间、供应商标识、实际模型名与供应商请求追踪标识。

供应商配置包含启用状态、模型名、API 地址、密钥环境变量名、联网搜索能力开关、单任务限额、超时和重试策略。真实 API Key 只存在服务端环境变量或密钥服务中，不写入前端、数据库、日志、Git 或 `raw_json`。

检索模型可用于发现候选来源；复核模型仅处理保存后的结构化证据。若某供应商没有联网检索能力，它不能承担检索角色，但可在明确配置后承担非联网的复核角色。

## 6. 证据区数据模型

在共享 MySQL 中新增由新子项目独立拥有的 `evidence_` 前缀表：

| 表 | 作用 |
| --- | --- |
| `evidence_runs` | 任务主题、时间范围、创建者、状态、耗时、用量与错误摘要 |
| `evidence_queries` | 任务实际查询词、供应商、模型、提示词版本与调用状态 |
| `evidence_documents` | 原始 URL、规范 URL、域名、标题、发布者、发布时间、来源类型、引用片段 |
| `evidence_items` | 去重后的候选证据、摘要、主题、范围结论、质量分与审核状态 |
| `evidence_verifications` | 规则/模型复核结论、理由、冲突原因与复核版本 |
| `evidence_delivery_batches` | 导入批次、审批者、导入时间、主库 `raw_post_id` 与错误回执 |

`evidence_items` 必须保存：`source_url`、`canonical_url`、`source_domain`、`source_type`、`published_at`、`retrieved_at`、`evidence_quote`、`scope_decision`、`scope_reasons`、`retrieval_provider`、`retrieval_model`、`prompt_version`、`verification_status`、`quality_score`。

状态机：

```text
Run: created → running → completed | failed
Item: discovered → rejected | uncertain | verified
      verified → pending_review → approved | rejected_by_admin
      approved → delivered
```

状态更新必须幂等；同一 `canonical_url` 在同一来源类型下只保留一条活动证据记录。内容相近但 URL 不同的记录可在审核页标记为重复，不自动删除审计记录。

## 7. 审核与主库导入

现有后台新增“联网证据采集”入口，包括：

- 任务页：新建主题、选择时间范围、选择可用供应商、设置候选上限；
- 候选证据页：展示 URL、标题、引用片段、来源类型、模型、范围与复核理由；
- 审核页：通过、拒绝、标记不确定，并记录管理员备注；
- 导入记录页：展示证据与主库 `raw_posts` 的对应关系。

主后端新增仅管理员可调用的内部导入接口，例如 `POST /api/admin/evidence/import`。它必须在一个事务中：

1. 校验请求项处于 `approved` 状态且所需证据字段完整；
2. 使用 `SHA-256(canonical_url)` 作为稳定 `external_id`；
3. 按主库字段映射创建或复用 `raw_posts`；
4. 回写交付结果和 `raw_post_id`；
5. 返回每个项目的成功、已存在或失败状态。

建议的主库映射：

| `raw_posts` 字段 | 导入值 |
| --- | --- |
| `platform` | `web_evidence` |
| `external_id` | 规范 URL 的 SHA-256 |
| `source_table` | `evidence_item` |
| `source_raw_id` | `evidence_items.id` |
| `source_keyword` | 任务主题/中大限定检索词 |
| `title`、`content` | 证据标题与可归因摘要 |
| `url`、`raw_url` | 原始来源 URL |
| `publish_time` | 来源页面发布时间（存在时） |
| `crawl_time` | 实际检索时间 |
| `raw_json` | 不含密钥的最小溯源元数据 |

后续 `process_raw_posts` 和舆情 Agent 沿用既有流程；它们不需要知道采集服务的供应商细节。

## 8. 质量、可靠性与安全

- 每个任务限制查询数量、候选数量、供应商重试次数与预算；所有阈值均为后台可配置项。
- 供应商超时、限流或返回格式错误时，记录到查询记录；其他供应商可继续执行。
- 搜索结果、网页摘录和模型输出均视为不可信输入，不能改变系统指令、访问本地资源或触发额外工具调用。
- 服务端不访问模型返回的任意 URL，避免 SSRF 和隐式爬虫行为。
- 官方公告、新闻报道必须区分来源类型和来源等级；模型摘要不得替代原始证据。
- 未经管理员批准，`raw_posts`、`processed_posts`、`public_events` 不得变化。

## 9. 测试与验收

单元测试覆盖：查询限定、URL 规范化、范围判定、状态机、供应商响应解析、去重和主库映射。集成测试使用假的供应商响应，不调用真实模型 API；使用测试数据库或事务回滚验证审核和导入幂等。

第一版验收标准：

1. `MediaCrawler` 没有任何文件、依赖或行为变化；
2. 无 URL、无引用片段、无范围判定理由的记录无法被批准或导入；
3. “中大”歧义记录默认不通过；
4. 同一规范 URL 重复导入只产生一条 `raw_posts` 记录；
5. 供应商故障不会污染证据区或主库；
6. 每个已导入 `raw_posts` 都能追溯到任务、查询、供应商、模型、提示词版本、引用片段和管理员决策；
7. 管理员不批准时，现有舆情数据完全不受影响。

## 10. 非目标

第一版不包含：自动定时任务、自动导入、自动公开发布、网页抓取、社交平台内容采集、消息队列、供应商成本结算、或对现有 MediaCrawler 的重构。
