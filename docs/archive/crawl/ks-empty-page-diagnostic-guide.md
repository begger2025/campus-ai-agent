# 机器 B：KS 批量 `empty_page` 只读排查协同指导

> 用途：将本文档交给机器 B 负责人，再由负责人交给机器 B 上的 AI agent 执行。
>
> 本文档只授权**读取与报告**。它不是重跑手册，也不授权修改代码、配置、队列、数据库、账号或网络。

---

## 一、任务目标

机器 B 在校园舆情第 2 轮中两次运行 KS 队列，12 个关键词都在几十秒内被标记为 `done`，但没有新增数据。

本次排查只需要回答两个问题：

1. 机器 B 的账号、会话、IP 或网络是否导致快手搜索接口静默返回空结果？
2. 如果普通网页搜索正常，爬虫运行环境中还有哪些可验证的差异或原始证据？

完成检查后，只提交报告给机器 A。**不要自行修复或再次运行爬虫。**

---

## 二、已经确认的事实

### 2.1 两次任务都已经播种和认领

不存在“机器 A 没有播种”的情况：

- 第一次第 2 轮 KS 任务：队列 ID `#63`～`#74`；
- 第二次补跑任务：队列 ID `#75`～`#86`；
- 两批任务都由 `worker=pissy` 认领；
- 两批共 24 次关键词运行均进入 `done`，而不是 `failed`。

### 2.2 两次都属于空跑

24 次运行的共同特征：

```text
pages_fetched = 1
items_seen = 0
items_stored = 0
stop_reason = empty_page
```

- 第一批约 27.5 秒清空；
- 第二批约 19.1 秒清空；
- 第二批命令从启动浏览器到退出约 40 秒；
- 浏览器自动关闭是队列排空后的正常收尾，不是独立的浏览器崩溃。

`items_seen` 在重复过滤、主题过滤、营销过滤和时间过滤之前统计。因此 `items_seen=0` 已排除：

- 数据库里都是重复帖；
- 关键词被主题过滤；
- 帖子被营销过滤；
- `--start_date` 时间窗口过滤。

### 2.3 登录检测通过不等于搜索接口正常

机器 B 日志显示 `pong` 通过，但二者调用的接口不同：

- 登录检测：`visionProfileUserList`；
- 关键词搜索：`visionSearchPhoto`。

所以账号可能通过登录检测，但搜索接口仍被静默限制，或返回缺字段/异常结构。

### 2.4 第一轮 KS 曾经正常工作

同一项目第一轮 KS 运行历史中，多数关键词能够：

- 翻取 10 页；
- 看到约 196～200 条原始结果；
- 实际入库 10～38 条不等。

第 2 轮连续两次、24 次关键词全部首屏为零，不像真实的“所有关键词都无内容”。

### 2.5 机器 A、B 的 KS 关键文件哈希已经一致

| 文件 | 两机一致的 SHA256 |
|---|---|
| `media_platform\kuaishou\core.py` | `7A09B92A7AA6BBBB038993D525F9C89EB0DFC806294B8AEC8EBC45356E3C2A78` |
| `media_platform\kuaishou\client.py` | `44F1F8716451D36CF48A57965E4AF8F310C595F93CD03CEEE8B45F5D56CE58B5` |
| `media_platform\kuaishou\graphql\search_query.graphql` | `6F1FF2585C158F778C33445191747EACE5E1FC384801AAC533796A17DBE32199` |

因此已基本排除这三个关键文件的版本不一致。

### 2.6 为什么空跑仍会显示 `done`

KS 搜索代码把以下任一情况统一记为 `empty_page` 并正常返回：

1. `videos_res` 为空；
2. `visionSearchPhoto.result != 1`；
3. `visionSearchPhoto.feeds` 为空。

队列执行器只要没有接收到抛出的异常，就会把任务标成 `done`。因此此处的 `done` 只表示任务函数结束，**不表示成功采集到数据**。

补充判据：

- `empty_page` 也可能是“已有内容并完成入库后，服务端返回 `pcursor=no_more`”的正常终止原因，因此不能只看 `stop_reason`；本事故的异常性来自 `pages_fetched=1 + items_seen=0 + items_stored=0` 同时出现。
- 如果客户端抛出 `DataFetchError`，运行历史应记录为 `exception`。本事故为 `empty_page + exit 0`，说明客户端没有抛出该异常，而是返回了一个被现有逻辑归入“空或异常”的响应。
- 首次搜索时 `search_session_id=""`，`pcursor=str(keyword_start_page)`；如果起始页随机偏移命中，首个 `pcursor` 可能大于 `1`。若首屏已经为零，程序会在读取服务端真实 `pcursor/searchSessionId` 前退出。
- 当前日志记录请求关键词、页码和请求 `pcursor`，但不记录原始 `videos_res`、`result` 实值、响应字段名或响应体，因此仅凭现有日志不能最终区分静默风控与响应结构异常。
- 现有“疑似风控后刷新 Cookie”的恢复逻辑属于评论抓取路径，不覆盖关键词搜索首屏为空的情况。

---

## 三、机器 B AI agent 的角色与硬性纪律

你是机器 B 的**只读诊断助手**。必须先完整阅读本文档，再执行下列步骤。

### 允许做

- 读取本地文件、配置项和文件哈希；
- 查看当前进程，但不干预；
- 使用既有状态脚本只读查询共享队列；
- 请机器 B 负责人在普通浏览器完成一次人工搜索；
- 收集并脱敏报告现有终端日志。

### 严禁做

- 不运行 `seed_crawl_queue.py`；
- 不运行任何 `reset`、`requeue`、`delete`、`purge` 脚本；
- 不再次运行 `main.py`，无论队列模式还是直接关键词模式；
- 不运行入库链；
- 不手写 SQL；
- 不修改任何代码或配置，包括临时加日志；
- 不执行任何 Git 操作；
- 不删除或清理浏览器用户目录、Cookie、缓存；
- 不退出账号、不切换账号、不更换网络或代理；
- 不启动或终止任何进程；
- 不输出 `.env`、Cookie、请求头、token、代理地址、数据库地址或任何凭据值。

遇到任何报错：保存原始错误，立即停止该步骤并报告，不要自行修复。

---

## 四、环境信息

机器 B 项目路径：

```text
C:\Users\pissy\Desktop\新建文件夹\campus-ai-agent_v3(2)\campus-ai-agent_v3\campus-ai-agent-main
```

机器 B 本轮使用的命令：

```powershell
Set-Location "C:\Users\pissy\Desktop\新建文件夹\campus-ai-agent_v3(2)\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"

.\.venv\Scripts\python.exe -u main.py --platform ks --from-queue yes --worker pissy `
  --get_comment yes --fresh yes
```

该命令没有 `--start_date`，写法正确。`--fresh yes` 不会改变 KS 的排序参数，因此不是本次全空的直接原因。

---

## 五、严格按序执行的只读检查

### 步骤 1：确认路径

```powershell
Set-Location -LiteralPath "C:\Users\pissy\Desktop\新建文件夹\campus-ai-agent_v3(2)\campus-ai-agent_v3\campus-ai-agent-main"
Get-Location
```

预期路径末尾为：

```text
campus-ai-agent-main
```

若路径不存在或不是该副本，原样报告并停止。

### 步骤 2：确认没有仍在运行的 KS 爬虫

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match '^python' -and
    $_.CommandLine -match 'main\.py.*--platform\s+ks'
  } |
  Select-Object ProcessId, Name, CommandLine
```

判断：

- 无输出：符合“本轮已退出”；
- 有输出：记录完整的 `ProcessId/Name/CommandLine` 并报告，**不要使用 `Stop-Process`**。

### 步骤 3：只读查看共享队列终态

仍在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform ks
```

已知参考终态应接近：

```text
ks: pending=0 claimed=0 done=43 failed=1
```

说明：

- `done=43` 是累计值，包含第一轮成功任务和第 2 轮两批空跑任务；
- `failed=1` 是第 2 轮开始前已有的历史失败；
- 如果出现新的 `pending` 或 `claimed`，只报告，不要启动爬虫处理。

### 步骤 4：再次核验三个关键文件

```powershell
Set-Location -LiteralPath "C:\Users\pissy\Desktop\新建文件夹\campus-ai-agent_v3(2)\campus-ai-agent_v3\campus-ai-agent-main\MediaCrawler"

Get-FileHash -Algorithm SHA256 -LiteralPath `
  .\media_platform\kuaishou\core.py, `
  .\media_platform\kuaishou\client.py, `
  .\media_platform\kuaishou\graphql\search_query.graphql |
  Format-List Path,Hash
```

逐项与 §2.5 对照。任何不一致都只报告，不执行 `git pull`、复制或覆盖。

### 步骤 5：读取相关配置，不读取 `.env`

```powershell
Select-String -LiteralPath .\config\base_config.py -Pattern `
  '^(LOGIN_TYPE|ENABLE_IP_PROXY|HEADLESS|CDP_CONNECT_EXISTING|SAVE_DATA_OPTION|START_PAGE|CRAWLER_MAX_NOTES_COUNT|CRAWL_MAX_PAGES_PER_KEYWORD|KS_SKIP_EXISTING_NOTES|CRAWL_PUBLISH_TIME_START|CRAWL_PUBLISH_TIME_END|SEARCH_START_PAGE_JITTER_PROB|SEARCH_START_PAGE_JITTER_MAX)\s*='
```

机器 A 当前参考值：

```text
LOGIN_TYPE = "qrcode"
ENABLE_IP_PROXY = False
HEADLESS = False
CDP_CONNECT_EXISTING = False
SAVE_DATA_OPTION = "db"
START_PAGE = 1
CRAWLER_MAX_NOTES_COUNT = 40
CRAWL_MAX_PAGES_PER_KEYWORD = 10
KS_SKIP_EXISTING_NOTES = True
CRAWL_PUBLISH_TIME_START = ""
CRAWL_PUBLISH_TIME_END = ""
SEARCH_START_PAGE_JITTER_PROB = 0.2
SEARCH_START_PAGE_JITTER_MAX = 5
```

要求：

- 只记录这些键的值；
- 不打开或输出 `.env`；
- 不修改任何不一致项。

补充判断：起始页随机偏移概率仅为 20%，不能合理解释连续两批共 24 个关键词全部首屏为零。

### 步骤 6：记录 Python 与关键依赖版本

```powershell
.\.venv\Scripts\python.exe --version

.\.venv\Scripts\python.exe -c "import importlib.metadata as m; print('playwright='+m.version('playwright')); print('httpx='+m.version('httpx')); print('sqlalchemy='+m.version('sqlalchemy'))"
```

只记录版本号。若某个包无法读取版本，原样记录错误，不安装或升级依赖。

### 步骤 7：只查看 KS 浏览器用户目录元信息

```powershell
Get-ChildItem -LiteralPath . -Directory -Force |
  Where-Object { $_.Name -like '*ks*user_data_dir*' } |
  Select-Object FullName, LastWriteTime
```

只报告目录是否存在及最后修改时间。

严禁：

- 进入并输出 Cookie 数据库内容；
- 复制浏览器用户目录；
- 删除、重命名或清空目录。

### 步骤 8：人工浏览器验证（必须由机器 B 负责人执行）

AI agent 不代替人操作账号。请机器 B 负责人使用：

- 同一台机器；
- 同一网络；
- 同一个快手账号；
- 普通可见浏览器。

依次搜索：

```text
中山大学 宿舍条件
中山大学 快递
```

每个词只记录以下结论，不要抄录个人信息：

1. 是否显示正常视频结果；
2. 是否空白或提示无结果；
3. 是否出现登录提示、验证码、滑块、访问频繁或其他限制；
4. 页面是否能继续翻页或滚动加载。

不要退出账号、清 Cookie、切换账号、换网络或关闭代理设置。任何改变都需要机器 A/任务负责人另行决定。

### 步骤 9：收集现有原始终端日志

如果第二次运行的终端内容仍可查看，截取或复制以下范围：

```text
[KuaiShouClient.pong] Begin pong kuaishou...
```

到第一个关键词出现：

```text
[KuaishouCrawler.search] Search result empty or abnormal, stop paging
```

同时保留范围内含有下列词的原始行：

```text
login
pong
Current search keyword
page
pcursor
searchSessionId
visionSearchPhoto
result
feeds
error
exception
captcha
proxy
```

要求：

- 不重新运行爬虫来制造日志；
- 不把总结替代原始日志；
- 如果日志已经丢失，明确写“原始终端日志不可用”；
- 如果日志意外包含 Cookie、token、请求头或 `.env` 值，必须把值替换为 `[REDACTED]`。

---

## 六、结果判断树

### 情况 A：普通网页搜索也为空或出现验证/限制

结论方向：账号、会话、IP 或网络层面的搜索限制，极可能是静默风控或临时限流。

操作：

- 报告事实；
- 停止检查；
- 不再次播种；
- 不自行换账号、换网络、清 Cookie 或调整代理；
- 等待机器 A/任务负责人决定冷却时间和后续方案。

### 情况 B：普通网页搜索正常，但三个关键文件有哈希不一致

结论方向：机器 B 使用的项目副本与机器 A 不一致。

操作：

- 列出不一致文件和实际哈希；
- 停止检查；
- 不执行 Git、复制或覆盖；
- 等待机器 A/任务负责人决定同步方式。

### 情况 C：普通网页搜索正常，三个关键文件也一致

结论方向：问题局限在爬虫的 `visionSearchPhoto` GraphQL 请求或返回结构；现有日志没有保存原始响应体，无法再凭共享数据库区分：

- `videos_res` 为空；
- `visionSearchPhoto` 缺失；
- `result != 1`；
- `feeds=[]`。

操作：

- 提交本轮报告；
- 不修改代码；
- 等待机器 A/任务负责人明确授权后，才可以考虑临时诊断日志或单关键词探针。

### 情况 D：发现 KS 爬虫仍在运行，或队列出现新的 `pending/claimed`

操作：

- 立即报告进程和队列原始状态；
- 不启动、终止、回收、重排任何任务；
- 不继续其余可能影响现场的检查。

---

## 七、回传给机器 A 的报告模板

请机器 B 的 AI agent 完成检查后，严格按以下格式输出：

````markdown
# KS `empty_page` 机器 B 只读检查报告

## 1. 检查信息
- 检查时间：
- 项目绝对路径：
- 执行者：机器 B AI agent（只读）

## 2. 进程与队列
- 是否存在运行中的 KS 爬虫：
- 进程信息（若有）：
- KS 队列原始输出：

## 3. 文件一致性
| 文件 | 实际 SHA256 | 是否与机器 A 一致 |
|---|---|---|
| core.py | | |
| client.py | | |
| search_query.graphql | | |

## 4. 配置快照
- LOGIN_TYPE：
- ENABLE_IP_PROXY：
- HEADLESS：
- CDP_CONNECT_EXISTING：
- SAVE_DATA_OPTION：
- START_PAGE：
- CRAWLER_MAX_NOTES_COUNT：
- CRAWL_MAX_PAGES_PER_KEYWORD：
- KS_SKIP_EXISTING_NOTES：
- CRAWL_PUBLISH_TIME_START：
- CRAWL_PUBLISH_TIME_END：
- SEARCH_START_PAGE_JITTER_PROB：
- SEARCH_START_PAGE_JITTER_MAX：

## 5. 运行环境
- Python：
- playwright：
- httpx：
- sqlalchemy：
- KS 用户目录是否存在/最后修改时间：

## 6. 人工网页搜索
### 中山大学 宿舍条件
- 是否有正常结果：
- 是否有验证/限制提示：
- 是否能继续加载：

### 中山大学 快递
- 是否有正常结果：
- 是否有验证/限制提示：
- 是否能继续加载：

## 7. 原始终端日志
```text
在这里粘贴脱敏后的原始日志；不可用则明确说明。
```

## 8. 结论
- 已确认事实：
- 基于证据的推断：
- 对应判断树：A / B / C / D
- 仍缺少的证据：

## 9. 明确未执行的操作
- 未修改代码或配置
- 未执行 Git
- 未清理 Cookie/用户目录
- 未启动或终止爬虫
- 未播种、重排或删除队列
- 未执行入库链
- 未输出任何凭据值
````

---

## 八、机器 A 收到报告后的下一步（机器 B 不执行）

机器 A/任务负责人根据报告拍板：

1. 如果属于账号/IP/会话限制：决定冷却、重新登录或其他人工方案；
2. 如果属于文件不一致：决定安全的同步方式；
3. 如果网页正常且文件一致：决定是否授权增加临时诊断日志；
4. 现场恢复后，先对计划内关键词 `宿舍条件` 做一次 KS-only 单词 dry-run → 确认 → 正式播种；
5. 只有单词探针确认 `items_seen > 0` 后，才考虑补播其余 11 个第 2 轮关键词。

未经上述确认，不要进行第三次整批重播。
