# 小红书两机并行爬取 · 操作手册

> **本次目标**：给语料补一批**近期**的小红书内容。
>
> **开跑前的真实基线**（2026-07-14 实测）：
>
> ```
> processed_posts（未剔除）:  395 条，其中近 30 天  19 条  =  4.8%
> xhs_note（原生表）:         154 行 / 154 个不同 note_id（零重复）
> crawl_task_queue（xhs）:    pending=0 claimed=0 done=6 failed=0（干净，可直接播种）
> ```
>
> **这次的 KPI 就是把那个 4.8% 顶上去。** 事件列表现在会把「340 天前」标红——语料有多旧，
> 评委一眼就能看见。**这件事比任何算法改动都值钱。**
>
> **角色**：你 = 播种 + 爬取（机器 A）；组员 = 爬取（机器 B）。
> 两台机从**共享队列**认领关键词，互不重叠，同时写共享 MySQL。

---

## 一、先读这一段：小红书跟快手完全不是一个节奏

上次两机冒烟跑的是**快手**，38 个视频很快就下来了。**小红书会慢一个数量级**，因为它开着
「保守详情模式」（`XHS_CONSERVATIVE_DETAIL_MODE = True`）——这是为了不撞风控，不是配错了。

代码里的硬事实（`MediaCrawler/config/base_config.py` + `media_platform/xhs/core.py`）：

| 配置 | 值 | 含义 |
|---|---|---|
| `XHS_MAX_DETAIL_FETCH_PER_RUN` | **5** | **每个关键词最多抓 5 条详情**（实际配额 = `min(CRAWLER_MAX_NOTES_COUNT=40, 5)` = **5**） |
| `XHS_DETAIL_PRE_SLEEP` | 60–120 秒 | 每条详情**之前**随机睡 |
| `XHS_DETAIL_POST_SLEEP` | 120–180 秒 | 每条详情成功**之后**随机睡 |
| `XHS_SEARCH_TO_DETAIL_SLEEP` | 30–60 秒 | 搜索完到开抓详情之间睡 |
| `XHS_MAX_CONSECUTIVE_DETAIL_FAILURES` | **1** | **一条详情失败就停掉这个关键词**（fail-fast） |
| 详情并发 | **1**（串行） | 保守模式下信号量恒为 1 |
| `XHS_SKIP_EXISTING_NOTE_DETAILS` | `True` | 已入库的帖子不重复抓详情——所以「新增」是**真新增** |

### 由此推出的时间预算（务必按这个规划）

```
单条详情 ≈ 前睡 60~120s + 抓取 + 后睡 120~180s ≈ 3~5 分钟
单个关键词 ≈ 搜索 + 30~60s + 5 条详情 ≈ 16~27 分钟   ← 最多入库 5 条新帖
```

| 播种关键词数 | 每台机分到 | 每台耗时 | 理论新增上限 |
|---|---|---|---|
| 12 | 6 | **约 1.7–2.7 小时** | 60 条 |
| 16 | 8 | 约 2.2–3.6 小时 | 80 条 |
| 20 | 10 | 约 2.8–4.5 小时 | 100 条 |

**推荐播 12–16 个关键词**。实际入库会低于上限（很多帖子已经在库里了，会被 skip）。

> ⚠️ **不要为了快去调小 sleep 或关掉保守模式**。小红书的风控是这个项目踩过的最硬的墙——
> 一旦触发验证码，`XHS_MAX_CONSECUTIVE_DETAIL_FAILURES=1` 会立刻停掉该关键词，整轮白跑。
> 慢，是这里唯一能跑通的策略。

---

## 二、开跑前的检查（**两台机都要做**）

### 1. 代码同步到最新

```powershell
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
git pull            # 组员：确保拿到最新的 main/当前分支
git log --oneline -1
```

### 2. 确认能连共享数据库

网络一抖 RDS 就连不上（今天已经遇到过一次）。**先验证，别等爬完才发现写不进去**：

```powershell
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
```

### 3. `base_config.py` 的本地状态

这个文件**不进 git**（每个人的本地调参不同）。确认这几项：

```python
PLATFORM = "xhs"
LOGIN_TYPE = "qrcode"
SAVE_DATA_OPTION = "db"          # ← 必须是 db，直接写共享库的原生表
CDP_CONNECT_EXISTING = False     # ← False = 自动开一个新浏览器让你扫码
HEADLESS = False                 # ← 必须 False，不然扫不了码
XHS_CONSERVATIVE_DETAIL_MODE = True   # ← 别关
```

### 4. 两台机用**不同的小红书账号**扫码

同一个账号在两台机上并发搜索，是在给自己送风控。

---

## 三、播种（**只有机器 A 做，做一次**）

关键词进 `crawl_task_queue` 表，两台机从里面**原子认领**（乐观锁 `UPDATE ... WHERE status='pending'`，
受影响行数 = 1 才算抢到），所以**零重叠**，不需要人工分配。

### 先干跑看清单

```powershell
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main

.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py `
  --platform xhs `
  --keywords "宿舍搬迁,食堂,宿舍空调,选课,教务,图书馆,校车,快递,期末,开学,社团,校园卡" `
  --dry-run
```

确认无误后去掉 `--dry-run` 真正播种。

### 关键词怎么挑（三条硬规则）

1. **不要播裸的「中山大学」**——`ALLOW_BROAD_KEYWORDS = False` 会**直接拦掉**它。
   裸主题词对过滤零区分力，招生/旅游/营销内容会全数灌进来。
2. **不用自己加「中山大学」前缀**——`CRAWL_TOPIC_QUALIFIER = "中山大学"` 会在查询侧
   **自动组合**（你播「食堂」，它去搜「中山大学 食堂」）。
3. **要具体**。「宿舍搬迁」比「宿舍」好：越具体的话题，越是舆情该关心的，噪声也越少。

想让面板帮你选词，可以从智能选题推荐直接灌：

```powershell
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs --from-recommendations --top 12
```

> 去重规则：只跳过当前 `pending` / `claimed` 的 (platform, keyword)。`done` / `failed` 过的可以重新入队。

---

## 四、爬取（**两台机同时跑**）

```powershell
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler

# 机器 A（你）
.\.venv\Scripts\python.exe main.py `
  --platform xhs `
  --from-queue yes `
  --worker cjt `
  --get_comment yes `
  --fresh yes `
  --start_date 2026-06-14

# 机器 B（组员）—— 只有 --worker 不同
.\.venv\Scripts\python.exe main.py `
  --platform xhs `
  --from-queue yes `
  --worker pissy `
  --get_comment yes `
  --fresh yes `
  --start_date 2026-06-14
```

### 每个参数为什么在那里

| 参数 | 作用 |
|---|---|
| `--from-queue yes` | 队列模式：登录一次，然后**循环认领关键词**直到队列排空 |
| `--worker <id>` | 你是谁（用于租约和排障）。不给的话默认取主机名，但显式写更好排查 |
| `--get_comment yes` | 抓一级评论。评论区风向会进情绪分析和简报语料 |
| `--fresh yes` | **小红书必须带**：把 `SORT_TYPE` 切成 `time_descending`（时间倒序）。<br>不带的话默认按热度排，捞回来的是**历史爆款老帖**——那正是我们要摆脱的东西。<br>而且只有时间倒序，下面的时间窗口才能**提前停止**（翻到窗口外就不再翻）。 |
| `--start_date` | 只要这个日期之后的帖子。填**今天往前 30 天**。 |

### 跑起来之后

1. 浏览器会自动弹出 → **扫码登录**（两台机用不同账号）
2. 登录成功后它会自己开始循环认领关键词
3. **日志会长时间"没动静"**——那是在 `XHS_DETAIL_PRE_SLEEP`（60–120 秒）里睡觉，**不是卡死**。
   日志里会明写 `Sleeping ... before detail fetch`
4. 队列排空后自动退出（`queue drained, exit`）

---

## 五、监控（任一台机随时可跑）

```powershell
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs
```

输出：

```
=== 队列汇总（按平台）===
  xhs: pending=4 claimed=2 done=6 failed=0

=== 认领中（claimed）===
  #13 xhs / 食堂 by cjt
  #14 xhs / 选课 by pissy
```

- `claimed` 后面跟 `[卡死待回收]` = **租约（30 分钟）已过期**。一台机崩了/关了，任务会被
  下一个认领者接手，不会永久卡住。
- 全部 `done`（+ 少量 `failed`）= 两台机都跑完了。

### 出问题时

```powershell
# 先干跑看会改什么
.\.venv\Scripts\python.exe scripts\reset_crawl_queue.py --platform xhs --requeue-claimed --dry-run

# 把卡死的 claimed 任务放回 pending（一台机崩了/被强杀）
.\.venv\Scripts\python.exe scripts\reset_crawl_queue.py --platform xhs --requeue-claimed

# 把 failed 的任务放回 pending（风控停了的关键词，换个时段重试）
.\.venv\Scripts\python.exe scripts\reset_crawl_queue.py --platform xhs --requeue-failed
```

---

## 六、入库（爬完之后，**机器 A 做一次就够**）

原生表 → `raw_posts` → `processed_posts` → 事件。

```powershell
cd D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main

# ① 原生表 -> raw_posts。--limit 0 = 全量！
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 0

# ② raw_posts -> processed_posts（清洗、打分、情绪、热度归一化）
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform xhs --limit 0

# ③ 事件生成：**先 --preview 看一眼，别直接写库**
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview

# ④ 确认无误后真正生成（会写 public_events，新事件是 draft，等你审核）
.\.venv\Scripts\python.exe scripts\generate_public_events.py
```

> 🚨 **`--limit 0` 不能省**。`sync` 和 `process` 的 `--limit` **默认是 100**，
> 你要是爬回来 120 条，默认参数会**静默丢掉 20 条**——而且它不会报错。
> 这个项目已经被同一个形状的 bug 咬过一次（`generate_public_events --limit 200` 悄悄丢了最旧的 97 条）。

### 事件生成会重跑**全量**聚类

新帖进来后，embedding 聚类 + LLM 精修 + 风险研判 + 生命周期研判会**全量重跑**（约 1 分钟，8 路并发）。
已发布的事件保持 `published`（不用重新审核），新事件是 `draft`。

---

## 七、验收（爬完必做，不然不知道成没成）

### 1. 队列跑干净了

```powershell
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs
# 期望：pending=0 claimed=0，done 是大头
```

### 2. 两台机零重复

分布式的核心承诺就是这个。查原生表：

```sql
SELECT COUNT(*) AS 总行数, COUNT(DISTINCT note_id) AS 不同帖子数 FROM xhs_note;
-- 两个数必须相等（DB 层有唯一索引兜底，理论上不可能不等）
```

### 3. 新数据真的进来了

```sql
-- 近 30 天的帖子占比（这次爬取的 KPI）
SELECT
  COUNT(*) AS 总数,
  SUM(publish_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)) AS 近30天,
  ROUND(100 * SUM(publish_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)) / COUNT(*), 1) AS 占比
FROM processed_posts WHERE excluded = 0;
```

**爬之前是 ~4%。这个数字涨上去，这次爬取就成了。**

### 4. 页面上看

- **数据管理**（`/admin/raw-posts`）：新帖在最上面（按发布时间倒序）
- **舆情分析**（`/sentiment`）：「帖子总数」变大，发帖趋势图右端有新柱子
- **事件审核**（`/admin/events`）：新的 `draft` 事件 → **点开看内容**（详情抽屉里有代表帖和原帖链接）→ 通过 / 驳回

### 5. 顺手做数据质量管控

新爬的帖子里难免混进无关内容（同名的台湾国立中山大学、蹭校名的广告）。
在**数据管理页**点「剔除」（要填理由）——它就不再进入舆情分析、事件聚类和舆情助手的检索。
剔错了可以在「已剔除」页签恢复。**别再直接删库。**

---

## 八、已知的坑（都是真踩过的）

| 坑 | 表现 | 怎么办 |
|---|---|---|
| **风控验证码** | 日志 `CaptchaBlockError`，该关键词立刻停（fail-fast） | 正常现象。换个时间段再跑，或减少并发关键词。**不要调小 sleep** |
| **`failed` 任务记账少报** | 队列里 `items_stored=0`，但数据其实存进去了 | **已知缺陷，数据不丢**。以数据库里的实际行数为准，别信队列的计数 |
| **`--limit` 默认 100** | sync/process 静默丢数据 | **永远写 `--limit 0`** |
| **不带 `--fresh yes`** | 捞回一堆历史爆款老帖 | 小红书必须带，否则这次爬取的意义（补新鲜数据）就没了 |
| **两台机用同一个账号** | 风控概率飙升 | 用不同账号 |
| **Clash / 系统代理** | 后端脚本连 RDS 超时 | 跑 `verify_db_connection.py` 先验；必要时关掉 Clash |
| **日志长时间不动** | 以为卡死了，手贱 Ctrl+C | 那是在 sleep（60–180 秒）。看日志里的 `Sleeping ...` |

---

## 九、一页速查

```powershell
# ===== 机器 A（你）=====
# 0. 检查
git pull
.\.venv\Scripts\python.exe scripts\verify_db_connection.py

# 1. 播种（只做一次）
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs `
  --keywords "宿舍搬迁,食堂,宿舍空调,选课,教务,图书馆,校车,快递,期末,开学,社团,校园卡" --dry-run
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform xhs `
  --keywords "宿舍搬迁,食堂,宿舍空调,选课,教务,图书馆,校车,快递,期末,开学,社团,校园卡"

# 2. 爬（扫码后放着跑 2~3 小时）
cd MediaCrawler
.\.venv\Scripts\python.exe main.py --platform xhs --from-queue yes --worker cjt `
  --get_comment yes --fresh yes --start_date 2026-06-14

# 3. 监控（另开一个终端）
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform xhs

# 4. 入库（两台都跑完之后）
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs --limit 0
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform xhs --limit 0
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview
.\.venv\Scripts\python.exe scripts\generate_public_events.py

# 5. 去 /admin/events 审核新的 draft 事件


# ===== 机器 B（组员）=====
git pull
cd MediaCrawler
.\.venv\Scripts\python.exe main.py --platform xhs --from-queue yes --worker pissy `
  --get_comment yes --fresh yes --start_date 2026-06-14
# 扫码（用**你自己的**小红书账号），然后放着跑。跑完告诉机器 A。
```
