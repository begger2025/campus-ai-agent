# 设计：防重复机制优化（解决四个注意点）

- 日期：2026-07-10
- 状态：已批准推进（用户："优化防重复机制，解决四个如实告知的注意点"）
- 前置事实：线上库七项查重实测为 0；本次是加固与提质，非修 bug

## 背景：四个注意点

1. **原生表无 DB 级唯一约束**：xhs_note/weibo_note/tieba_note 的 note_id、三评论表的 comment_id 只是普通索引；防重靠"先查后插"，理论上并发可产生重复（现实 concurrency=1 风险极低）。
2. **文件保存模式无防重**：csv/json/jsonl/excel 无条件追加（db 模式不受影响，但切换即漏）。
3. **互动数冻结**：同一帖再爬，新点赞/评论数只更新原生表；raw_posts/processed_posts 因"已存在即跳过、无更新路径"永远停在首次同步值——热度延续信号看不到老帖热度增长。
4. **微博/贴吧无爬取阶段跳过**：每轮把见过的帖子重抓一遍再覆盖，不产生重复行但浪费请求额度（仅小红书有 XHS_SKIP_EXISTING_NOTE_DETAILS）。

## 方案（四项，均在 MediaCrawler 内 + 主项目 scripts；主项目模型/前端/算法核心零改动）

### 注意点 1：DB 级唯一约束（堵漏，最高价值）
- **模型**：`MediaCrawler/database/models.py` 六列改 `unique=True`（note_id×3、comment_id×3），新建库 create_all 即带约束。
- **迁移**：新脚本 `scripts/add_crawler_unique_indexes.py`（主项目，走共享 .env）——对每张表：表不存在→跳过；已有唯一索引→跳过（幂等）；**先查该键重复数，>0 则拒绝并打印重复样本**（绝不在有重复时强加）；否则 `ALTER TABLE ... ADD UNIQUE INDEX`。支持 `--dry-run`。
- **store 加固**：三平台 `store_content`/`store_comment` 的 insert 分支包 `try/except IntegrityError → 回滚后转 update`，把"极罕见并发竞态"从静默重复（旧）或崩溃（加约束后）变为自愈。async session 状态需正确回滚；若 async 语义过于棘手，退化为"记录并跳过该条"并在报告说明。

### 注意点 2：文件模式进程内去重（堵漏，低价值但自包含）
- `MediaCrawler/tools/async_file_writer.py` 与 `store/excel_store_base.py`：加进程内 `seen` 集合（键=(item_type, id)，id 取 note_id/comment_id），同一 run 内重复项跳过。跨 run 文件去重不做（需全文件扫描，不划算），文档注明。

### 注意点 3：互动数刷新（提质，opt-in）
- `scripts/sync_media_to_raw_posts.py` 加 `--refresh`（默认关）：命中已存在 raw_posts 行时，更新四个互动量字段（like/collect/comment/share）为原生表最新值，计入新 `stats.updated`；不加时行为与现状逐字节一致（仍 skipped_duplicate）。
- `scripts/process_raw_posts.py` 加 `--refresh`（默认关）：对已存在 processed_posts 行，从（已刷新的）raw_post 重算四个互动量 + heat_score（复用现有打分函数），其余分析字段不动。
- 演示动线：先 `sync --refresh` 再 `process --refresh` 才能让热度延续信号反映老帖增长。

### 注意点 4：微博/贴吧爬取阶段跳过（提质，省额度）
- 复用小红书思路：微博/贴吧 core 的 search 循环，在决定抓取/入库前批量查库已存在的 note_id 并跳过。
- 新配置 `WEIBO_SKIP_EXISTING_NOTES` / `TIEBA_SKIP_EXISTING_NOTES`（默认 True）。
- 各自 store 层加 `batch_get_existing_note_ids(ids)`（仿 xhs `_store_impl.py`）。
- 跳过的帖子同时不抓其评论（读代码确认 note_id 不进评论抓取列表）。
- 注意：与主题过滤/时间窗口过滤的既有 continue 协同——跳过应在这些过滤之后、抓取之前，且不影响时间窗口的整页 page_resolved_ts 早停判据（早停看页龄，跳过看是否已入库，二者独立；已存在项仍应贡献 page_resolved_ts）。

## 测试与验收
- 纯逻辑/脚本用 unittest 或 pytest（就近既有风格）：迁移脚本的幂等与"有重复则拒绝"分支、文件去重 seen 集合、refresh 的 updated 计数与"默认关不改行为"、batch_get_existing_note_ids。
- 基线：MediaCrawler pytest 52 通过 + 1 既有失败（excel 用例）；主项目 unittest 106。新增测试全绿、无新失败。
- 线上迁移：脚本先 `--dry-run`，确认后正式跑；跑后复验唯一索引存在且七项查重仍为 0。
- 平台爬取跳过靠代码审查 + 用户真实爬取冒烟。

## 范围外
- 跨 run 文件去重；把互动数刷新做成自动/默认（保持 opt-in）；改动主项目后端模型或算法核心。
