# 联网证据采集（Evidence Collector）

管理端通过 AI 大模型的联网检索能力，发现与中山大学有关的公开网页信息，经 URL 规范化、
SYSU 范围判定、人工审核后，写入 `raw_posts`，进入既有的舆情处理流水线。

代码位置：`backend/services/evidence/`、`backend/models_evidence.py`、
`backend/routers/admin_evidence.py`、`frontend/src/views/AdminEvidenceView.vue`。

---

## 1. 为什么爬虫之外还需要联网检索

`MediaCrawler` 与联网证据采集不是重复建设，而是两条互补的数据来源链路：

```text
MediaCrawler ：固定平台、固定页面、持续抓取、保留原始帖子与互动数据
联网证据采集 ：跨站点发现、可引用出处、快速形成可审计证据
```

**（1）降低单一采集方式的系统性风险。** 爬虫依赖平台页面结构、登录态、Cookie、验证码和风控
策略。任意一个环节变化，都可能使某个平台的采集任务失效。联网检索作为第二入口，可以在爬虫
失效、平台限流或临时无法登录时继续发现公开信息，避免"一个采集器挂掉导致整个项目没有数据"。

**（2）提高公开信息的发现速度与覆盖范围。** 爬虫覆盖的是已经确定的平台和页面；联网检索更适合
回答"最近有哪些与中山大学有关的公开信息"这类开放问题，可以一次检索学校官网、校园通知、
新闻网站等公开来源。

**（3）减少为每个平台编写解析器的成本。** 新增一个社交平台通常需要单独处理登录、翻页、
HTML/接口结构；而新增或替换一个 AI 供应商，改动集中在 `backend/services/evidence/providers.py`，
不会污染 `MediaCrawler` 的平台采集器与数据模型。

**（4）可审计、可交叉验证。** 不同 AI 供应商的检索索引、更新时间、收录范围不同。通过统一的
provider 接口并行检索并对比结果，最终交付的不是"AI 说了什么"，而是**带有来源 URL、标准化
URL 哈希、原文摘录、供应商与模型信息的证据记录**。没有 citation 的纯文本回答会被直接丢弃。

**（5）边界更清晰。** 联网检索只针对公开网页，且由明确的 API key、模型、endpoint 和
`WEB_SEARCH_ENABLED` 开关共同门控；**没有注入 HTTP 客户端时默认不联网**——仅填 API key 不会让
系统自动开始抓取，这是刻意设计的安全默认值。

> 结论：`MediaCrawler` 负责平台原始数据与持续采集；`evidence_collector` 负责联网发现、引用提取、
> 范围过滤与证据审计。两者最终都必须经过审核闸门才能进入公共信息数据库。

---

## 2. 数据流

```text
管理员触发 run（话题 + 检索词 + 供应商）
  → 各 provider 并发联网检索（asyncio.gather）
  → 只接受带 HTTP(S) citation 且有原文摘录的结果
  → URL 规范化 + SHA-256 去重（evidence_documents 全局唯一）
  → SYSU 范围判定（in_scope / needs_review / out_of_scope）
  → 人工核验（verify）+ 人工审核（review）
  → 交付：写入 raw_posts（platform='web'）
  → 进入既有舆情流水线（process_raw_posts → processed_posts → 事件聚类）
```

六张表：`evidence_runs` / `evidence_queries` / `evidence_documents` / `evidence_items` /
`evidence_verifications` / `evidence_delivery_batches`。

**交付闸门（三个条件必须同时满足）**：

```text
scope_decision == in_scope  且  verification_status == verified  且  review_status == approved
```

不满足的条目永远进不了 `raw_posts`。管理端页面会逐条列出"为什么这条还不能交付"。

**幂等**：`raw_posts` 上 `(platform, external_id)` 唯一，交付使用
`platform='web'`、`external_id=canonical_url_hash`，所以重复交付**不会**产生重复行。

---

## 3. 范围判定规则（scope_policy）

| 情况 | 判定 |
| --- | --- |
| 来源类型不是 official / news | `out_of_scope` |
| 没有原文摘录 | `out_of_scope` |
| 域名缺失或格式非法 | `out_of_scope` |
| **官方域名在 SYSU 白名单内** | **`in_scope`（域名本身即坐实实体，不要求正文出现"中山大学"）** |
| 官方域名不在白名单 | `needs_review` |
| 新闻域名在白名单 + 正文/标题出现"中山大学" | `in_scope` |
| 新闻域名在白名单 + 正文只出现"中大" | `needs_review` |
| 新闻域名不在白名单 | `needs_review` |

**为什么官方域名要单独放行**：中大官网上的真实通知通常写"我校""学校"，不会反复写全名。
早期版本要求正文字面出现"中山大学"，导致 `news.sysu.edu.cn` 上的真通知被判 `out_of_scope`
丢弃。新闻域名仍保持严格要求，防止新闻站顺带提一句就被收录。

域名白名单可用环境变量覆盖：`EVIDENCE_SYSU_OFFICIAL_DOMAINS`、`EVIDENCE_ALLOWED_NEWS_DOMAINS`
（逗号分隔）。匹配按 DNS 点边界进行，`evil-sysu.edu.cn` 和 `sysu.edu.cn.evil.com` 都不会命中。

---

## 4. URL 规范化（canonicalize）

去重的正确性直接决定 `raw_posts` 会不会出现同一篇文章的重复行——重复行会在下游被**重复计数**，
污染情感统计与事件聚类。因此规范化规则是数据正确性问题，不是美观问题。

规则：scheme/host 转小写 → 丢弃 fragment → 剥离 `utm_*` / `spm` / `from` → 剩余查询参数排序 →
去掉默认端口（80/443）→ **非空路径去掉尾斜杠**（`/notice/1/` → `/notice/1`，根路径保持 `/`）。
非 HTTP(S)、含账号密码、含空白字符的 URL 一律拒绝。

以下写法会被正确合并为同一篇 document：

```text
https://news.sysu.edu.cn/notice/1
https://news.sysu.edu.cn/notice/1/
https://news.sysu.edu.cn/notice/1/?utm_source=x
https://news.sysu.edu.cn:443/notice/1
https://news.sysu.edu.cn/notice/1?b=1&a=2   ←→   ...?a=2&b=1
```

---

## 5. 配置

**当前状态：一个供应商都没配，管理端页面会显示"暂无可用的检索模型"并禁用触发按钮。**
这是配置待完成，不是页面坏了。

在项目根目录 `.env` 中为**至少一家**供应商配齐四项（`.env` 已被 `.gitignore` 忽略，不会进仓库）：

```env
EVIDENCE_DEEPSEEK_API_KEY=<your-api-key>
EVIDENCE_DEEPSEEK_MODEL=<模型 ID>
EVIDENCE_DEEPSEEK_BASE_URL=<供应商的 OpenAI 兼容 chat-completions 地址>
EVIDENCE_DEEPSEEK_WEB_SEARCH_ENABLED=true
```

支持的 provider id：`deepseek` / `glm` / `kimi` / `doubao` / `qwen`。
其余四家用同样的前缀（`EVIDENCE_GLM_*`、`EVIDENCE_KIMI_*`、`EVIDENCE_DOUBAO_*`、`EVIDENCE_QWEN_*`）。
占位模板见根目录 `.env.example`。

`BASE_URL` 被当作**实际 POST endpoint** 使用，不会自动拼接路径——请填供应商官方文档给出的
OpenAI 兼容 chat-completions 完整地址。

配好后可以在管理端页面直接看到该供应商出现在下拉框里，或调
`GET /api/admin/evidence/providers` 确认（该接口只返回 provider id 和 enabled 布尔值，
不会回显任何凭证）。

---

## 6. 数据库表

六张 `evidence_*` 表由 `backend/database.py::init_db()` 统一创建（与主项目共用同一个
SQLAlchemy engine 和 Base，因此也跟随 `CAMPUS_DEMO_MODE=1` 的 SQLite 降级）。

共享 RDS 上**已建表**（2026-07-12）。组员无需任何操作，拉最新代码即可。
若需在新库上建表：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\init_db.py
```

`create_all` 只增不改：只创建缺失的表，不会 drop、不会 alter、不碰现有数据。

---

## 7. 使用流程（管理端）

1. 以管理员身份登录 → 后台管理 → **证据采集**。
2. 填话题 + 检索词，勾选供应商，点击开始采集。运行较慢（并发的联网大模型调用），页面会显示
   加载态并防止重复提交。
3. 在条目表中逐条查看：来源域名、可点击的原文链接、标题、原文摘录、供应商/模型徽章、
   范围判定标签。可按 `scope_decision` / `verification_status` / `review_status` 过滤。
4. 对可信条目执行**核验**与**审核通过**（两道闸门都要过）。
5. 点击**交付**，把该 run 中已审批的证据写入 `raw_posts`。交付后会报告"新建 N 行 / 已存在 M 行"。
6. 之后照常运行 `scripts/process_raw_posts.py`，这些 `platform='web'` 的行会与爬虫数据一起
   进入情感分析与事件聚类。

---

## 8. 接口

全部在 `/api` 前缀下，需要管理员权限（`require_admin`），统一 `{code, message, data}` 信封。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/evidence/providers` | 各供应商是否可用（不回显凭证） |
| POST | `/api/admin/evidence/runs` | 触发一次采集 |
| GET | `/api/admin/evidence/runs` | run 列表 |
| GET | `/api/admin/evidence/runs/{id}` | run 详情（含各 query 的供应商/模型/错误） |
| GET | `/api/admin/evidence/items` | 证据条目，可按 run/范围/核验/审核状态过滤 |
| POST | `/api/admin/evidence/items/{id}/verify` | 核验 |
| PATCH | `/api/admin/evidence/items/{id}/review` | 人工审核（通过/驳回 + 备注） |
| POST | `/api/admin/evidence/runs/{id}/deliver` | 把已审批证据交付进 `raw_posts` |

---

## 9. 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| 页面显示"暂无可用的检索模型" | 没有供应商配齐凭证，见 §5。这是配置问题不是故障。 |
| 触发采集报 404 | 选了未配置的供应商。前端已按可用性过滤，若仍出现请刷新页面。 |
| run 状态是 `partial` | 部分供应商失败、部分成功。在 run 详情里看每个 query 的 `error`（凭证已脱敏）。 |
| run 状态是 `failed` | 所有供应商都失败。同上查看 `error`。 |
| 条目全是 `out_of_scope` | 检索词与中山大学无关，或来源类型不是 official/news。 |
| 条目是 `needs_review` | 域名不在白名单，或正文只出现"中大"。可人工判断后审核通过，或扩充白名单（§3）。 |
| 交付按钮说没有可交付条目 | 三道闸门（in_scope + verified + approved）没有同时满足。页面会逐条说明缺哪一项。 |
| 交付后 `raw_posts` 没增加 | 该证据之前已交付过。唯一约束保证幂等，返回结果里的"已存在"计数即为此。 |

---

## 10. 已知限制

- **run 是同步的**：`POST /runs` 会一直等到采集结束。前端把该请求的超时放宽到 180 秒。
  若单次 run 可能超过 3 分钟，正确做法是改成后台任务 + 轮询，目前未实现。
- **`load_settings()` 只校验 API key 与 `WEB_SEARCH_ENABLED`**，不校验 `MODEL` / `BASE_URL`。
  因此配了 key 和开关但漏配模型/地址的供应商，会被报告为 `enabled: true` 却在运行时失败。
- **`http_transport.py` 与主项目的 `backend/services/llm_client.py` 仍是两套 HTTP 调用栈**。
  前者是异步、无缓存、无用量统计；后者是同步、有重试/缓存/token 统计。合并二者需要处理
  同步/异步差异与各家不同的联网检索开关（GLM 用 `tools`、Qwen 用 `enable_search`），
  故暂未合并。后果：证据采集的 token 消耗不会出现在现有的用量面板里。
- **`EvidenceDeliveryBatch.raw_post_id` 是单数外键**，因此一次交付会为每一行 `raw_posts`
  生成一条 batch 记录（batch = "这个 run 的这条证据变成了这条 raw_post" 的审计事实）。
