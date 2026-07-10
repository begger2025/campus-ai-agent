# 设计：快手爬虫深度改造（端到端对齐五平台管线）

- 日期：2026-07-11
- 状态：已批准（用户选定：方案一"完整对齐 + 最小 schema 增强"；平台码全链路 `ks`）
- 范围：MediaCrawler/ + 主项目 scripts/、backend/、frontend/ + 线上迁移；子项目 core 零改动

## 1. 背景与现状

快手爬虫是上游最原始版本：老式页数配额（`(page - start_page + 1) * 20 <= MAX`）、
无任何管线特性（主题限定/营销过滤/宽泛词拦截/时间窗口/跳过已入库/唯一索引/爬取历史）、
搜到什么存什么。主项目入库链路完全不认识 ks。

平台事实（已核实 `client.py` 与 `graphql/search_query.graphql`）：
- 搜索 API `visionSearchPhoto` 只接受 `keyword/pcursor/searchSessionId`——**无服务端排序、
  无时间筛选**。故 `--fresh` 对 ks 为无操作；时间窗口纯客户端过滤且**无提前停止**
  （结果非时间序），靠 `CRAWL_MAX_PAGES_PER_KEYWORD=10` 兜底。
- 搜索结果自带全文：`photo.caption` + `photo.originCaption` + `photo.timestamp`（毫秒）
  ——**微博整页模式**，无需二段详情抓取。
- 上游两个隐患，本次一并消除：
  1. 翻页把页码当游标传（`pcursor=str(page)`），服务端返回的真实 `pcursor` 被丢弃；
  2. 空结果时 `continue` 不翻页 → 死循环隐患。
- 表结构短板：`video_id`/`comment_id` 仅普通索引无唯一约束；`kuaishou_video`
  **没有评论数列**（GraphQL 返回 `commentCount` 但入库时丢弃）；评论表无点赞列；
  计数列为 Text（`liked_count`）；`comment_id` 列 BigInteger 但 store 写入 str
  （MySQL 隐式转换可用，维持现状不改类型）。
- `main.py` CrawlerFactory 已含 `"ks"`，无需接线。

## 2. 爬取端重写（media_platform/kuaishou/core.py 的 search()）

按微博管线重写，顺序：

1. **宽泛词拦截**：`is_broad_keyword`，原始词判定，在 compose 之前，命中警告 + continue。
2. **主题限定**：`compose_topic_keyword`，组合后设 `source_keyword_var`。
3. **爬取历史**：每关键词一个 `RunState(platform="ks")`，try/except/finally 落
   `crawler_run_history` 一行；异常 `mark_stop(exception)` + 落行 + continue 下一关键词；
   stop_reason 限 5 法定值。
4. **翻页修正**：首页沿用 `str(起始页)`；之后**优先用响应真实 `pcursor`**
   （取不到回退"页码+1"）；响应 `pcursor == "no_more"` 或空 feeds →
   `mark_stop(empty_page)` + break（消除死循环隐患）。`searchSessionId` 继续线程回传。
5. **防饥饿 jitter**：`SEARCH_START_PAGE_JITTER_PROB/MAX` 偏移起始页
   （ks 游标兼容页码，起始页偏移可行；被跳过的页不请求、不计数）。
6. **配额**：`should_fetch_next_page(items_stored, pages_fetched, CRAWLER_MAX_NOTES_COUNT,
   CRAWL_MAX_PAGES_PER_KEYWORD)`（复用 tools/crawl_quota.py）——按**新增入库**计数，
   过滤/跳过不烧配额；min clamp 保持 20（ks 每页固定 20 条）。
7. **时间窗口**：`photo.timestamp`（毫秒）直接 `is_within_window`；
   `PUBLISH_TIME_KEEP_UNKNOWN` 语义沿用（timestamp 缺失/0 视为 unknown）。
   **无 window_exhausted 提前停止**（结果非时间序，如实）；`page_resolved_ts`
   仍在任何跳过之前收集（与微博同构，便于日志观测）。
8. **主题过滤**：`matches_topic([caption, originCaption], TOPIC_RELEVANCE_TERMS)`。
9. **营销过滤**：`is_marketing_noise`，与主题过滤同组文本。
10. **跳过已入库**：新配置 `KS_SKIP_EXISTING_NOTES = True`（base_config 与另三平台并列）；
    新增 `kuaishou_store.batch_get_existing_note_ids(video_ids)`（模块级包装 +
    db-impl 方法，非 db 后端优雅降级返回空集，仿 zhihu 模式）。
11. **入库与计数**：逐条 `update_kuaishou_video` 成功才 `add_stored(1)`；评论仅对本页
    新入库视频抓取，跟随全局 `ENABLE_GET_COMMENTS`；保留原有"疑似风控 → 取消评论任务 +
    歇 20 秒 + 刷 cookie"恢复逻辑。
12. **--fresh**：ks 无服务端排序可切，cmd_arg 零改动；面板复制命令带 `--fresh yes` 无害。

## 3. 存储加固

- `database/models.py`：`KuaishouVideo.video_id`、`KuaishouVideoComment.comment_id` 改
  `unique=True`；`KuaishouVideo` **新增 `comment_count` 列**（Text，与该表 `liked_count`
  风格一致）。
- `store/kuaishou/__init__.py`：`update_kuaishou_video` 持久化 `photo.commentCount`；
  新增 `batch_get_existing_note_ids(video_ids) -> Set[str]`。
- `store/kuaishou/_store_impl.py`：`store_content`/`store_comment` insert 分支加
  `await session.flush()` + `except IntegrityError → rollback → 转 update`（与 xhs/zhihu
  同构自愈）。
- `scripts/add_crawler_unique_indexes.py`：TARGETS 追加
  `("kuaishou_video", "video_id", "uk_kuaishou_video_video_id")`、
  `("kuaishou_video_comment", "comment_id", "uk_kuaishou_video_comment_comment_id")`。
- **线上执行顺序**：先探测线上是否存在 ks 两张原生表；
  - 不存在 → 新幂等建表脚本 `scripts/create_ks_tables.py`（仿 create_zhihu_tables.py：
    --dry-run、计划/执行分离、退出码约定；DDL 与 models.py 逐列一致、含 `comment_count`
    列与唯一索引）——索引迁移自动 skip；
  - 存在 → `create_ks_tables.py` 兼作补列迁移（表已存在时探测 `comment_count` 列，
    缺则幂等 `ALTER TABLE ADD COLUMN`，在则 skip——单脚本覆盖建表/补列两态）+
    索引迁移（dry-run → 用户确认 → 执行 → 幂等复跑；有重复值拒绝并列样本，人工清重后重跑）。

## 4. 入库链路（主项目）

`scripts/sync_media_to_raw_posts.py`：
- `SUPPORTED_PLATFORMS` 加 `"ks"`；`TABLE_BY_PLATFORM["ks"] = "kuaishou_video"`；
  `_normalize_platforms` 默认列表、CLI `--platform` choices 同步补。
- 新增 `_map_ks`：`platform="ks"`、`external_id=video_id`、`title=title`（=caption 截断）、
  `content=desc`（=caption）、`author=nickname`、`publish_time=create_time`（**毫秒** epoch
  转 datetime；0/空回退 add_ts）、`url=video_url`、`like_count=liked_count`（Text 容错转
  int，非数字 → 0）、`comment_count=comment_count`（同容错）、`collect_count=0`、
  `share_count=0`、`tags_json="[]"`（ks 标签未持久化，D 新话题信号不参与——如实）、
  `source_keyword` 透传。
- `REFRESH_FIELDS_BY_PLATFORM["ks"] = ("like_count", "comment_count")`（collect/share 恒 0，
  避免 0 覆盖）。
- `process_raw_posts.py`：`--platform` choices 补 `ks`（内核平台无关，零逻辑改动）。

`backend/services/comment_loader.py`：`PLATFORM_COMMENT_SPEC["ks"] =
{"table": "kuaishou_video_comment", "join_col": "video_id", "like_col": None}`
（评论表无点赞列，同贴吧字面量 0；add_ts 排序可用）。

`backend/routers/api.py` `_normalize_platform`：收敛 `快手`/`kuaishou` → `ks`。

## 5. 面板与前端

- `AdminKeywordsView.vue` `PLATFORM_OPTIONS` 加 `{ label: "快手", value: "ks" }`
  （复制命令 `--platform ks`；`--fresh yes` 对 ks 无操作但无害）。
- `AdminRawPostsView.vue`：筛选 `el-option` 加快手；`PLATFORM_LABELS` 加 `ks: '快手'`；
  `.source-ks` 样式（琥珀色系 `background: #fefce8; color: #a16207`，与现有四色区分）。
- `utils/postLink.js` `SEARCH_BUILDERS` 加 ks：
  `https://www.kuaishou.com/search/video?searchKey=<关键词>`（zhihu 缺口维持范围外不动）。
- `SentimentView.vue` 标签色 map 加 `'快手'`。

## 6. 测试与验收

- MediaCrawler pytest（基线 133 通过 + 1 既有失败，只增不改）：
  - `test_kuaishou_search_flow.py`：仿 test_zhihu_search_flow.py（真实 config 词表、
    mock store 边界），覆盖主题保留/丢弃、营销+救回、时间窗口、跳过已入库仍贡献
    page_ts、计数语义（过滤不烧配额）；
  - 游标推进（响应 pcursor 优先/回退页码）与 `no_more`/空页停止；
  - ks IntegrityError 自愈（并入 test_store_integrity_fallback.py 模式）与
    `batch_get_existing_note_ids` 降级/空输入（并入 test_existing_note_skip.py 模式）。
- 主项目 unittest（基线 176，只增不改）：`_map_ks` 映射（create_time 三态：正常毫秒/0
  回退/Text 计数非数字容错）、`--refresh` 只刷两字段、`_normalize_platform` ks 分支、
  comment_loader ks spec（like 字面量 0）。
- 线上操作（均先 dry-run + 用户确认）：ks 表探测 → 建表或"加列 + 索引迁移"。
- 用户冒烟（我无法代扫码）：
  `python main.py --platform ks --keywords "宿舍" --get_comment yes --start_date <近14天>`
  → `sync_media_to_raw_posts.py --platform ks` → `process_raw_posts.py --platform ks` → 面板。

## 7. 范围外

creator/指定视频模式增强、视频画面理解（仅用文案文本）、二级评论策略调整、
`comment_id` 列类型改造（BigInteger + str 写入的隐式转换维持现状）、子项目算法核心、
demo snapshot、postLink 的 zhihu 既有缺口。
