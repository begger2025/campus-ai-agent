# 四平台爬取操作手册（小红书 / 微博 / 知乎 / 快手）

> 面向答辩与日常采集的手把手操作手册。命令以 **PowerShell**（用户默认终端）为准。
> 全流程 = **① 爬取（MediaCrawler）→ ② 同步（sync）→ ③ 加工（process）→ ④ 面板查看**。
> 各平台每一步命令几乎一致，差别只在 `--platform` 的取值和各自的登录/代理注意点。

---

## 0. 一分钟速查

| 平台 | 爬取 `--platform`（CLI） | 同步/加工 `--platform` |
|------|:---:|:---:|
| 小红书 | `xhs` | `xhs` |
| 微博 | **`wb`** | **`weibo`** |
| 知乎 | `zhihu` | `zhihu` |
| 快手 | `ks` | `ks` |

> ⚠️ **最容易踩的坑**：微博在爬虫命令行里是 `wb`，但在同步/加工脚本里是 `weibo`。其余两个平台前后一致。

三条核心命令（把 `<PLAT>` 换成上表对应值）：

```powershell
# ① 爬取——在 MediaCrawler 目录、用 MediaCrawler 自己的 .venv
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform <CLI码> --keywords "中山大学 宿舍" --get_comment yes --fresh yes --start_date 2026-06-27 --end_date 2026-07-11

# ② 同步——在主项目根、用根 .venv
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform <同步码>

# ③ 加工——同样在主项目根
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform <同步码>
```

---

## 1. 环境与前置准备（每次开跑前必看）

### 1.1 两个虚拟环境，别用错

| 用途 | 目录 | Python |
|------|------|--------|
| 爬取（MediaCrawler，含 playwright/浏览器） | `MediaCrawler\` | `MediaCrawler\.venv\Scripts\python.exe` |
| 同步 / 加工 / 后端 | 主项目根 | `.\.venv\Scripts\python.exe` |

### 1.2 关代理（**微博必做，其余强烈建议**）

本机 Clash（`127.0.0.1:7897`）会破坏采集：`www.weibo.com` 走代理直接断连（SSL EOF），
`127.0.0.1` 的本机请求（CDP 调试口、后端）经代理会 502/超时。开跑前在**当前 PowerShell 窗口**执行：

```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:http_proxy,Env:https_proxy -ErrorAction SilentlyContinue
$env:NO_PROXY = "127.0.0.1,localhost"
$env:PYTHONIOENCODING = "utf-8"
```

并且**关掉 Clash 的「系统代理」开关**（微博尤其敏感——`www.weibo.com` 只有直连才 200）。
知乎/小红书对代理没那么敏感，但一并关掉最省心。

> 说明：上面三行只对**当前这个终端窗口**生效，新开窗口要重来。

### 1.3 采集配置现状（`MediaCrawler\config\base_config.py`，已按答辩调好）

| 配置 | 值 | 含义 |
|------|----|----|
| `SAVE_DATA_OPTION` | `"db"` | 直接写共享 MySQL 原生表（带去重） |
| `CDP_CONNECT_EXISTING` | `False` | **自动新开一个 Chrome 供扫码**（冒烟调试用，见 §4） |
| `CRAWLER_MAX_NOTES_COUNT` | `40` | 每个关键词「新增入库」条数封顶（微博/贴吧/知乎语义）；小红书为详情调度配额 |
| `CRAWL_MAX_PAGES_PER_KEYWORD` | `10` | 单关键词翻页保护上限，防贫瘠词无限翻页 |
| `WEIBO/TIEBA/ZHIHU_SKIP_EXISTING_NOTES` | `True` | 爬取阶段跳过已入库帖子，省额度 |
| `CRAWL_TOPIC_QUALIFIER` | `"中山大学"` | 查询侧自动拼主题词 + 结果侧词表过滤 |

> `CDP_CONNECT_EXISTING=False` 与 `CRAWLER_MAX_NOTES_COUNT=40` 是**本地未提交的冒烟调参**，
> 不在任何 git 提交里。正式跑/交付前按需保留或还原。

---

## 2. 参数含义（三平台通用）

| 参数 | 取值 | 作用 |
|------|------|------|
| `--platform` | `xhs` / `wb` / `zhihu` | 平台（注意微博是 `wb`） |
| `--keywords` | `"中山大学 宿舍"` | 关键词，多个用英文逗号分隔。裸关键词会被查询侧自动拼「中山大学」 |
| `--get_comment` | `yes` | 采集一级评论（面板评论加载依赖它） |
| `--fresh` | `yes` | **新鲜优先预设**：小红书切时间倒序、微博切实时、知乎切按创建时间排序；使时间窗口整页早停可用 |
| `--start_date` / `--end_date` | `YYYY-MM-DD` | 只保留该时间窗内的帖子（客户端过滤 + 时间倒序提前停止） |
| `--type` | 默认 `search` | 爬虫类型，日常用默认搜索模式即可 |

> **时间窗口建议**：面板 C/D 信号（热点/新话题）只认「近 14 天」内容。答辩前跑一轮新数据时，
> `--start_date` 取「今天 − 14 天」。以 2026-07-11 为例即 `--start_date 2026-06-27 --end_date 2026-07-11`。
> 不加 `--fresh yes` 时默认排序捞到的多是历史爆款老帖，面板热点信号点不亮。

---

## 3. 各平台爬取命令

> 均在 `MediaCrawler\` 目录、用 `MediaCrawler\.venv`。跑前先做 §1.2 关代理。

### 3.1 小红书（xhs）

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform xhs --keywords "中山大学 宿舍" --get_comment yes --fresh yes --start_date 2026-06-27 --end_date 2026-07-11
```

- 小红书详情采集**刻意做成低频串行**（防风控）：每条详情前后随机 sleep 60~180 秒，
  单轮详情上限 `XHS_MAX_DETAIL_FETCH_PER_RUN=5`。所以小红书跑得慢、单轮条数少属正常。
- 用时间窗口时务必带 `--fresh yes`（切 `time_descending`）才能整页提前停止。

### 3.2 微博（wb）— 对代理最敏感

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform wb --keywords "中山大学 宿舍" --get_comment yes --fresh yes --start_date 2026-06-27 --end_date 2026-07-11
```

- **务必**先做 §1.2：清 `HTTP(S)_PROXY` 环境变量 + 关 Clash 系统代理。
  实测漏关会出现：CDP 调试口 502 / 扫码二维码瞬间闪退（httpx 走代理连 `m.weibo.cn` 失败）/
  `www.weibo.com` `ERR_CONNECTION_CLOSED`。
- 提前停止仅在实时（`real_time`）模式下生效，`--fresh yes` 已帮你切好。
- 主题过滤会正常滤掉「蹭校名的地产 B 端广告 / 无关帖」，日志里出现「skip N 条 off-topic」是预期。

### 3.3 知乎（zhihu）

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform zhihu --keywords "中山大学 宿舍" --get_comment yes --fresh yes --start_date 2026-06-27 --end_date 2026-07-11
```

- 知乎有**服务端增强**：`--fresh yes` → 服务端「最新」排序；时间窗口 → 服务端粗时间档
  + 客户端秒级精筛，比其他平台更省流量、更准。
- 知乎无收藏/转发计数，同步时这两项恒为 0，属预期（面板 D「标签」信号也不参与知乎）。

### 3.4 快手（ks）

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform ks --keywords "中山大学 宿舍" --get_comment yes --start_date 2026-06-27 --end_date 2026-07-11
```

- 快手搜索 API **无服务端排序、无时间筛选**：`--fresh` 对快手是无操作（带上无害，可不带）；
  时间窗口纯客户端过滤且**无法提前停止**（结果非时间序），靠 10 页翻页上限兜底。
- 帖子正文 = 视频文案（caption），搜索结果自带全文，无二段详情抓取，跑得比小红书快。
- 快手无收藏/转发计数，同步时这两项恒为 0；标签未持久化（D「新话题」信号不参与），属预期。
- 同步/加工也用 `ks`（与 CLI 一致，没有微博那种 wb/weibo 前后不一致的坑）。

---

## 4. 登录（CDP 扫码）

当前 `CDP_CONNECT_EXISTING=False`：运行爬取命令后，程序会**自动弹出一个真实 Chrome 窗口**
（CDP 调试端口 `9222`，被占用则自动顺延），加载对应平台的登录页并显示二维码。
用手机 App 扫码即可，登录态会缓存到 `MediaCrawler\browser_data\cdp_<平台>_user_data_dir`，
下次通常免扫。

各平台登录态判定：
- **微博**：扫 `m.weibo.cn` 二维码。
- **知乎**：扫知乎二维码。
- **小红书**：扫小红书二维码。

排障：
- **二维码没来得及扫就闪退** → 基本都是代理没清干净（httpx 走代理取二维码失败）。回到 §1.2 重清一遍再跑。
- **弹的是标准 playwright 模式而非真实 Chrome** → CDP 启动失败回退了；确认 Chrome 已安装、
  `9222` 端口没被占，且代理已按 §1.2 处理（本机 `127.0.0.1:9222` 别被代理拦）。
- 若想改用「手动开好的 Chrome 远程调试口」连接，把 `CDP_CONNECT_EXISTING` 设 `True`（进阶用法，日常不需要）。

---

## 5. 同步 → 加工（入库到产品表）

爬取只写 MediaCrawler 的**原生表**（`xhs_note` / `weibo_note` / `zhihu_content` 等）。
要让数据出现在产品面板，还需两步——均在**主项目根**、用**根 `.venv`**，用**同步码**（微博是 `weibo`）。

### 5.1 同步：原生表 → `raw_posts`

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform xhs
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform weibo
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform zhihu
```

- `--platform` 可重复传多次，或用 `--platform all` 一次同步全部。
- `--refresh`：命中已存在的行时**刷新互动量**（点赞/评论数等，默认跳过不更新）。想演示「老帖热度增长」才需要。
- `--limit N`（默认 100）、`--dry-run`（只看不写）。

### 5.2 加工：`raw_posts` → `processed_posts`（算情绪/风险/热度/标签）

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform xhs
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform weibo
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform zhihu
```

- `--platform` 同样可重复传（choices：`xhs` / `weibo` / `tieba` / `zhihu`），不传则处理全部。
- `--refresh`：对已存在的 `processed_posts` 行重算互动量与热度（默认不刷新）。
- 精确情绪/标签提取依赖 LLM key；无 key 时走规则兜底（只提取已知粗粒度词），答辩前建议配好 key。

> 想同时刷新老帖热度：`sync ... --refresh` 与 `process ... --refresh` **要成对使用**，
> 且需临时把 `*_SKIP_EXISTING_NOTES` 设 `False` 重爬，否则老帖被跳过、热度冻结在首次同步值。

---

## 6. 验证是否入库成功

### 6.1 面板查看（最直观）
1. 重启后端（`stop.bat` → `run.bat`），确保加载最新路由。
2. 打开 **数据管理 → 原始帖子（AdminRawPosts）**，按平台筛选，能看到新帖即成功。
3. **智能选题** 面板的「热点/新话题」信号需有近 14 天数据才会点亮。

### 6.2 命令行核对（可选）
用 `scripts\view_db.py` 或直接查对应原生表行数 / `crawler_run_history` 本轮记录
（每关键词一行：关键词、翻页数、seen 数、入库数、stop_reason）。
`入库数 > 0` 且原生表新增即成功。

---

## 7. 常见问题速查

| 现象 | 原因 | 解法 |
|------|------|------|
| 二维码弹出即闪退 | httpx 走代理取二维码失败 | §1.2 清代理环境变量 + 关 Clash 系统代理 |
| CDP 502 / 连不上 9222 | 代理拦截了 `127.0.0.1` | `$env:NO_PROXY="127.0.0.1,localhost"` |
| 微博 `ERR_CONNECTION_CLOSED` | Clash 破坏 `www.weibo.com` | 关 Clash 系统代理（直连才 200） |
| 面板热点/新话题信号全 0 | 库里内容超出 14 天窗口 | 带 `--fresh yes --start_date 今天-14天` 跑一轮新数据 |
| 爬到了但面板看不到 | 只写了原生表，没同步/加工 | 补跑 §5 的 sync + process（注意用 `weibo` 而非 `wb`） |
| 智能选题 404 | 后端进程是旧的、没有新路由 | 重启后端（`stop.bat` → `run.bat`） |
| 微博采集到无关广告帖 | 蹭校名的 B 端营销 | 已由营销负面词表拦截大部分；纯「提及校名的无关帖」为已知技术权衡 |

---

## 8. 一句话完整示例（微博，从零到面板）

```powershell
# 0) 关代理（当前窗口）
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:http_proxy,Env:https_proxy -ErrorAction SilentlyContinue
$env:NO_PROXY = "127.0.0.1,localhost"; $env:PYTHONIOENCODING = "utf-8"
# （并关掉 Clash 系统代理开关）

# 1) 爬取（CLI 码 wb）——弹 Chrome 扫码
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform wb --keywords "中山大学 宿舍" --get_comment yes --fresh yes --start_date 2026-06-27 --end_date 2026-07-11

# 2) 同步 + 加工（同步码 weibo）
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform weibo
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --platform weibo

# 3) 重启后端，去「数据管理 → 原始帖子」按微博筛选核对
```

---

> 贴吧（tieba）暂不在本手册：其上游详情页解析器与百度当前 HTML 结构失配，采集能登录/搜索但入库为 0，
> 已知待适配，答辩以三平台为准。
