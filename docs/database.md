# 数据库设计：Week2 共享 MySQL

当前团队主库：

```text
campus_ai_agent
```

主项目、MediaCrawler、公共舆情 Agent 都应连接同一个共享 MySQL。第一周的 `data/campus.db` 只作为历史本地文件，不再作为团队主库。

## 核心链路

```text
MediaCrawler 原生采集表
-> raw_posts
-> processed_posts
-> public_events
-> event_post_links
-> 管理员审核与日志
-> 普通用户查看 published 事件并提交反馈
```

第二周暂不接入个人事项 Agent，因此 smoke test 不检查 `personal_advices`、个人建议接口、通知表和复杂 RBAC。

## MediaCrawler 原生表

这些表由 MediaCrawler 维护，主项目后端只读取，不直接改表结构。

常见表：

```text
xhs_note
xhs_note_comment
xhs_creator
xhs_crawl_history
weibo_note
weibo_note_comment
weibo_creator
tieba_note
tieba_comment
tieba_creator
douyin_aweme
bilibili_video
kuaishou_video
zhihu_content
```

公共舆情 Agent 不应直接依赖这些原生表，而应通过同步入口写入 `raw_posts`。

## 主项目公共舆情表

### raw_posts

统一原始帖子表，承接 MediaCrawler 同步后的内容。

核心字段：

```text
id
platform
external_id
source_table
source_raw_id
source_keyword
title
content
author
publish_time
url
raw_url
like_count
collect_count
comment_count
share_count
tags_json
images_json
raw_json
crawl_time
status
created_at
updated_at
```

约束：

```text
UNIQUE(platform, external_id)
```

### processed_posts

清洗后的帖子表，是公共舆情 Agent 的主要输入表。

核心字段：

```text
id
raw_post_id
platform
note_id
title
content
source_keyword
publish_date
publish_time_raw
author_name
tags_json
note_url
raw_note_url
images_json
like_count
collect_count
comment_count
share_count
heat_score
heat_rank
sentiment
sentiment_score
risk_level
risk_score
risk_reasons_json
concerns_json
created_at
updated_at
```

兼容字段：

```text
author
publish_time
```

约束：

```text
raw_post_id -> raw_posts.id
UNIQUE(raw_post_id)
```

#### 热度三层：heat_score（展示）→ heat_rank（平台内百分位）→ ranking_score（排序）

```text
heat_score      原始加权互动量        —— 落库、展示给用户，公式不动
  ↓ 平台内百分位（归一化 pass）
heat_rank       0-100，该帖在自己平台内的位次  —— 落库，保平台内公平
  ↓ × platform_weight[platform]
ranking_score   跨平台排序分          —— 不落库，排序时现算（权重要能不改库就调）
```

**排序 / 选 top-N / 加权重要性一律用 `ranking_score`；展示给用户看的仍是 `heat_score`。**
下面三小节依次说明每一层为什么存在。

##### 第一层 heat_score：真实但跨平台不可比

`heat_score` 是**原始互动量的加权和**，由 `scripts/process_raw_posts.py::calculate_heat_score` 计算：

```text
heat_score = like*1.0 + collect*1.5 + comment*3.0 + share*2.5
```

它是一个真实、可解释、要展示给用户看的数，**公式不动**。但它**跨平台不可比**——
各平台的互动量量级差约 3 个数量级（2026-07 在共享库 331 行 `processed_posts` 上实测）：

| platform | 行数 | heat_score 中位数 |
|---|---|---|
| xhs | 182 | 3924 |
| ks | 38 | 998 |
| weibo | 10 | **3** |
| zhihu | 101 | **5** |
| web | 0（尚无交付） | **0**（网页没有互动量，恒为 0） |

后果：任何按 `heat_score` 排序/取 top-N 的视图都会被 xhs/ks 占满，把 weibo（最重要的舆情
平台）、zhihu 和人工审核过的 web 官方通知整个埋掉。

##### 第二层 heat_rank：平台内百分位

`heat_rank`（0-100 float）是修复：该行 `heat_score` 在**它自己平台内**的百分位。

- **算在哪**：百分位是**语料相对**的（一行新增会改变同平台每一行的百分位），不是逐行函数。
  所以它由 `scripts/process_raw_posts.py` 在处理完之后跑的一次**归一化 pass** 全量重算
  （按平台重算该平台所有行）。331 行的规模下 O(n log n) 全量重算成本可忽略，且避免了
  增量更新必然产生的漂移。纯函数 `backend/services/heat_ranking.py::percentile_ranks`
  可单测，DB pass 只剩薄薄一层。
- **并列怎么处理**：**中位秩**（mid-rank）——`100 * (比它小的个数 + 并列个数/2) / 总数`。
  相同分数拿到完全相同的百分位，绝不靠 id 偷偷分先后。由此单条的平台得 50（中性）而不是
  0 或 100，且任何行的百分位都严格落在 (0, 100) 内，没有哪一行会被判 0 分沉底。
- **它仍然只是中间量**：`heat_rank` 落库，但**不要直接拿它排序**——见下一层。

`web` 平台的 `heat_score` 不来自互动量（网页没有赞/藏/评/转），而来自**来源权威度 + 核验
强度**，见 `docs/evidence-collector.md`。

##### 第三层 ranking_score：平台先验权重 × 平台内百分位

纯百分位**矫枉过正**：它把**量级**整个丢了。一条 3 个赞、排在 weibo 95 分位的帖子，和一条
10 万赞、排在 xhs 95 分位的帖子，`heat_rank` 完全相同——可它们的真实触达差了三个数量级。
项目负责人人工审阅了抓取样本：对校园舆情这个场景，**xhs/ks 的触达和数据质量都明显高于
weibo/zhihu**（这也和上表的中位数量级一致）。

所以在百分位之上再乘一个**平台先验权重**：

```text
ranking_score = platform_weight[platform] × heat_rank
```

- **平台内公平**由百分位保住：权重是常数倍，不改变平台内的相对顺序，weibo 的头部帖依然稳赢
  weibo 的长尾帖。
- **跨平台触达**由权重还回来：zhihu 的 99 分位帖得 `0.5 × 99 = 49.5`，落在 xhs 的中位数
  （`1.0 × 50 = 50`）附近——**它能冒头，但压不住 xhs 的头部帖**（`1.0 × 90 = 90`）。

**默认权重**（`backend/agent/public_opinion_core/platform_weights.py::DEFAULT_PLATFORM_WEIGHTS`）：

| platform | weight | 说明 |
|---|---|---|
| xhs | 1.0 | 触达与数据质量最高（基准） |
| ks | 0.9 | 次高 |
| web | 0.8 | 官方通知/新闻，人工核验过，质量高但非社交扩散 |
| tieba | 0.6 | 2026-07-19 起有真实数据（首轮学业教务词 13 条），量小噪声偏多，中游权重暂维持 |
| zhihu | 0.5 | 量级小、噪声大 |
| weibo | 0.4 | 同上；仍是最重要的舆情平台，故权重压制而非排除 |

- **未列出的平台 → 权重 1.0**（`UNKNOWN_PLATFORM_WEIGHT`）：新平台在被正式定权前以满权重参与
  排序。**绝不**把未知平台默默打成 0 分沉底。
- **怎么调（不需要迁移）**：`ranking_score` **不是数据库列**，而是 `(platform, heat_rank)` 的
  纯函数，在排序发生的地方现算。调权重只要设环境变量 `HEAT_PLATFORM_WEIGHTS`（写进 `.env`，
  与 `LLM_*` 等配置同一套约定），**增量覆盖**，未写到的平台保持默认；改完既不用迁移、也不用
  重跑归一化 pass：

  ```bash
  # 两种写法都认；只写要改的平台
  HEAT_PLATFORM_WEIGHTS={"weibo": 0.6, "zhihu": 0.7}
  HEAT_PLATFORM_WEIGHTS=weibo=0.6,zhihu=0.7
  ```

  配置写坏（非法 JSON / 负数 / 非数字）时整体退回默认表，排序降级成"没调过"，不会让流水线炸掉。

##### 谁用哪个

| 用途 | 用哪个 |
|---|---|
| 展示给用户的热度数字 | `heat_score`（永远） |
| 排序 / 选 top-N / 事件排序 | `ranking_score`，兜底链 `ranking_score → heat_rank → heat_score` |
| 风险规则"综合热度较高" | **`heat_rank`**（裸百分位，见下） |
| 跨次运行的热度变化 `heat_delta` | `heat_score`（`memory.py`：同一事件跟自己比，且是展示值） |

已切换到 `ranking_score` 的调用点：`backend/agent/public_opinion_core/clustering.py`
（`note_rank_key`、`build_event_from_group` 的代表帖与 `OpinionEvent.ranking_score` 聚合、
`sort_events`）、`semantic_clustering.py`（簇种子序、`_new_key_and_title` 代表帖，均经由
`note_rank_key`）、`backend/services/opinion_chat_service.py`（`_risk_sorted_events`、
`_search_ranked_notes` → 对话检索 top-10 与 ReAct `search_notes` top-5）。

**唯一的例外：`sentiment_risk._is_high_heat` 故意留在裸 `heat_rank >= 80` 上。** 它问的不是
"这条帖子跨平台排第几"（那才是选择/排序），而是"这条帖子**在它自己的社区里**是不是烧起来
了"——那是一个平台内属性，也正是风险信号本身的含义。而且若改用 `ranking_score >= 80`，
weibo（权重 0.4）的 `ranking_score` 上限只有 40、zhihu（0.5）只有 50，**永远**够不到 80，
这条风险规则对它们会像绝对阈值 150 时代一样彻底失效——恰恰是引入 `heat_rank` 要修的那个 bug
原样复发。

**老数据兜底**：`heat_rank` 为 0（未归一化）→ `ranking_score` 为 0 → 排序键依次回退到
`heat_rank`、`heat_score`，行为与改造前一致，绝不退化成随机顺序。

**迁移**：`create_all()` 不会 ALTER 已存在的表，新增 `heat_rank` 列必须跑
`scripts/add_processed_posts_heat_rank.py`（幂等，支持 `--dry-run`；加列 + 回填存量行）。

### public_events

公共舆情 Agent 聚合生成的事件表。

核心字段：

```text
id
event_key
title
summary
topic
event_type
sentiment
risk_level
risk_score
heat_score
confidence
source_count
date_range_json
source_keywords_json
top_tags_json
concerns_json
risk_reasons_json
status
reviewed_by
reviewed_at
review_comment
created_at
updated_at
```

兼容字段：

```text
source_post_id
```

事件状态：

```text
draft
published
rejected
archived
```

普通用户接口只返回：

```text
status = published
```

### event_post_links

事件与帖子关联表，用于记录一个事件由哪些帖子支撑。

字段：

```text
id
event_id
processed_post_id
raw_post_id
rank
role
created_at
```

字段说明：

```text
role = representative | source
rank = 代表性内容排序
```

外键：

```text
event_id -> public_events.id
processed_post_id -> processed_posts.id
raw_post_id -> raw_posts.id
```

## 后台管理与审计表

### users

普通用户和管理员账号表。

字段：

```text
id
username
password_hash
display_name
role
email
phone
status
last_login_at
created_at
updated_at
```

第二周只使用：

```text
role = user
role = admin
```

### crawl_tasks

记录爬虫、同步、清洗和导入任务。

字段：

```text
id
task_name
task_type
platform
keyword
status
started_by
started_at
finished_at
total_count
success_count
failed_count
error_message
report_path
created_at
updated_at
```

常见 `task_type`：

```text
crawl
sync
process
import
```

### agent_run_logs

记录公共舆情 Agent 每次运行。

字段：

```text
id
agent_type
keyword
input_count
output_count
input_summary
output_summary
status
error_message
duration_ms
created_by
started_at
finished_at
created_at
```

第二周主要使用：

```text
agent_type = public_opinion
```

### event_review_logs

记录事件审核状态变化。

字段：

```text
id
event_id
reviewer_id
old_status
new_status
review_comment
created_at
```

兼容字段：

```text
comment
```

### admin_operation_logs

管理员操作审计日志。

字段：

```text
id
admin_user_id
action
target_type
target_id
detail
ip_address
user_agent
created_at
```

当前常见 action：

```text
update_event_status
run_public_opinion_analysis
update_feedback_status
```

### system_logs

系统关键日志，面向管理员后台展示。

字段：

```text
id
level
module
message
detail
request_id
created_at
```

常见 module：

```text
backend
crawler
sync
process
agent
database
admin
smoke
```

### user_feedback

普通用户反馈表。

字段：

```text
id
user_id
target_type
target_id
feedback_type
content
contact
status
handled_by
handled_at
handle_note
created_at
updated_at
```

常见状态：

```text
pending
handling
resolved
ignored
handled
```

### system_configs

可选系统配置表，用于采集关键词、风险阈值、数据源开关等。

字段：

```text
id
config_key
config_value
description
updated_by
created_at
updated_at
```

约束：

```text
UNIQUE(config_key)
```

## 保留但非第二周核心的表

```text
user_tasks
user_schedules
```

这两张表来自第一周个人事项模块，可保留，但不作为第二周公共舆情 Agent 验收主线。

## 初始化

创建或补齐表：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

共享 MySQL 下禁止自动插入第一周 demo 数据。只有本地 SQLite 开发需要演示数据时，才使用：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py --seed-demo
```

## Week2 Smoke Test 数据库检查项

运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_backend.ps1 -Limit 200 -Port 9010
```

至少检查：

```text
raw_posts > 0
processed_posts > 0
public_events > 0
crawl_tasks > 0
agent_run_logs > 0
event_review_logs > 0
admin_operation_logs > 0
user_feedback > 0
```

成功说明：

```text
采集数据已经能进入 raw_posts
raw_posts 已能清洗到 processed_posts
processed_posts 已能作为 Agent 输入生成 public_events
管理员审核会写入 event_review_logs 和 admin_operation_logs
用户反馈会写入 user_feedback
系统关键步骤会写入 system_logs
```

## 废弃表与自动维护说明（2026-07-08 数据库优化）

- **废弃表**：`user_tasks`、`user_schedules`（week-1 个人事项遗产，个人页现走前端本地存储）、`system_configs`（从未被读写）。ORM 模型已移除，共享库中的空表保留不 drop；确需删除请与全组确认后手动执行。
- **processed_posts 情绪/风险列**：由 `/agent/public/analyze`（persist 运行）自动回写逐帖标注，不再是占位值。
- **陈旧草稿自动归档**：全量分析（无关键词/平台过滤且未被 limit 截断）会把本次不再出现的 draft 事件归档并写审核日志（reviewer=system）；published/rejected 永不自动改动。
- **索引**：模型声明即索引口径；已存在的库用 `scripts/add_indexes.py` 幂等补齐。

- **评论语料（2026-07-08）**：`xhs_note_comment` 的高赞评论（每帖前 3 条）经 `backend/services/comment_loader.py` 进入 Agent 分析文本与简报语料；关联口径为裸 note_id（processed_posts.note_id 需剥 `xhs:` 前缀）。评论只影响情绪/风险与简报，不进聚类嵌入。
