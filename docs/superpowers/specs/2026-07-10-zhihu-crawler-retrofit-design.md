# 设计：知乎爬虫深度改造（对齐四平台管线）

- 日期：2026-07-10
- 状态：已批准（用户选定：完整对齐 + 方案一"微博模式 + 服务端增强"）
- 范围：MediaCrawler/ + 主项目 scripts/ + 前端一处；子项目 core（planner）零改动

## 1. 背景与现状

知乎爬虫是上游原始版本：老式页数配额、`DataFetchError` 吞掉整个关键词、无本项目已给
xhs/微博/贴吧做的任何管线特性（主题限定/营销过滤/宽泛词拦截/时间窗口/防饥饿/跳过已入库/
唯一索引/爬取历史），且主项目入库链路（sync_media_to_raw_posts.py）完全不认识 zhihu。

运行前提已验证：`libs/zhihu.js` 存在、execjs + Node v24 可用（x-zse-96 签名链路可行）、
登录走既有 CDP 浏览器扫码（需 d_c0 cookie）。

知乎独有优势（其他三平台均无）：搜索 API 支持**服务端排序**（`SearchSort.CREATE_TIME`
最新发布）与**服务端时间档位**（`SearchTime`：一天/一周/一月/三月/半年/一年）；搜索结果
直接含内容全文（`content_text` 为提取后纯文本），无需二段详情抓取——因此采用微博整页
模式而非小红书两段式。

## 2. 爬取端重写（media_platform/zhihu/core.py）

`search()` 按微博管线重写，顺序：

1. **宽泛词拦截**：`is_broad_keyword`，原始词判定，在 compose 之前，命中警告 + continue。
2. **主题限定**：`compose_topic_keyword`，组合后设 `source_keyword_var`。
3. **爬取历史**：每关键词一个 `RunState`，try/except/finally 落 `crawler_run_history` 一行；
   `DataFetchError` 从"return 中断全部"改为 `mark_stop(exception)` + 落行 + **continue 下一
   关键词**；stop_reason 限 5 法定值。
4. **防饥饿 jitter**：仅综合排序（`ZHIHU_SEARCH_SORT` 为空/DEFAULT）时按
   `SEARCH_START_PAGE_JITTER_PROB/MAX` 偏移起始页；最新排序时间倒序天然无饥饿，不偏移。
5. **配额**：`should_fetch_next_page(items_stored, pages_fetched, CRAWLER_MAX_NOTES_COUNT,
   CRAWL_MAX_PAGES_PER_KEYWORD)`（复用 tools/crawl_quota.py）；跳过/过滤不烧配额；
   保留 min-20 clamp（zhihu_limit_count=20）。
6. **空页 break**（empty_page）。
7. **时间窗口双层**：
   - 服务端预筛：新纯函数 `pick_zhihu_search_time(window_lo_ms, now_ms) -> SearchTime`
     （窗口起点距今 ≤1天→ONE_DAY、≤7→ONE_WEEK、≤31→ONE_MONTH、≤92→THREE_MONTH、
     ≤183→HALF_YEAR、≤366→ONE_YEAR、更早或无窗口→DEFAULT）。档位按窗口**起点**距今
     计算（保证覆盖整个窗口）；窗口关闭时恒 DEFAULT。
   - 客户端精筛：`created_time`（秒级 epoch）×1000 后 `is_within_window`；
     `PUBLISH_TIME_KEEP_UNKNOWN` 语义沿用（created_time=0 视为 unknown）。
   - 提前停止：`ZHIHU_SEARCH_SORT == "created_time"` 时整页已解析 created_time 全部早于
     窗口起点 → break（window_exhausted）；`page_resolved_ts` 在跳过已入库之前收集。
8. **主题过滤**：`matches_topic([title, desc, content_text], TOPIC_RELEVANCE_TERMS)`——
   知乎判定文本最富（含全文）。
9. **营销过滤**：`is_marketing_noise`，与主题过滤同组文本。
10. **跳过已入库**：`ZHIHU_SKIP_EXISTING_NOTES=True`（新配置），
    `zhihu_store.batch_get_existing_note_ids(content_ids)`（新增，仿 xhs 模式 +
    getattr/callable 降级），过滤后、入库前批量查。
11. **入库与计数**：逐条 `update_zhihu_content` 成功才 `add_stored(1)`；评论跟随全局
    `ENABLE_GET_COMMENTS`，仅对本页新入库内容抓取。

**--fresh**：cmd_arg 的 fresh 分支追加 `config.ZHIHU_SEARCH_SORT = "created_time"`；
`zhihu_config.py` 新增 `ZHIHU_SEARCH_SORT = ""`（默认综合）；core 调用
`get_note_by_keyword(..., sort=SearchSort(config.ZHIHU_SEARCH_SORT) if ... else DEFAULT,
search_time=pick_zhihu_search_time(...))`。

## 3. 防重复对齐

- `database/models.py`：`ZhihuContent.content_id`、`ZhihuComment.comment_id` 改
  `unique=True`（`zhihu_creator.user_id` 已 unique，不动）。
- `store/zhihu/_store_impl.py`：`store_content`/`store_comment` 的 insert 分支加
  `await session.flush()` + `except IntegrityError → rollback → 转 update`（与 xhs 同构自愈）。
- `store/zhihu/__init__.py`：新增 `batch_get_existing_note_ids(content_ids) -> Set[str]`
  （db/sqlite/postgres 之外优雅降级返回空集）。
- 主项目 `scripts/add_crawler_unique_indexes.py`：TARGETS 追加
  `("zhihu_content", "content_id", ...)`、`("zhihu_comment", "comment_id", ...)`；脚本既有
  幂等/表缺失跳过/有重复拒绝逻辑复用。
- **线上执行顺序**：先探测线上是否存在 zhihu 三张原生表；不存在 → 新幂等建表脚本
  `scripts/create_zhihu_tables.py`（仿 create_crawler_run_history.py：--dry-run、计划/执行
  分离、退出码约定；DDL 与 models.py 逐列一致、含唯一索引）建表——此时唯一索引随建表
  自带，索引迁移自动 skip；存在 → 跑索引迁移（dry-run → 用户确认 → 执行 → 幂等复跑）。

## 4. 入库链路（主项目）

`scripts/sync_media_to_raw_posts.py`：
- `SUPPORTED_PLATFORMS` 加 `"zhihu"`；新增 `_zhihu_rows` 读取 + 映射：
  `external_id=content_id`、`title=title`（回答的 title 即问题标题）、`content=content_text`、
  `created_at = datetime.fromtimestamp(created_time)`（**秒级** epoch；created_time 存于
  String(32) 列，需 int() 容错，0/空/非数字 → 回退 add_ts 毫秒转秒）、
  `like_count=voteup_count`、`comment_count=comment_count`、`collect_count=0`、
  `share_count=0`、`tags_json="[]"`（知乎无标签体系，D 新话题信号不参与——如实）、
  `url=content_url`、`source_keyword` 透传。
- `--refresh`：ENGAGEMENT_FIELDS 映射只刷 voteup→like 与 comment 两项，其余保持。
- `process_raw_posts.py` 与 heat_score 平台无关，零改动。

## 5. 面板与配置

- 前端 `AdminKeywordsView.vue` 的 `PLATFORM_OPTIONS` 加 `{ label: "知乎", value: "zhihu" }`
  （复制命令自动含 --fresh yes --start_date）。
- `config/base_config.py`：`ZHIHU_SKIP_EXISTING_NOTES = True`（与另三平台并列注释）。
- 评论沿用全局 `ENABLE_GET_COMMENTS` / `--get_comment`。

## 6. 测试与验收

- MediaCrawler pytest：`pick_zhihu_search_time` 档位边界（含无窗口/超一年）、
  `batch_get_existing_note_ids` 降级、`--fresh` 含 zhihu 排序覆盖、search 管线可测拆分
  （营销/主题/窗口过滤顺序与计数语义，仿 test_tieba_search_flow.py 的 mock 边界方式）。
  基线 115+1 → 只增不改。
- 主项目 unittest：zhihu sync 映射（created_time 容错三态：正常秒级/0/非数字）、--refresh
  只刷两字段、建表脚本纯逻辑。基线 142 → 只增不改。
- 线上操作（均先 dry-run + 用户确认）：zhihu 表探测 → 建表或索引迁移。
- 用户冒烟：扫码登录跑一轮真实爬取（如"宿舍"），验证签名→搜索→过滤→入库→sync→
  面板全链路（我无法代扫码）。

## 7. 范围外

creator/指定帖模式增强、知乎视频内容特化、二级评论策略调整、子项目算法核心改动、
跨 run 文件去重。
