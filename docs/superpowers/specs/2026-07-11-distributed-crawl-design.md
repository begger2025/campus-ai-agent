# 设计：分布式协同爬取 + 限速抖动

- 日期：2026-07-11
- 状态：已批准（用户选定：方案 A 认领队列 + 随机抖动 + 关键词双来源 + CLI 管理）
- 范围：MediaCrawler/（队列模型/认领模块/队列驱动/抖动）+ 主项目 scripts/（建表/播种/监控/重置）+ 线上建表
- 目标：不触发平台风控前提下短时间获取大量数据；多名成员在各自电脑同时跑爬虫、写共享库不冲突、不重复劳动

## 1. 背景与现状

现状三个约束：
- **写共享库不冲突：已基本具备。** 六张原生表 + 快手两表均有 `note_id/comment_id` 唯一索引 +
  IntegrityError 自愈（防重复加固 + 快手改造两轮已落地）。多成员并发写同一表由数据库唯一约束
  兜底：谁先插谁赢，后到者撞约束自愈成 update，不产生重复行。`crawler_run_history` 每轮一行、
  天然不冲突。本设计只在此基础上补"瞬时错误重试"保险丝。
- **单机限速：过于保守。** `CRAWLER_MAX_SLEEP_SEC=18`（固定 18 秒/页）、`MAX_CONCURRENCY_NUM=1`。
- **多机协同：缺失。** 关键词来自 `config.KEYWORDS`（CLI）或面板复制命令，无跨机分工机制；
  多人跑同一份词表 = 重复请求（存储去重了，但平台请求白费、无横向加速）。

核心判断：**横向协同（N 成员各爬互不重叠关键词）是"短时间大量数据 + 不加风控风险"的正解**——
单机请求频率不变、单账号风控风险不变，总吞吐近似 ×N。单机加速是次要且有上限的，只做
"固定间隔改随机抖动"（降风险，不加风险）。

已确认的技术前提：
- MediaCrawler `store/run_history.py` 用 `database/db_session.get_session()`（异步）+
  `CrawlerRunHistory` 模型写入，指向的就是**共享阿里云 RDS**（与主项目同库，快手数据即经此入库）。
  故认领队列表放在该共享库、MediaCrawler 与主项目脚本均可访问。
- 建表脚本模板：`scripts/create_ks_tables.py`（幂等、plan/apply 分离、--dry-run、退出码约定）。

## 2. 队列表 `crawl_task_queue`（共享 MySQL）

| 列 | 类型 | 用途 |
|---|---|---|
| id | INT PK AUTO_INCREMENT | 主键 |
| platform | VARCHAR(16) | CLI 平台码：xhs/wb/tieba/zhihu/ks |
| keyword | VARCHAR(255) | **裸**关键词（如"宿舍"）；爬虫侧照常自动拼"中山大学" |
| status | VARCHAR(16) | pending / claimed / done / failed（默认 pending） |
| priority | INT default 0 | 排序用，大者优先（v1 播种默认 0，退化为 FIFO） |
| claimed_by | VARCHAR(64) | worker id（默认主机名，可 `--worker` 覆盖）；未认领为 NULL |
| claimed_at | BIGINT | 认领时间戳（ms） |
| lease_expires_at | BIGINT | 租约到期（ms）——机器崩溃任务不永久卡死 |
| finished_at | BIGINT | 完成时间戳（ms） |
| items_stored | INT default 0 | 结果回填：本任务新增入库条数（供监控） |
| stop_reason | VARCHAR(32) | 结果回填：run_history 的停止原因 |
| created_at | BIGINT | 播种时间戳（ms） |

索引：`INDEX ix_queue_platform_status (platform, status)`（认领候选查询走此索引）。
**不设** (platform, keyword) 唯一约束——done 过的关键词允许重新入队做定期刷新；播种去重在脚本侧
只针对"当前 pending/claimed"（见 §5）。

建表脚本 `scripts/create_crawl_task_queue.py`：照 `create_ks_tables.py` 结构（plan/apply 分离、
--dry-run、幂等 skip_exists、退出码约定；单表无需两态补列，只有 create/skip）。

## 3. 认领逻辑（版本无关，MySQL 5.7/8.0 通用）

**不依赖 `SELECT ... FOR UPDATE SKIP LOCKED`（8.0 专属）**，用乐观条件更新 + 重试，5.7/8.0 皆可：

1. **回收过期租约**（幂等，认领前先跑）：
   ```sql
   UPDATE crawl_task_queue SET status='pending', claimed_by=NULL
   WHERE platform=:p AND status='claimed' AND lease_expires_at < :now
   ```
2. **读候选**：
   ```sql
   SELECT id FROM crawl_task_queue
   WHERE platform=:p AND status='pending'
   ORDER BY priority DESC, id ASC LIMIT 1
   ```
3. **条件认领**（行级原子）：
   ```sql
   UPDATE crawl_task_queue
   SET status='claimed', claimed_by=:w, claimed_at=:now, lease_expires_at=:now+:lease_ms
   WHERE id=:id AND status='pending'
   ```
   受影响行数 == 1 → 抢到，返回该任务；== 0 → 被别人抢先，回步骤 2 换候选，重试至多 N 次
   （N 默认 5）；候选为空 → 返回 None（队列排空）。

行级条件 UPDATE 的 `WHERE status='pending'` 守卫保证两台机器绝不认领同一行——这是本设计的
并发正确性核心。完成/失败：
```sql
UPDATE crawl_task_queue
SET status=:st, finished_at=:now, items_stored=:n, stop_reason=:r
WHERE id=:id
```

**代码落点**：
- `database/models.py` 新增 `CrawlTaskQueue` 模型（列同 §2）。
- `store/crawl_queue.py` 新模块，仿 `store/run_history.py`：`get_session()` 异步执行上述 SQL；
  非 db 系存储（csv/json/...）优雅降级——`claim_task` 返回 None、`complete_task` no-op（getattr/
  callable 或 SAVE_DATA_OPTION 判定），保证队列模式在非共享库配置下不崩、只是拿不到任务。
  纯 SQL 用 `text()`（认领需受影响行数，模型 ORM 不便）。
- 配置：`config/base_config.py` 新增 `CRAWL_QUEUE_LEASE_SEC = 1800`（30 分钟租约）、
  `CRAWL_QUEUE_CLAIM_RETRY = 5`。

## 4. 队列驱动运行模式

- **CLI/config**：`cmd_arg/arg.py` 新增 `--from-queue`（yes/no，默认 no）→ `config.CRAWL_FROM_QUEUE`；
  新增 `--worker`（worker id 字符串，默认空 → 运行时取 `socket.gethostname()`）→ `config.CRAWL_WORKER_ID`。
- **five crawlers `start()`**：登录成功后、`if config.CRAWLER_TYPE == "search"` 分支内改为：
  ```python
  if config.CRAWLER_TYPE == "search":
      if getattr(config, "CRAWL_FROM_QUEUE", False):
          await run_keyword_queue(self)     # 共享 helper
      else:
          await self.search()               # 原行为，完全不变
  ```
  （detail/creator 模式不受影响。）
- **共享 helper `run_keyword_queue(crawler)`**（放 `tools/crawl_queue_runner.py` 或 store 模块）：
  ```
  worker = config.CRAWL_WORKER_ID or socket.gethostname()
  platform = config.PLATFORM
  while True:
      task = await claim_task(platform, worker)          # §3
      if task is None: break                              # 队列排空
      before_id = await max_run_history_id(platform)      # 结果回填基准
      config.KEYWORDS = task["keyword"]                   # 单关键词
      try:
          await crawler.search()                          # 复用各平台既有 search()
          stored, reason = await run_history_delta(platform, before_id)  # 读新增行汇总
          await complete_task(task["id"], "done", stored, reason)
      except Exception as ex:
          await complete_task(task["id"], "failed", 0, "exception")
          utils.logger.error(...)                          # 标 failed 但不中断循环
  ```
  - **结果回填**：`search()` 每关键词写一行 run_history。helper 记录调用前该平台
    `max(id)`，调用后取 `id > before_id` 的新增行，汇总 `items_stored`、取其 `stop_reason`。
    宽泛词被拦截时 search 不写 run_history 行（无新增行）→ 回填 `stored=0, reason='skipped'`。
  - **异常隔离**：单任务 search 抛异常 → 标 failed、记日志、**继续认领下一个**，不让一个坏关键词
    终止整台机器的采集（与 search() 内部"DataFetchError 只中断当前关键词"同一哲学，此处再兜一层）。
  - 非队列模式（不带 `--from-queue`）：以上分支全部不进入，行为逐字节不变。

## 5. CLI 脚本（播种 / 监控 / 重置）

均在主项目根、用根 `.venv`、连共享库；用 sync SQLAlchemy engine（`backend.database.engine`）。

**`scripts/seed_crawl_queue.py`** —— 双来源播种：
- `--from-recommendations --platform ks --top 20`：调现有关键词推荐（keyword_planner，主项目已
  synced），取 top-N 裸关键词，为指定平台灌 pending 任务。
- `--keywords "宿舍,食堂" --platform ks,zhihu`：手动，平台 × 关键词笛卡尔积。
- 两模式均可带 `--priority N`（默认 0）、`--dry-run`。
- **去重**：只对**当前 status ∈ {pending, claimed} 的 (platform, keyword)** 跳过（避免堆积重复待爬）；
  done/failed 过的同词允许重新入队（支持定期刷新）。
- 纯逻辑（去重、笛卡尔积、行构造）与 DB 写入分离，便于单测。

**`scripts/crawl_queue_status.py`** —— 监控：
- 按平台聚合 pending / claimed / done / failed 计数；
- 列出 claimed 任务：谁（claimed_by）在爬哪个 keyword、认领多久、租约是否将过期；
- 标出卡死任务（status=claimed 且 lease_expires_at < now，回收前的可见提示）。

**`scripts/reset_crawl_queue.py`** —— 重置：
- `--requeue-claimed`（把卡死/在爬的 claimed 打回 pending）、`--requeue-failed`、
  `--clear-done`（清完成行）、`--platform` 过滤、`--dry-run`。破坏性操作打印将影响行数、需确认。

## 6. 限速改随机抖动

- `config/base_config.py`：新增 `CRAWLER_MIN_SLEEP_SEC = 8`；`CRAWLER_MAX_SLEEP_SEC` 保留（默认 18）。
  语义：翻页/请求间隔从"固定 18 秒"改为"[MIN, MAX] 均匀随机"。
- 新增抖动 helper（放 `tools/utils.py`）：`async def random_sleep_sec(min_s, max_s)` →
  `await asyncio.sleep(random.uniform(min_s, max_s))`；`min > max` 或任一非法时回退到 `max_s`
  固定睡（防误配）。
- 替换五个 core 中**翻页处**的固定 `await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)`
  为 `await random_sleep_sec(config.CRAWLER_MIN_SLEEP_SEC, config.CRAWLER_MAX_SLEEP_SEC)`。
  小红书详情自己的 `XHS_DETAIL_*_SLEEP_*` 区间**不动**（已是随机区间）。
- 理据：固定间隔比随机更易被行为指纹识别为机器人；本改动**降风险**，非提速冒险。

## 7. 并发写加固（次要保险丝）

现有唯一索引 + IntegrityError 自愈已保证多成员并发写不产生重复行。补一层瞬时错误重试：
store 的 DB 实现里，对 `commit()`/`flush()` 包一个小重试（捕获 MySQL 死锁 1213 / 锁等待超时
1205 → 短暂退避后重试至多 2~3 次，仍失败则记警跳过该条不崩）。不同成员爬不同关键词、行争用低，
死锁罕见，此为保险丝。**实现上抽一个共享装饰器/helper，仅接入已有自愈路径**，避免五份 store 各写一遍。

## 8. 测试与验收

- **MediaCrawler pytest**（基线 154 通过 + 1 既有 excel 失败，只增不改）：
  - 认领纯逻辑：乐观条件更新竞态（第一次候选被抢→重试第二候选成功）、租约回收（过期 claimed
    打回 pending）、重试耗尽返回 None、非 db 后端优雅降级——mock async session（AsyncMock，
    受影响行数 rowcount 驱动分支）。
  - 队列驱动循环：fake claim（预置任务序列，末尾 None）+ fake crawler.search（可注入抛异常）
    → 断言认领顺序、failed 不中断、结果回填、队列排空退出。
  - 抖动 helper：区间边界、min>max 回退、非法值回退（monkeypatch random）。
  - 瞬时错误重试：注入 OperationalError(1213) → 重试后成功 / 耗尽跳过不抛。
- **主项目 unittest**（基线 202 OK，只增不改）：
  - seed 纯逻辑：去重（跳过当前 pending/claimed）、笛卡尔积、priority、行构造；
  - status 汇总纯逻辑（给定行快照 → 计数/卡死判定）；
  - reset 纯逻辑（给定过滤 → 目标行集）；
  - 建表脚本纯逻辑（plan/apply、DDL 断言含索引）。
- **线上**：`create_crawl_task_queue.py --dry-run` → 用户确认 → 执行 → 幂等复跑全 skip。
- **冒烟**（我无法代跑多机）：用户 + 队友两台机各 `main.py --platform ks --from-queue yes`，
  先 `seed_crawl_queue.py --keywords "词1,词2,词3,词4" --platform ks` 灌 4 个任务，观察
  `crawl_queue_status.py`：两机各认领不重叠子集、无一任务被双认领、库内无重复行、队列最终全 done。

## 9. 范围外

- 跨平台账号池 / IP 代理池（风控的另一维度，独立课题，不在此）；
- 队列优先级调度算法（v1 只 FIFO + priority 字段，不做动态权重）；
- 面板可视化播种/监控（CLI 已够用，后续可加一个 Admin 页复用这些脚本逻辑）；
- 单关键词内部断点续爬（任务粒度到关键词即可，一个关键词一轮内失败整轮重来）；
- 分布式限流（跨机全局 QPS 协调——各机独立账号/IP，单机限速已足够，不做全局令牌桶）。
