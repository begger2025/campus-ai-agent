# 设计：关键词质量闭环（选得准 → 搜得对 → 爬得好）

- 日期：2026-07-10
- 状态：已批准（用户选定 P1 + P2 全做）
- 目标：推荐端产出高质量、可搜索的关键词；爬虫用与关键词语义匹配的策略抓回高质量相关内容；爬取结果回流推荐端，形成"推荐 → 爬取 → 反馈 → 推荐"完整闭环。

## 1. 两端审查结论（问题清单）

### 推荐端（智能选题）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| R1 | `normalize_keyword` 无最大长度限制，句子式长标签（如"我在中山大学等你来"）可成为候选词 | keyword_planner.py:83-93 | 长词作为搜索词质量差，平台检索几乎必然零命中 |
| R2 | `GENERIC_BLACKLIST` 仅 17 词，挡不住营销标签长尾（探店/穿搭/优惠等），D 信号候选噪声大 | keyword_planner.py:36-42 | 营销词混入推荐（好在纯 discovery 词分数上限 2.0，污染有界） |
| R3 | 无 LLM key 时 A 信号词表被 9 个硬编码 `KNOWN_KEYWORDS` 封顶（其中"中山大学"归一化后丢弃，有效 8 个） | intent_router.py:18,69-73 | 需求信号粒度粗（已知遗留，答辩前配 key） |
| R4 | **零产出反馈断裂**：降权数据从内容表倒推，爬过但零入库的词不留任何痕迹 → 永不降权、反复推荐、反复浪费配额 | keyword_suggestion_adapter.py:86-92 | 闭环在"搜不到"场景断裂（最重要） |

### 交接层（面板 → 爬虫）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| H1 | **语义错位**：推荐词的含义是"最近 3-7 天冒头的需求/话题"，但爬虫默认排序是 xhs 热度倒序、微博综合——捞到的是历史爆款老帖 | xhs_config.py:24、weibo_config.py:24 | 高质量关键词 → 低时效内容；老帖 published_at 旧 → C 信号衰减殆尽 → 面板看不到爬取效果 |
| H2 | CLI 无排序参数，面板复制命令无法控制搜索策略，只能改配置文件 | cmd_arg/arg.py（无 sort 选项） | 交接手段缺失 |

### 爬虫端

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| C1 | 仅 xhs 写爬取历史（`xhs_crawl_history`），且无人读；微博/贴吧零留痕 | xhs/core.py:144-172 | R4 的爬虫侧根因 |
| C2 | 微博/贴吧配额按页数计（`CRAWLER_MAX_NOTES_COUNT=10` → 恒 1 页），跳过已入库/被过滤不补页 | weibo/core.py:184、tieba/core.py:187 | 关键词一轮后"干涸"，每轮新增趋近 0 |
| C3 | 宽泛词（如裸"中山大学"）无拦截，主题过滤对其零区分力，营销/招生/旅游内容全数入库 | 全链路 | 污染 processed_posts 与 D 信号 |
| C4 | xhs 详情配额在抓取时计数、主题过滤在入库前发生，无关帖烧配额（每条含 1-3 分钟节流） | xhs/core.py:963 vs 996 | 已知设计代价（防误杀），本次不改，如实说明 |

## 2. 方案（P1 核心闭环 + P2 可选提质）

### P1-1 候选词可搜索性过滤（子项目 core → 同步主项目）

- `normalize_keyword` 增加规则：长度 > `MAX_KEYWORD_LEN = 12` 丢弃；剥离表情与首尾标点后再判长。
- `GENERIC_BLACKLIST` 扩充营销/泛化词（保守清单，避免误杀真实舆情词）：
  探店、美食、穿搭、ootd、旅游、旅行、景点、拍照、约拍、优惠、团购、种草、测评、集美、姐妹。
- 影响面：纯函数 + 常量，26 个既有测试回归 + 新增用例。

### P1-2 通用爬取历史表 `crawler_run_history`（MediaCrawler）

- 新表（`database/models.py` + 建表语句），三平台 `search()` 每个关键词跑完写一行：
  `platform, source_keyword`（组合后的词，读侧归一化对账）`, started_at, finished_at, pages_fetched, items_seen, items_stored`（过滤后真正入库数）`, stop_reason`。
- 纯追加日志表，无唯一约束；xhs 现有专表保留不动（双写，互不影响）。
- 非 db 存储模式优雅降级（跳过写入，仿 `batch_get_existing_note_ids` 的 getattr/callable 模式）。

### P1-3 贫瘠词强降权（子项目 core + 主项目 adapter）

- `plan_keywords` 新增可选参数 `barren_keywords: set[str] | None = None`（归一化后对账，向后兼容）。
- 命中贫瘠集合的词：`penalty = BARREN_PENALTY = 0.1`（替代而非叠加 0.3 的常规降权），reason 追加"近期爬过但无相关内容（已强降权）"。
- adapter 读 `crawler_run_history`（表不存在时优雅返回空，行为与现状一致）：
  - 每词取窗口内（14 天）最近一次 run；`items_stored == 0` → 入贫瘠集合；
  - 同时将历史表的 `finished_at` 并入 `crawled_at_by_keyword`（取 max）——降权时间从此不再依赖"内容表倒推"，零产出的爬取也能触发常规降权。

### P1-4 "新鲜优先"预设 + 面板命令升级（MediaCrawler CLI + 前端）

- CLI 新增 `--fresh`（yes/no，默认 no，完全向后兼容）：
  - xhs：`SORT_TYPE = "time_descending"`（同时使时间窗口早停可用）；
  - 微博：`WEIBO_SEARCH_TYPE = "real_time"`（同时使早停可用）；
  - 贴吧：本就时间倒序，无需改。
- 前端 `AdminKeywordsView.copyCommand` 升级为：
  `--platform <p> --keywords "<kw>" --get_comment yes --fresh yes --start_date <今天-14天>`
  （日期由前端 JS 计算；`--start_date` 与推荐信号的 14 天内容窗口对齐）。
- 语义对齐后的动线：推荐"最近的需求" → 爬"最近 14 天发布的帖子" → C/D 信号立刻可见。

### P1-5 微博/贴吧配额改按"新增入库条数"计（MediaCrawler）

- 循环条件从页数改为：`stored_count < CRAWLER_MAX_NOTES_COUNT and pages_fetched < CRAWL_MAX_PAGES_PER_KEYWORD`（新配置，默认 10，防无限翻页）；平台返回空页即 break。
- 被窗口/主题过滤或跳过已入库的帖子不再烧配额——与 xhs 的"新增详情数"语义对齐，根治 C2 干涸。
- 语义变化需在配置注释注明：`CRAWLER_MAX_NOTES_COUNT` 对 wb/tieba 从"约抓 N 条"变为"新增入库 N 条封顶"。

### P2-1 营销内容负面词表（MediaCrawler，可选）

- 新配置 `TOPIC_NEGATIVE_TERMS`（保守清单：留学中介、保研辅导、代写、网课推广、租房中介等）+ `ENABLE_TOPIC_NEGATIVE_FILTER = True`。
- 在既有主题过滤同点判定：命中负面词且**不含**投诉/求助语气词时丢弃并计数打日志。纯函数进 `tools/topic_scope.py`。

### P2-2 宽泛词拦截（MediaCrawler，可选）

- 搜索入口检测：关键词等于 `CRAWL_TOPIC_QUALIFIER` 本身或归一化后为空（黑名单词）→ 打印警告并跳过该关键词（新配置 `ALLOW_BROAD_KEYWORDS = False` 可放行）。
- 面板产出的词天然不触发（planner 已过滤），拦的是手输场景。

## 3. 测试与验收

- 子项目：normalize 新规则、`plan_keywords(barren_keywords=...)` 降权与 reason、向后兼容（不传参行为不变）。基线 286 → 全绿后同步主项目。
- 主项目：adapter 读历史表（存在/不存在/空表/贫瘠判定）、面板命令文案。基线 124。
- MediaCrawler：run_history 纯逻辑（行组装、stop_reason）、`--fresh` 参数覆盖、wb/tieba 新配额循环（纯函数抽取后测）、负面词表判定。基线 78 通过 + 1 既有失败（excel 用例，非本次范围）。
- 线上：`crawler_run_history` 建表走脚本 + `--dry-run`，须用户确认后执行。
- 真实爬取冒烟由用户执行（需扫码登录）。

## 4. 范围外

- LLM/向量语义相关性过滤（成本高；查询侧限定 + 词表双层已够，答辩如实说明局限）。
- 四信号公式与权重调整。
- xhs 详情配额被无关帖烧掉的问题（C4，防误杀的既有设计代价）。
- 跨 run 文件模式去重、评论级相关性过滤。
