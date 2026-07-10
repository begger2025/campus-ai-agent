# 知乎爬虫深度改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 知乎爬虫按"微博模式 + 服务端增强"完整对齐四平台管线，并接入主项目入库链路与面板。

**Architecture:** 爬取端整页管线（宽泛词拦截→主题限定→run_history→jitter→按入库数配额→窗口双层→主题/营销过滤→跳过已入库→精确计数）；防重复 = 模型 unique + store 自愈 + 批量已存查询；主项目 = sync 映射 + 索引迁移 TARGETS + 建表脚本 + 前端选项。

**Tech Stack:** Python (pytest / unittest, SQLAlchemy async), Vue3。设计文档：`docs/superpowers/specs/2026-07-10-zhihu-crawler-retrofit-design.md`（先通读）。

**分支**：`feature/zhihu-crawler`（已建）。**基线**：MediaCrawler pytest `115 passed + 1 failed`（唯一失败 `test_store_factory.py::test_create_excel_store` 为既有遗留，永不修）；主项目 unittest `Ran 142 tests OK`。

**测试命令**：
- MediaCrawler：`cd MediaCrawler && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests -q`
- 主项目：仓库根 `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m unittest discover -s backend/tests -t . -q`

**必读参考实现（本会话刚审查通过的同构代码，接线 API 一律照抄）**：
- `MediaCrawler/media_platform/weibo/core.py:139-330`（管线顺序、RunState 接线、配额循环、page_resolved_ts 约束）
- `MediaCrawler/media_platform/tieba/core.py`（_handle_search_notes 返回入库数的精确计数模式）
- `MediaCrawler/tools/{topic_scope,crawl_quota,run_history,publish_time_window}.py` 与 `store/run_history.py`
- `MediaCrawler/store/xhs/_store_impl.py`（IntegrityError 自愈 + batch_get_existing_note_ids）
- `MediaCrawler/tests/test_tieba_search_flow.py`（mock 边界方式）
- 主项目 `scripts/create_crawler_run_history.py`（建表脚本风格）、`scripts/sync_media_to_raw_posts.py`

---

## Task Z1: 配置 + SearchTime 档位纯函数

**Files:**
- Modify: `MediaCrawler/config/zhihu_config.py`（追加 `ZHIHU_SEARCH_SORT = ""`，注释注明可选值 `"" | upvoted_count | created_time`）
- Modify: `MediaCrawler/config/base_config.py`（`WEIBO/TIEBA_SKIP_EXISTING_NOTES` 旁追加 `ZHIHU_SKIP_EXISTING_NOTES = True`）
- Modify: `MediaCrawler/tools/publish_time_window.py`（新增纯函数）
- Test: `MediaCrawler/tests/test_publish_time_window.py`

- [ ] **Step 1: 写失败测试**（追加到既有测试文件，unittest/pytest 风格与文件内一致）

```python
DAY_MS = 24 * 3600 * 1000

class TestPickZhihuSearchTimeValue:
    NOW = 1_800_000_000_000  # 固定 now，毫秒

    def _lo(self, days_ago: float) -> int:
        return int(self.NOW - days_ago * DAY_MS)

    def test_no_window_returns_default(self):
        assert pick_zhihu_search_time_value(None, self.NOW) == ""

    def test_buckets(self):
        assert pick_zhihu_search_time_value(self._lo(0.5), self.NOW) == "a_day"
        assert pick_zhihu_search_time_value(self._lo(1), self.NOW) == "a_day"      # 边界含
        assert pick_zhihu_search_time_value(self._lo(6.9), self.NOW) == "a_week"
        assert pick_zhihu_search_time_value(self._lo(7), self.NOW) == "a_week"
        assert pick_zhihu_search_time_value(self._lo(31), self.NOW) == "a_month"
        assert pick_zhihu_search_time_value(self._lo(92), self.NOW) == "three_months"
        assert pick_zhihu_search_time_value(self._lo(183), self.NOW) == "half_a_year"
        assert pick_zhihu_search_time_value(self._lo(366), self.NOW) == "a_year"

    def test_older_than_a_year_returns_default(self):
        assert pick_zhihu_search_time_value(self._lo(400), self.NOW) == ""

    def test_future_lo_clamps_to_smallest_bucket(self):
        assert pick_zhihu_search_time_value(self.NOW + DAY_MS, self.NOW) == "a_day"
```

- [ ] **Step 2: 跑测试确认失败**（ImportError: pick_zhihu_search_time_value 不存在）
- [ ] **Step 3: 最小实现**（返回字符串值而非枚举，避免 tools→media_platform 反向依赖；core 侧用 `SearchTime(value)` 转换）

```python
_ZHIHU_TIME_BUCKETS = (
    (1, "a_day"), (7, "a_week"), (31, "a_month"),
    (92, "three_months"), (183, "half_a_year"), (366, "a_year"),
)

def pick_zhihu_search_time_value(window_lo_ms: Optional[int], now_ms: int) -> str:
    """按窗口起点距今天数选知乎服务端时间档位；覆盖不到（>1年）或无窗口返回 ""（不限）。"""
    if window_lo_ms is None:
        return ""
    days = max((now_ms - window_lo_ms) / (24 * 3600 * 1000), 0.0)
    for limit, value in _ZHIHU_TIME_BUCKETS:
        if days <= limit:
            return value
    return ""
```

- [ ] **Step 4: 跑测试全绿**，config 两处追加（纯配置无测试）
- [ ] **Step 5: Commit** `feat(crawler): 知乎配置与服务端时间档位映射纯函数`

---

## Task Z2: 模型 unique + store 自愈 + 批量已存查询

**Files:**
- Modify: `MediaCrawler/database/models.py`（`ZhihuContent.content_id`、`ZhihuComment.comment_id` 两列加 `unique=True`）
- Modify: `MediaCrawler/store/zhihu/_store_impl.py`（`ZhihuDbStoreImplement.store_content/store_comment`）
- Modify: `MediaCrawler/store/zhihu/__init__.py`（新增 `batch_get_existing_note_ids`）
- Test: `MediaCrawler/tests/test_zhihu_store.py`（新文件）

- [ ] **Step 1: store 自愈改造**——insert 分支照抄 `store/xhs/_store_impl.py` 的模式：`session.add(...)` 后 `await session.flush()`，外层 `try/except IntegrityError → await session.rollback() → 重查该 id → 存在则逐字段 setattr 更新 → commit`。store_content 与 store_comment 同构各改一处。
- [ ] **Step 2: `batch_get_existing_note_ids` 写失败测试**（模块级包装的优雅降级——非 db 存储时返回空集不抛错）：

```python
import pytest
from store import zhihu as zhihu_store

@pytest.mark.asyncio
async def test_batch_get_existing_note_ids_degrades_to_empty_for_non_db(monkeypatch):
    import config
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "csv")
    result = await zhihu_store.batch_get_existing_note_ids(["a", "b"])
    assert result == set()

@pytest.mark.asyncio
async def test_batch_get_existing_note_ids_empty_input(monkeypatch):
    import config
    monkeypatch.setattr(config, "SAVE_DATA_OPTION", "db")
    result = await zhihu_store.batch_get_existing_note_ids([])
    assert result == set()
```

- [ ] **Step 3: 实现**——照抄 `store/xhs/__init__.py` 的 batch_get_existing_note_ids 包装（getattr/callable 判空降级）与 `store/xhs/_store_impl.py` 的实现（`select(ZhihuContent.content_id).where(ZhihuContent.content_id.in_(ids))`，出参统一 `str` 集合）。
- [ ] **Step 4: pytest 全绿（115+新增），Commit** `feat(crawler): 知乎防重复对齐——unique 列、冲突自愈、批量已存查询`

---

## Task Z3: --fresh 接入知乎排序

**Files:**
- Modify: `MediaCrawler/cmd_arg/arg.py`（fresh 分支追加一行 `config.ZHIHU_SEARCH_SORT = "created_time"`）
- Test: `MediaCrawler/tests/test_cmd_arg.py`

- [ ] **Step 1: 在既有 fresh 用例中追加断言**（yes → `ZHIHU_SEARCH_SORT == "created_time"`；默认/no → 保持 config 原值），跑出 RED
- [ ] **Step 2: 实现一行，跑 GREEN**（restore_config fixture 已快照全部大写 config 键，自动覆盖新键）
- [ ] **Step 3: Commit** `feat(crawler): --fresh 预设扩展知乎最新排序`

---

## Task Z4: core.py search() 重写（核心任务）

**Files:**
- Modify: `MediaCrawler/media_platform/zhihu/core.py`（search 方法整体替换 + import 补充）
- Test: `MediaCrawler/tests/test_zhihu_search_flow.py`（新文件，mock 边界方式仿 `test_tieba_search_flow.py`）

**先读**：`weibo/core.py:139-330` 全文——RunState 构造/mark_stop/finish/保存的**准确调用方式一律照抄微博**（含 try/except/finally 结构与 stop_reason 五法定值）。

- [ ] **Step 1: 把"单页处理"拆出可测方法**。新增 `_filter_and_store_page(self, content_list, window_lo, window_hi, window_enabled, run_state) -> Tuple[List[ZhihuContent], List[int]]`：返回（本页实际入库成功的内容列表, page_resolved_ts）。职责与顺序：

```python
async def _filter_and_store_page(self, content_list, window_lo, window_hi, window_enabled, run_state):
    page_resolved_ts: List[int] = []
    kept: List[ZhihuContent] = []
    window_filtered = topic_filtered = marketing_filtered = 0
    topic_terms = getattr(config, "TOPIC_RELEVANCE_TERMS", [])
    for content in content_list:
        ts_ms = int(content.created_time) * 1000 if content.created_time else None
        if ts_ms is not None:
            page_resolved_ts.append(ts_ms)
        if window_enabled and not is_within_window(ts_ms, window_lo, window_hi, config.PUBLISH_TIME_KEEP_UNKNOWN):
            window_filtered += 1
            continue
        texts = [content.title, content.desc, content.content_text]
        if getattr(config, "ENABLE_TOPIC_RELEVANCE_FILTER", False) and not matches_topic(texts, topic_terms):
            topic_filtered += 1
            continue
        if getattr(config, "ENABLE_TOPIC_NEGATIVE_FILTER", False) and is_marketing_noise(
            texts, getattr(config, "TOPIC_NEGATIVE_TERMS", []), getattr(config, "TOPIC_NEGATIVE_RESCUE_TERMS", [])
        ):
            marketing_filtered += 1
            continue
        kept.append(content)
    # 日志打三类过滤计数（各自 >0 才打），文案与微博/贴吧一致
    # 跳过已入库：必须在过滤后、入库前；page_resolved_ts 已收集完毕，不受影响
    if kept and bool(getattr(config, "ZHIHU_SKIP_EXISTING_NOTES", True)):
        existing = await zhihu_store.batch_get_existing_note_ids(
            [str(c.content_id or "").strip() for c in kept]
        )
        if existing:
            before = len(kept)
            kept = [c for c in kept if str(c.content_id or "").strip() not in existing]
            if before - len(kept):
                utils.logger.info(f"[ZhihuCrawler.search] 跳过已入库 {before - len(kept)} 条")
    stored: List[ZhihuContent] = []
    for content in kept:
        try:
            await zhihu_store.update_zhihu_content(content)
            stored.append(content)
            run_state.add_stored(1)
        except Exception as ex:
            utils.logger.error(f"[ZhihuCrawler.search] store failed content_id={content.content_id}: {ex}")
    return stored, page_resolved_ts
```

- [ ] **Step 2: 写失败测试**（monkeypatch 打在 `media_platform.zhihu.core` 模块引用的 `zhihu_store` 上；构造 ZhihuContent 假对象只需 content_id/title/desc/content_text/created_time 字段；用真实 config 词表）。用例：
  1. 含"中山大学"的内容通过、无关内容被主题过滤且不计 stored；
  2. 营销文案（"考研机构春季班火热报名"）被过滤，"有没有靠谱的考研机构求推荐"救回；
  3. skip-existing：mock batch_get_existing_note_ids 返回其中一个 id → 该条不入库不计数，page_resolved_ts 仍含它的时间；
  4. store 抛异常的条目不计 stored；
  5. 窗口过滤：created_time 早于窗口起点的条目被过滤但贡献 page_resolved_ts。
- [ ] **Step 3: 实现 Step 1 代码跑 GREEN**
- [ ] **Step 4: 重写 search() 主循环**（结构照抄微博，知乎特有点标注）：

```python
async def search(self) -> None:
    utils.logger.info("[ZhihuCrawler.search] Begin search zhihu keywords")
    zhihu_limit_count = 20
    if config.CRAWLER_MAX_NOTES_COUNT < zhihu_limit_count:
        config.CRAWLER_MAX_NOTES_COUNT = zhihu_limit_count
    start_page = config.START_PAGE
    window_lo, window_hi = parse_window(config.CRAWL_PUBLISH_TIME_START, config.CRAWL_PUBLISH_TIME_END)
    window_enabled = window_lo is not None or window_hi is not None
    sort_value = str(getattr(config, "ZHIHU_SEARCH_SORT", "") or "")
    search_sort = SearchSort(sort_value) if sort_value else SearchSort.DEFAULT
    search_time = SearchTime(pick_zhihu_search_time_value(window_lo, utils.get_current_timestamp()))
    for keyword in config.KEYWORDS.split(","):
        # 1) 宽泛词拦截（原始词判定，compose 之前）——照抄微博的 is_broad_keyword 块
        # 2) compose_topic_keyword + source_keyword_var.set + 日志——照抄微博
        # 3) RunState 创建（platform="zhihu"）——照抄微博 try/except/finally 结构
        # 4) jitter：仅 search_sort == SearchSort.DEFAULT 时执行——块内照抄微博
        # 5) 配额循环：while should_fetch_next_page(run_state.items_stored, run_state.pages_fetched,
        #        config.CRAWLER_MAX_NOTES_COUNT, config.CRAWL_MAX_PAGES_PER_KEYWORD):
        #    页 skip 分支（page < keyword_start_page → page+=1; continue，不计 pages_fetched）
        #    content_list = await self.zhihu_client.get_note_by_keyword(
        #        keyword=keyword, page=page, sort=search_sort, search_time=search_time)  # 知乎特有
        #    run_state.add_page(); run_state.add_seen(len(content_list))
        #    空页 → mark_stop("empty_page"); break
        #    stored, page_resolved_ts = await self._filter_and_store_page(...)
        #    评论：await self.batch_get_content_comments(stored)  # 只对新入库内容
        #    早停：search_sort == SearchSort.CREATE_TIME 且 window_lo 且 page_resolved_ts
        #          且全部 < window_lo → mark_stop("window_exhausted") 后 break
        #          （五法定值：quota_reached|empty_page|window_exhausted|exception|completed）
        #    sleep(config.CRAWLER_MAX_SLEEP_SEC); page += 1
        # 6) DataFetchError/Exception：mark_stop(exception) + 日志 + break 本关键词
        #    （finally 落行后 for 循环自然 continue 下一关键词——不再 return）
        # 7) finally：run_state.finish() + 保存一行（调用方式照抄微博）
```

  **强制要求**：stop_reason 只用五法定值（以 `tools/run_history.py` 定义为准）；`get_note_by_keyword` 的 `search_time` 形参名以 `client.py:189-224` 实际签名为准（先读）；quota_reached 归结逻辑照抄微博循环后判定。
- [ ] **Step 5: 全量 pytest**（应 115+新增 全绿 + 1 既有失败）；导入冒烟 `./.venv/Scripts/python.exe -c "import media_platform.zhihu.core"`
- [ ] **Step 6: Commit** `feat(crawler): 知乎搜索重写——微博模式管线+服务端排序/时间档+爬取历史`

---

## Task Z5: 主项目 sync 接入 zhihu

**Files:**
- Modify: `scripts/sync_media_to_raw_posts.py`
- Test: 主项目既有 sync 测试模块（先 `grep -rn "sync_media" backend/tests/` 找到，追加用例）

- [ ] **Step 1: 写失败测试**——`_zhihu_created_at` 容错三态 + 行映射：

```python
def test_zhihu_created_at_normal_seconds(self):
    # created_time="1750000000"（秒级字符串）→ datetime.fromtimestamp(1750000000)
def test_zhihu_created_at_zero_falls_back_to_add_ts(self):
    # created_time="0"、add_ts=1750000000000（毫秒）→ fromtimestamp(1750000000)
def test_zhihu_created_at_garbage_falls_back_to_add_ts(self):
    # created_time="abc" 同上回退
def test_zhihu_row_mapping(self):
    # voteup_count=12 → like_count=12；comment_count 直通；collect/share=0；
    # tags_json="[]"；external_id=content_id；url=content_url；source_keyword 透传
```

- [ ] **Step 2: 实现**——`SUPPORTED_PLATFORMS = {"xhs", "weibo", "tieba", "zhihu"}`；仿既有平台新增 `_zhihu_rows`（`SELECT ... FROM zhihu_content`）与映射函数；`--refresh` 的 ENGAGEMENT_FIELDS 对 zhihu 只刷 like_count（voteup）与 comment_count（其余两项恒 0 不刷）。时间转换函数与既有平台同一时区口径（读现有 xhs/weibo 转换代码后保持一致）。
- [ ] **Step 3: 主项目 unittest 全绿（142+新增），Commit** `feat(sync): raw_posts 同步接入知乎（voteup→点赞，秒级时间容错）`

---

## Task Z6: 索引迁移 TARGETS + 建表脚本

**Files:**
- Modify: `scripts/add_crawler_unique_indexes.py`（TARGETS 追加 zhihu_content.content_id、zhihu_comment.comment_id 两元组，格式照抄既有六元组）
- Create: `scripts/create_zhihu_tables.py`（整体结构照抄 `scripts/create_crawler_run_history.py`：plan/apply 分离、--dry-run、退出码、幂等）
- Test: 既有索引脚本测试模块追加断言 + `backend/tests/test_create_zhihu_tables.py`（新）

- [ ] **Step 1: TARGETS 追加 + 既有计数断言同步更新**（6→8 属行为扩展，非弱化；先跑 RED 确认旧断言抓到数量变化）
- [ ] **Step 2: 建表脚本**——DDL 与 `MediaCrawler/database/models.py` 的三张知乎表逐列一致（String→VARCHAR、Text→TEXT、Integer/BigInteger、default），**content_id/comment_id/user_id 直接建 UNIQUE INDEX**（索引名沿用 SQLAlchemy 默认 `ix_zhihu_*` 命名 + unique），utf8mb4/InnoDB。三张表逐一 plan（存在→skip_exists）。测试：DDL 字符串断言（每表列清单/UNIQUE/引擎）、план三态、dry-run 不执行（假 apply_fn 锁死）、退出码。
- [ ] **Step 3: 全绿后 Commit** `feat(scripts): 知乎三表建表脚本 + 唯一索引迁移目标扩展`（**不在本任务连线上库**）

---

## Task Z7: 前端平台选项

**Files:**
- Modify: `frontend/src/views/AdminKeywordsView.vue`（`PLATFORM_OPTIONS` 追加 `{ label: "知乎", value: "zhihu" }`）

- [ ] **Step 1: 改一行 → `cd frontend && npm run build` 通过（dist 在 .gitignore，不提交）**
- [ ] **Step 2: Commit** `feat(admin-keywords): 复制命令平台选项加知乎`

---

## Task Z8: 全量验证

- [ ] MediaCrawler pytest：期望 `115+新增 passed, 1 failed`（仅既有 excel）
- [ ] 主项目 unittest：期望 `Ran 142+新增 tests OK`
- [ ] `git log --oneline` 核对提交序列完整、工作区干净

---

## 线上操作（实现完成、审查通过后，由主控执行，均需用户确认）

1. 探测线上 zhihu_content/zhihu_comment/zhihu_creator 是否存在。
2. 不存在 → `create_zhihu_tables.py --dry-run` → 用户确认 → 执行 → 幂等复跑 → 结构复验。
3. 存在 → `add_crawler_unique_indexes.py --dry-run`（新 TARGETS）→ 用户确认 → 执行。
4. 用户扫码冒烟：`python main.py --platform zhihu --keywords "宿舍" --get_comment yes --fresh yes --start_date <近14天>` → 验证入库 → `sync_media_to_raw_posts.py` → `process_raw_posts.py` → 面板。
