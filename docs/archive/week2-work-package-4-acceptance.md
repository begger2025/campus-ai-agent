# 后端工作包4验收记录：统一同步入口

检查时间：2026-06-05

## 1. 工作包目标

本工作包建立统一数据链路：

```text
MediaCrawler 原生表 / 增强 JSON / JSONL
        -> raw_posts
        -> processed_posts
        -> OpinionNote
        -> 公共舆情 Agent
```

目标不是让 Agent 直接读取 `xhs_note`、`weibo_note`、`tieba_note`，而是让所有采集来源先进入主项目统一表，再由 `processed_posts` 提供 Agent 输入。

## 2. 本次完成内容

### 2.1 表结构补齐

已给 `raw_posts` 补齐工作包4要求的字段：

```text
source_raw_id
```

该字段用于记录来源平台原生表中的主键，例如：

```text
xhs_note.id
weibo_note.id
tieba_note.id
```

已同步修改：

- `backend/models.py`
- `backend/schemas.py`
- `scripts/sql/wp1_create_tables_mysql.sql`
- `scripts/check_wp2.py`

并新增：

- `scripts/ensure_wp4_schema.py`

共享 MySQL 已执行加法迁移：

```text
[OK] added: raw_posts.source_raw_id
```

### 2.2 MediaCrawler -> raw_posts

新增脚本：

```text
scripts/sync_media_to_raw_posts.py
```

支持：

```text
--platform xhs
--platform weibo
--platform tieba
--platform all
--json-path xxx.json
--json-path xxx.jsonl
--limit 100
--dry-run
```

去重规则：

```text
platform + external_id
```

输出字段：

```text
platform
scanned
inserted
skipped_duplicate
failed
```

### 2.3 raw_posts -> processed_posts

新增脚本：

```text
scripts/process_raw_posts.py
```

清洗处理包括：

- 跳过已处理的 `raw_post_id`
- 清洗标题和正文空白
- 生成 `note_id = platform + ":" + external_id`
- 统一 `publish_date` 和 `publish_time_raw`
- 复制 tags/images/url/author 等 Agent 输入字段
- 计算热度分

热度分规则：

```text
heat_score = like_count * 1.0
           + collect_count * 1.5
           + comment_count * 3.0
           + share_count * 2.5
```

### 2.4 processed_posts -> OpinionNote

新增 Agent 输入适配：

```text
agent/opinion_input.py
```

提供：

```python
load_opinion_notes_from_db()
processed_post_to_opinion_note()
OpinionNote
```

后续公共舆情 Agent 可直接从 `processed_posts` 加载统一结构，不需要关心数据来自小红书、微博、贴吧还是增强 JSONL。

### 2.5 验收脚本

新增：

```text
scripts/check_wp4.py
check_wp4.bat
```

验收内容：

- 是否使用共享 MySQL
- MediaCrawler 原生表和主项目业务表是否存在
- `raw_posts.source_raw_id` 是否存在
- `xhs_note` dry-run 是否能扫描
- `raw_posts` 是否已有数据
- `processed_posts` 是否已有数据
- `processed_posts` 是否能转换为 `OpinionNote`

## 3. 实际执行结果

### 3.1 初始数据状态

本次开始前共享 MySQL 状态：

```text
xhs_note: 182
weibo_note: 0
tieba_note: 0
raw_posts: 0
processed_posts: 0
```

### 3.2 同步 dry-run

命令：

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 5 --dry-run
```

结果：

```text
[DRY-RUN] no rows were inserted
platform=xhs scanned=5 inserted=5 skipped_duplicate=0 failed=0
total scanned=5 inserted=5 skipped_duplicate=0 failed=0
```

### 3.3 正式同步

命令：

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform all --limit 100
```

结果：

```text
platform=xhs scanned=100 inserted=100 skipped_duplicate=0 failed=0
platform=weibo scanned=0 inserted=0 skipped_duplicate=0 failed=0
platform=tieba scanned=0 inserted=0 skipped_duplicate=0 failed=0
total scanned=100 inserted=100 skipped_duplicate=0 failed=0
```

说明：当前共享库中只有 `xhs_note` 有数据，`weibo_note` 和 `tieba_note` 暂为空。

### 3.4 重复同步验证

命令：

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 5 --dry-run
```

结果：

```text
[DRY-RUN] no rows were inserted
platform=xhs scanned=5 inserted=0 skipped_duplicate=5 failed=0
total scanned=5 inserted=0 skipped_duplicate=5 failed=0
```

结论：重复同步不会重复插入。

### 3.5 raw_posts 清洗为 processed_posts

dry-run 命令：

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 5 --dry-run
```

结果：

```text
[DRY-RUN] no rows were inserted
scanned=5 inserted=5 skipped_duplicate=0 skipped_empty=0 failed=0
```

正式处理命令：

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 100
```

结果：

```text
scanned=100 inserted=100 skipped_duplicate=0 skipped_empty=0 failed=0
```

### 3.6 OpinionNote 加载验证

命令：

```powershell
.\.venv\Scripts\python.exe -m agent.opinion_input
```

结果：

```text
OpinionNote count: 5
- xhs:685b42d90000000022031ecf | ... | keyword=中山大学 | heat=61364.0
- xhs:69e59cf0000000001f003f84 | ... | keyword=中山大学 | heat=20177.0
- xhs:69fdb429000000003701db04 | ... | keyword=中山大学 | heat=18235.5
- xhs:693a573d000000001f00e5b7 | ... | keyword=中山大学 | heat=17291.5
- xhs:672c353f000000001d03b107 | ... | keyword=中山大学 | heat=16334.0
```

### 3.7 工作包4完整验收

命令：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py
```

结果：

```text
[OK] Using shared MySQL
[OK] MediaCrawler and main project tables present
[OK] raw_posts.source_raw_id present
[OK] xhs dry-run scanned 3 rows
[OK] raw -> processed dry-run callable (scanned=0, insertable=0)
[INFO] xhs_note: 182 rows
[INFO] weibo_note: 0 rows
[INFO] tieba_note: 0 rows
[INFO] raw_posts: 100 rows
[INFO] processed_posts: 100 rows
[OK] raw_posts row count >= 1
[OK] processed_posts row count >= 1
[OK] processed_posts can be loaded as OpinionNote

WP4 data pipeline checks PASSED.
```

### 3.8 工作包2回归验收

由于本次新增了 `raw_posts.source_raw_id`，已重新执行工作包2结构验收。

结果：

```text
WP2 schema checks PASSED.
```

### 3.9 /api/posts 验证

由于当前虚拟环境缺少 `httpx/httpx2`，无法使用 `fastapi.testclient.TestClient`。已改为直接调用同一套后端路由函数验证查询逻辑。

结果：

```text
code: 0
total: 100
items: 5
sample: platform=xhs, source_table=xhs_note, source_raw_id=168
```

结论：`/api/posts` 对应的后端查询逻辑已经能从 `raw_posts` 返回同步后的统一数据。

## 4. 当前共享数据库状态

核心数据量：

```text
xhs_note: 182
weibo_note: 0
tieba_note: 0
raw_posts: 100
processed_posts: 100
```

当前完成的是从 `xhs_note` 接入。微博、贴吧表已纳入同一套同步框架，但因为原生表当前没有数据，所以没有产生 `raw_posts` 和 `processed_posts` 记录。

## 5. 后续使用方式

### 同步平台表到 raw_posts

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform all --limit 100
```

### 先 dry-run

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 50 --dry-run
```

### 导入增强 JSON/JSONL

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --json-path data\samples\enhanced_posts.jsonl --limit 100
```

### 生成 processed_posts

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 100
```

### 验收工作包4

```powershell
.\check_wp4.bat
```

或者：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py
```

## 6. 验收结论

工作包4已完成：

- `xhs_note -> raw_posts` 已打通
- `weibo_note`、`tieba_note` 已纳入同步框架
- 增强 JSON/JSONL 已保留统一导入入口
- 重复同步不会重复插入
- `raw_posts -> processed_posts` 已打通
- `processed_posts -> OpinionNote` 已打通
- `/api/posts` 查询逻辑可以读取同步后的 `raw_posts`

当前剩余不是工作包4代码问题，而是数据来源问题：共享库中的 `weibo_note` 和 `tieba_note` 暂无数据，后续只要爬虫负责人把数据写入这两张表，同一套同步脚本即可接入。
