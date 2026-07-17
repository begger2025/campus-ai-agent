# 小红书两机并行续爬 · 扩容操作手册

> **本次目标**：继续补充近期小红书校园舆情语料，同时把”每个关键词最多 1 篇”安全提升到
> “每个关键词最多 3 篇”；首批稳定后，再选择性提升到 5 篇。
>
> **审核日期**：2026-07-15。运行日期变化时，30 天时间窗口必须跟着更新。
>
> **⚠️ 数字口径（2026-07-17 补注）**：本文里的”当前配置 = 1”是**撰写当时**的值；
> 扩容已按本手册完成到 B 档，`XHS_MAX_DETAIL_FETCH_PER_RUN` 现值为 **5**。
> 任何时候以 `MediaCrawler/config/base_config.py` 的实际内容为准，勿凭本文判断现值。
>
> **上一轮实测基线**：
>
> ~~~text
> crawl_task_queue：#17～#28 共 12 条，全部 done；cjt / pissy 各认领 6 条
> xhs_note：165 行，note_id 零重复
> xhs_note_comment：42 行，comment_id 零重复
> raw_posts（xhs）：165 行
> processed_posts（xhs）：165 行
> 上一轮结果：12 条详情抓取成功，11 条笔记持久化成功，1 条“选课”笔记持久化失败
> ~~~
>
> **角色**：机器 A（cjt）负责基线、单次播种、爬取、监控和后处理；机器 B（pissy）只负责爬取。
> 两台机器继续使用不同的小红书账号和同一套共享 MySQL。

---

## 一、先看结论：不要一次同时放大所有维度

当前两台机器的真实配置仍是：

~~~python
XHS_MAX_DETAIL_FETCH_PER_RUN = 1
~~~

这就是上一轮每个关键词最多只持久化 1 篇的原因。原手册里写的“每词 5 篇”不是当前文件的真实值。

本轮采用两级扩容：

| 档位 | 每词详情上限 | 关键词数 | 一级评论上限 | 理论笔记上限 | 双机预计耗时 |
|---|---:|---:|---:|---:|---:|
| **A：平衡档（推荐先跑）** | **3** | **12** | 每帖 5 条 | 36 | 约 1.2～2 小时 |
| B：帖子优先档（A 通过后） | 5 | 8 | 每帖 3 条 | 40 | 约 1.3～2.4 小时 |

理论上限不是“保证净新增”。搜索候选不足、时间窗口、旧帖跳过、详情失败、内容过滤、跨关键词重复和
数据库持久化失败，都会让实际新增低于 3/5。

> ⚠️ **先完成 A 档并做强验收，再决定是否跑 B 档。不要把两批任务同时播进队列。**

---

## 二、小红书的真实节奏和不能动的安全参数

| 配置 | 当前/要求值 | 含义 |
|---|---:|---|
| `CRAWLER_MAX_NOTES_COUNT` | 40 | 全局上限；本轮不用改 |
| `XHS_MAX_DETAIL_FETCH_PER_RUN` | 当前 1；A 档改 3，B 档改 5 | 每个关键词详情调度上限 |
| `XHS_CONSERVATIVE_DETAIL_MODE` | `True` | 保守模式，必须保留 |
| `XHS_SKIP_EXISTING_NOTE_DETAILS` | `True` | 跳过已入库详情 |
| `XHS_DETAIL_PRE_SLEEP_*` | 60～120 秒 | 每条详情前等待 |
| `XHS_DETAIL_POST_SLEEP_*` | 120～180 秒 | 每条详情成功后等待 |
| `XHS_SEARCH_TO_DETAIL_SLEEP_*` | 30～60 秒 | 搜索到详情之间等待 |
| `XHS_MAX_CONSECUTIVE_DETAIL_FAILURES` | 1 | 一次连续详情失败就停当前关键词 |
| `MAX_CONCURRENCY_NUM` | 1 | 单机并发保持 1 |
| `CRAWL_QUEUE_LEASE_SEC` | **7200 秒（120 分钟）** | 单任务租约，不是整批时长 |
| `ENABLE_GET_SUB_COMMENTS` | `False` | 不抓子评论 |

~~~text
3 篇详情 / 关键词 ≈ 12～20 分钟
5 篇详情 / 关键词 ≈ 20～35 分钟
~~~

不要缩短 sleep，不要关闭保守模式，也不要提高单机并发。租约没有 heartbeat，因此
`CRAWL_QUEUE_LEASE_SEC` 不能降回 1800 秒。

---

## 三、关键词必须是校园舆情，不是泛校园流量词

### 3.1 三条硬规则

1. **问题或服务对象要具体**：用“食堂卫生”“教务系统”，不要只用“食堂”“教务”。
2. **不要手工加“中山大学”**：系统会自动组合“中山大学 + 关键词”。
3. **不用招生、旅游、打卡、校友宣传等流量词**：只补后勤、教学服务、学生权益和校园治理。

### 3.2 A 档：12 个词，每词最多 3 篇

| 类别 | 关键词 |
|---|---|
| 宿舍与基础设施 | 宿舍热水、宿舍维修、宿舍噪音、校园网 |
| 食堂与消费 | 食堂卫生、食堂涨价 |
| 教学服务 | 教务系统、成绩申诉、考试安排 |
| 校园治理 | 停水停电、校内施工、电动车管理 |

~~~text
宿舍热水,宿舍维修,宿舍噪音,校园网,食堂卫生,食堂涨价,教务系统,成绩申诉,考试安排,停水停电,校内施工,电动车管理
~~~

### 3.3 B 档：8 个词，每词最多 5 篇

| 类别 | 关键词 |
|---|---|
| 教学/生活设施 | 教室空调、宿舍门禁、校医院服务 |
| 安全与物流 | 校园安保、快递丢件、校车拥挤 |
| 学生权益 | 转专业政策、奖学金评定 |

~~~text
教室空调,宿舍门禁,校医院服务,校园安保,快递丢件,校车拥挤,转专业政策,奖学金评定
~~~

备选词池：`心理咨询、体育场馆预约、外卖管理、学费住宿费、助学金评定、实习就业、保研政策、毕业手续`。
不要临时追加到正在运行的队列。

---

## 四、开跑前检查（两台机都做）

### 4.1 先看工作区，不要盲目 `git pull`

`base_config.py` 实际受 Git 跟踪，而且当前有本地安全参数修改：

~~~powershell
$ProjectRoot = "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
Set-Location $ProjectRoot
git status --short
git branch --show-current
git rev-parse HEAD
git diff -- MediaCrawler/config/base_config.py
~~~

只有确认不会覆盖本地修改、两机已协调好分支时，才执行：

~~~powershell
git pull --ff-only
~~~

不要使用 `git reset --hard` 或 `git checkout -- base_config.py`。如果 HEAD 不同，至少确认
`MediaCrawler` 运行代码一致。

### 4.2 验证共享数据库和空队列

~~~powershell
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs
~~~

开始前必须满足 `pending=0`、`claimed=0`。两台机器必须连同一个共享数据库，不能误连本地 MySQL。

### 4.3 登录和账号

- A、B 使用不同小红书账号；
- 不复制 Cookie 或 `browser_data`；
- 同一公网 IP 下，B 比 A 晚 60～90 秒启动；
- 登录掉线、反复扫码或出现验证码时，不继续抢新任务。

---

## 五、两机同步修改每词详情上限

两台机器都编辑 `MediaCrawler/config/base_config.py`，A 档确认：

~~~python
XHS_CONSERVATIVE_DETAIL_MODE = True
XHS_MAX_DETAIL_FETCH_PER_RUN = 3
XHS_SKIP_EXISTING_NOTE_DETAILS = True
XHS_MAX_CONSECUTIVE_DETAIL_FAILURES = 1

MAX_CONCURRENCY_NUM = 1
XHS_DOWNLOAD_NOTE_IMAGES = False
XHS_EXPORT_ENHANCED_JSON = False
ENABLE_GET_SUB_COMMENTS = False

ALLOW_BROAD_KEYWORDS = False
CRAWL_QUEUE_LEASE_SEC = 7200
~~~

不要改 `CRAWLER_MAX_NOTES_COUNT=40`。程序启动后才读取配置；运行中修改不会影响已启动进程。

两台分别校验：

~~~powershell
Select-String .\MediaCrawler\config\base_config.py -Pattern "XHS_MAX_DETAIL_FETCH_PER_RUN|XHS_CONSERVATIVE_DETAIL_MODE|XHS_SKIP_EXISTING_NOTE_DETAILS|XHS_MAX_CONSECUTIVE_DETAIL_FAILURES|MAX_CONCURRENCY_NUM|CRAWL_QUEUE_LEASE_SEC|XHS_DOWNLOAD_NOTE_IMAGES|XHS_EXPORT_ENHANCED_JSON"
(Get-FileHash -Algorithm SHA256 .\MediaCrawler\config\base_config.py).Hash
~~~

LF/CRLF 会导致 SHA 不同。哈希不同时先比较参数值，不要只凭哈希判失败。

---

## 六、机器 A 记录新批次基线

在数据库客户端执行只读 SQL：

~~~sql
SELECT COALESCE(MAX(id),0) AS queue_id0 FROM crawl_task_queue;
SELECT COALESCE(MAX(id),0) AS run_history_id0 FROM crawler_run_history WHERE platform='xhs';
SELECT COALESCE(MAX(id),0) AS xhs_history_id0 FROM xhs_crawl_history;
SELECT COALESCE(MAX(id),0) AS note_id0,COUNT(*) AS note_count0 FROM xhs_note;
SELECT COALESCE(MAX(id),0) AS comment_id0,COUNT(*) AS comment_count0 FROM xhs_note_comment;
SELECT COALESCE(MAX(id),0) AS raw_id0 FROM raw_posts WHERE platform='xhs';
SELECT COALESCE(MAX(id),0) AS processed_id0 FROM processed_posts WHERE platform='xhs';
SELECT COALESCE(MAX(id),0) AS event_id0 FROM public_events;
SELECT COALESCE(MAX(id),0) AS agent_run_id0 FROM agent_run_logs;
~~~

记录：

~~~text
queue_id0 / run_history_id0 / xhs_history_id0
note_id0 / note_count0 / comment_id0 / comment_count0
raw_id0 / processed_id0 / event_id0 / agent_run_id0
~~~

没有完整基线就不要播种。状态脚本汇总全部历史任务，不能代替本批 ID 区间。

---

## 七、A 档播种（只有机器 A 做一次）

### 7.1 dry-run

~~~powershell
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "宿舍热水,宿舍维修,宿舍噪音,校园网,食堂卫生,食堂涨价,教务系统,成绩申诉,考试安排,停水停电,校内施工,电动车管理" --priority 100 --dry-run
~~~

预期“待插入 12 条”。不是 12 条时，先检查活动的同名任务。

### 7.2 正式播种

~~~powershell
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "宿舍热水,宿舍维修,宿舍噪音,校园网,食堂卫生,食堂涨价,教务系统,成绩申诉,考试安排,停水停电,校内施工,电动车管理" --priority 100
~~~

机器 B 绝不播种。队列表没有活动关键词唯一约束，两个人同时播种可能产生重复任务。

~~~sql
SELECT id,keyword,status,priority,claimed_by
FROM crawl_task_queue
WHERE platform='xhs' AND id><queue_id0>
ORDER BY id;
~~~

必须恰好得到 12 条 `pending`。记下 `Q_FIRST` 和 `Q_LAST`，再启动 worker。

---

## 八、两机并行爬取并保存完整日志

上一轮“选课”持久化失败的异常原文没有保存，因此这次必须用 `Tee-Object` 留日志。

### 8.1 机器 A

~~~powershell
$ProjectRoot = "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$StartDate = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
$EndDate = (Get-Date).ToString("yyyy-MM-dd")
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
Set-Location "$ProjectRoot\MediaCrawler"
$env:PYTHONUNBUFFERED = "1"
.\.venv\Scripts\python.exe -u .\main.py --platform xhs --lt qrcode --type search --from-queue yes --worker cjt --save_data_option db --get_comment yes --get_sub_comment no --max_comments_count_singlenotes 5 --max_concurrency_num 1 --enable_ip_proxy no --fresh yes --start_date $StartDate --end_date $EndDate --headless no 2>&1 | Tee-Object -FilePath (Join-Path $LogDir "xhs-expand-cjt-$Stamp.log")
~~~

### 8.2 机器 B

~~~powershell
$ProjectRoot = "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
$StartDate = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
$EndDate = (Get-Date).ToString("yyyy-MM-dd")
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
Set-Location "$ProjectRoot\MediaCrawler"
$env:PYTHONUNBUFFERED = "1"
.\.venv\Scripts\python.exe -u .\main.py --platform xhs --lt qrcode --type search --from-queue yes --worker pissy --save_data_option db --get_comment yes --get_sub_comment no --max_comments_count_singlenotes 5 --max_concurrency_num 1 --enable_ip_proxy no --fresh yes --start_date $StartDate --end_date $EndDate --headless no 2>&1 | Tee-Object -FilePath (Join-Path $LogDir "xhs-expand-pissy-$Stamp.log")
~~~

### 8.3 启动协调

1. A 先启动并看到第一条 `claimed id=...`；
2. 60～90 秒后 B 启动；
3. 两边分别报告 worker、queue ID 和 keyword；
4. 两个首任务必须是不同 queue ID；
5. 运行期间不再播种、不改配置、不启动第三个 XHS worker。

队列原子领取只保证正常租约内同一 queue 行不被双领；不同关键词仍可能搜到同一帖子。

---

## 九、运行中监控和停机规则

### 9.1 监控命令必须从项目根目录执行

~~~powershell
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs
~~~

重点看：

- `Q_FIRST～Q_LAST` 是否从 pending → claimed → done；
- `claimed_by` 是否同时出现 `cjt` 和 `pissy`；
- 是否出现 `failed`、`exception` 或租约过期；
- 两台日志是否出现同一个 queue ID。

### 9.2 紧急停机条件

出现任一情况，立即停止触发机器：

- CAPTCHA、HTTP 461/471、“安全验证”“请求太频繁”；
- `risk_page`、`login_page`、`api_detail_captcha`、`html_fallback_risk_page`；
- `consecutive_detail_failures`；
- MySQL 1213、1205 或数据库断连；
- `Failed to store note detail`；
- 同一个 queue ID 被两机报告；
- 账号掉线或反复扫码。

如果两台机器共用公网 IP，任一账号触发明显风控时建议两台都暂停，不要马上重试。

### 9.3 活跃 worker 期间禁止全量重排 claimed

以下命令会重排该平台**所有** claimed，不只处理过期项：

~~~powershell
.\.venv\Scripts\python.exe scripts\reset_crawl_queue.py --platform xhs --requeue-claimed
~~~

因此：

1. 任一 worker 仍在运行时禁止执行；
2. 过期租约会在下一次 claim 时自动回收，优先等待；
3. 确需恢复时，先让两台都退出，再执行带 `--dry-run` 的预览；
4. 保存日志和本批 queue ID 后再决定是否恢复。

---

## 十、爬完后的强验收

`done` 或 `quota_reached` 不能单独证明入库成功。上一轮“选课”就是
`done + quota_reached + items_stored=0`，但 `store_failed_note_ids` 记录了真实失败。

### 10.1 队列终态

~~~sql
SELECT id,keyword,status,claimed_by,items_stored,stop_reason,
       FROM_UNIXTIME(claimed_at/1000.0) AS claimed_time,
       FROM_UNIXTIME(finished_at/1000.0) AS finished_time
FROM crawl_task_queue
WHERE id BETWEEN <Q_FIRST> AND <Q_LAST>
ORDER BY id;
~~~

通过标准：

- 12 条都不再是 pending/claimed；
- 两个 worker 都至少认领 1 条；
- 没有 `stop_reason='exception'`；
- `SUM(items_stored)` 只作参考，不等同于净新增行数。

### 10.2 通用运行历史

~~~sql
SELECT id,source_keyword,pages_fetched,items_seen,items_stored,stop_reason
FROM crawler_run_history
WHERE platform='xhs' AND id><run_history_id0>
ORDER BY id;
~~~

预期每个执行的关键词有一条。`source_keyword` 会写成“中山大学 + 裸关键词”。

### 10.3 XHS 专属历史：必须查持久化失败数组

~~~sql
SELECT id,run_id,source_keyword,
       planned_detail_count,success_detail_count,failed_detail_count,
       risk_control_triggered,stop_reason,
       JSON_LENGTH(JSON_EXTRACT(extra_json,'$.stored_note_ids')) AS stored_count,
       JSON_LENGTH(JSON_EXTRACT(extra_json,'$.store_failed_note_ids')) AS store_failed_count,
       JSON_EXTRACT(extra_json,'$.stored_note_ids') AS stored_note_ids,
       JSON_EXTRACT(extra_json,'$.store_failed_note_ids') AS store_failed_note_ids
FROM xhs_crawl_history
WHERE id><xhs_history_id0>
ORDER BY id;
~~~

强通过标准：

~~~text
risk_control_triggered = 0
failed_detail_count = 0
store_failed_count = 0
~~~

`planned_detail_count` 最多是 3，不保证等于 3；`stored_count` 也可能因过滤或重复而更小。

### 10.4 原生笔记、评论和唯一性

~~~sql
SELECT COUNT(*) AS current_note_count,COALESCE(MAX(id),0) AS current_note_id FROM xhs_note;
SELECT COUNT(*) AS current_comment_count,COALESCE(MAX(id),0) AS current_comment_id FROM xhs_note_comment;
SELECT note_id,COUNT(*) AS copies FROM xhs_note GROUP BY note_id HAVING COUNT(*)>1;
SELECT comment_id,COUNT(*) AS copies FROM xhs_note_comment GROUP BY comment_id HAVING COUNT(*)>1;
~~~

评论不计入 queue/history 的 `items_stored`。本轮每帖最多抓 5 条一级评论，远端评论总数不要求和本地相等。

### 10.5 A 档进入 B 档的门槛

必须同时满足：

- 12 条任务全部结束，无 pending/claimed；
- 风控、详情失败、store failure 全为 0；
- 两个 worker 都实际参与；
- `note_id` / `comment_id` 重复查询为空；
- 有真实新笔记入库；
- 两台完整日志已保留；
- 账号没有掉线或验证。

任一条件不满足，都先排障，不把上限升到 5。

---

## 十一、后处理：只由机器 A 执行一次

### 11.1 同步到产品表

~~~powershell
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 0
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform xhs --limit 0
~~~

`--limit 0` 表示不加 LIMIT。默认 100 不会永久删除剩余数据，但只处理前 100 条，容易造成“本轮已经
全部处理”的错觉。

~~~sql
SELECT n.id AS xhs_id,n.note_id,n.source_keyword,n.title,
       r.id AS raw_post_id,r.status AS raw_status,
       p.id AS processed_post_id,p.excluded,p.excluded_reason
FROM xhs_note n
LEFT JOIN raw_posts r ON r.platform='xhs' AND r.external_id=n.note_id
LEFT JOIN processed_posts p ON p.raw_post_id=r.id
WHERE n.id><note_id0>
ORDER BY n.id;
~~~

本轮新笔记必须都有 `raw_post_id`、`processed_post_id`。`excluded=0` 才进入后续事件分析。

### 11.2 先做数据质量检查

去 `/admin/raw-posts` 检查新帖，剔除：

- 台湾同名学校内容；
- 招生营销、旅游打卡、租卡广告；
- 与校园治理或学生体验无关的帖子；
- 明显重复、失真或无法核验的内容。

不要直接删除数据库记录。

### 11.3 事件生成不是 XHS 专属增量任务

`generate_public_events.py` 没有 `--platform`。裸跑会分析所有平台全部未剔除 processed 数据；
正式成功后，还可能把本轮没有再次生成的旧 draft 自动归档。

隔离预览应使用真实出现在标题/正文中的主题词，并禁止 0 结果回退：

~~~powershell
.\.venv\Scripts\python.exe scripts\generate_public_events.py --keyword "宿舍" --no-fallback --preview
~~~

这不代表覆盖全部新帖；`--keyword` 不匹配 `source_keyword`。

只有明确接受“全平台全量重算 + 旧 draft 状态协调”时，才执行：

~~~powershell
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview
.\.venv\Scripts\python.exe scripts\generate_public_events.py
~~~

`--preview` 不写 `public_events`，但仍可能调用外部模型并更新本地
`data/public_opinion_memory.json`，不是完全离线命令。

---

## 十二、A 档通过后：可选 B 档（每词最多 5 篇）

确认 pending=0、claimed=0，两台进程都已退出后，把两机配置改成：

~~~python
XHS_MAX_DETAIL_FETCH_PER_RUN = 5
~~~

重新执行第 5 节语义校验。机器 A 再播种：

~~~powershell
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "教室空调,宿舍门禁,校医院服务,校园安保,快递丢件,校车拥挤,转专业政策,奖学金评定" --priority 100 --dry-run
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "教室空调,宿舍门禁,校医院服务,校园安保,快递丢件,校车拥挤,转专业政策,奖学金评定" --priority 100
~~~

确认恰好新增 8 条。按第 8 节启动两台 worker，但把评论上限由 5 改成 3：

~~~text
--max_comments_count_singlenotes 3
~~~

其余参数不变。结束后重复第 10～11 节验收。

---

## 十三、已知坑

| 坑 | 表现 | 正确处理 |
|---|---|---|
| 原文写每词 5，实际配置是 1 | 每词最多只入 1 篇 | 两机启动前同步修改详情上限 |
| 把 3/5 当保证新增数 | 实际新增更少 | 它只是调度上限；查 `stored_note_ids` |
| 只看 queue 的 `done` | store failure 被掩盖 | 联查两张 history 和 `store_failed_note_ids` |
| 两台同时播种 | 可能重复 queue 行 | 只由 A 播种一次 |
| 活跃时 `--requeue-claimed` | 正在跑的任务回到 pending | 两台都停后才考虑 |
| 认为租约是 30 分钟 | 正常慢任务被误判卡死 | 当前是 7200 秒 / 120 分钟 |
| 不保存日志 | 无法还原异常 | 使用 `-u` + `Tee-Object` |
| 不带 `--fresh yes` | 捞回历史爆款 | 必须 fresh + 动态 30 天窗口 |
| 裸跑事件生成 | 全平台重算，可能归档旧 draft | 先质检和 preview；隔离测试加 `--no-fallback` |
| 从 `MediaCrawler` 跑根脚本 | 路径或 venv 错误 | monitor/sync/process/generate 前回项目根 |
| SHA 不同就判配置不同 | LF/CRLF 假差异 | 先比较参数语义 |

---

## 十四、一页速查（A 档）

~~~powershell
# ===== 两台机器：检查 =====
$ProjectRoot = "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
Set-Location $ProjectRoot
git status --short
git rev-parse HEAD
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs

# 两台手工确认：
# XHS_MAX_DETAIL_FETCH_PER_RUN = 3
# XHS_CONSERVATIVE_DETAIL_MODE = True
# MAX_CONCURRENCY_NUM = 1
# CRAWL_QUEUE_LEASE_SEC = 7200

# ===== 机器 A：记录 SQL 基线后，只播种一次 =====
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "宿舍热水,宿舍维修,宿舍噪音,校园网,食堂卫生,食堂涨价,教务系统,成绩申诉,考试安排,停水停电,校内施工,电动车管理" --priority 100 --dry-run
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --keywords "宿舍热水,宿舍维修,宿舍噪音,校园网,食堂卫生,食堂涨价,教务系统,成绩申诉,考试安排,停水停电,校内施工,电动车管理" --priority 100

# ===== 两台机器：进入 MediaCrawler；B 晚 60～90 秒 =====
$StartDate = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
$EndDate = (Get-Date).ToString("yyyy-MM-dd")
Set-Location "$ProjectRoot\MediaCrawler"

# A：
.\.venv\Scripts\python.exe -u .\main.py --platform xhs --lt qrcode --type search --from-queue yes --worker cjt --save_data_option db --get_comment yes --get_sub_comment no --max_comments_count_singlenotes 5 --max_concurrency_num 1 --enable_ip_proxy no --fresh yes --start_date $StartDate --end_date $EndDate --headless no

# B：同一命令，只把 worker 改成 pissy。

# ===== 另开终端监控：回到项目根 =====
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs

# ===== 两台结束、强验收通过后，只由 A 后处理 =====
Set-Location $ProjectRoot
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 0
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform xhs --limit 0

# 先去 /admin/raw-posts 质检。
# 事件全量重算不是自动必做，确认影响后再运行：
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview
.\.venv\Scripts\python.exe scripts\generate_public_events.py
~~~

最后去：

- `/admin/raw-posts`：检查并剔除无关新帖；
- `/sentiment`：确认近期帖子数量和趋势上升；
- `/admin/events`：审核新 draft，同时留意旧 draft 是否因全量重算被归档。
