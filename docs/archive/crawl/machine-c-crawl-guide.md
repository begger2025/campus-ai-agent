# 机器 C 协同爬取指导手册（A + C 两机并行）

> **用途**：机器 C 负责人将本文档交给机器 C 上的 AI 助手，按文档推进爬取。
>
> **给机器 C 上 AI 的授权边界（先读这段）**：
> - ✅ 允许：按本文档搭环境、核对配置、运行爬取命令、查看日志、报告结果
> - ❌ 禁止：修改爬虫代码、调小任何 sleep/风控参数、重置队列（`reset_crawl_queue.py`）、
>   直接写数据库、把 `.env` 或任何密钥粘贴到聊天/文档/截图里
> - 队列播种、入库四步、事件审核**全部由机器 A 执行**，机器 C 只负责"认领并爬"
> - 遇到文档没覆盖的情况：停下来，把日志原文报给机器 A 负责人，不要自行发挥

---

## 一、背景：你接替的是谁、从哪里继续

- 本项目是中山大学校园舆情平台的语料采集，多机从**共享 MySQL 队列**认领关键词并行爬取，
  互不重叠（原子认领），同时写共享库。总计划见附录 A（96 词 8 轮）。
- 第 1 轮（T1 词组，xhs + ks）已完成：新增 418 条。
- 第 2 轮（住宿后勤 12 词）：**xhs 部分已完成**（机器 A + B 并行爬完）；
  **ks 部分两次全部空跑**——机器 B 的快手搜索接口被静默限流（登录检测 `pong` 通过，
  但搜索接口 `visionSearchPhoto` 永远返回空页，24 次运行 `items_seen=0`，任务被假标成
  `done`，实际入库 **0 条**）。机器 B 已退出协同。
- **机器 C 的首个任务：补爬第 2 轮的 ks（12 词）**，之后按附录 A 与机器 A 并行推进第 3~8 轮。

---

## 二、环境搭建（一次性）

### 2.1 需要从机器 A 负责人处获取的东西

| 东西 | 说明 |
|---|---|
| 项目代码 | 完整项目目录（含 `MediaCrawler/` 子目录），从团队仓库拉取或直接拷贝压缩包 |
| `.env` 文件 | 放在项目根目录。含共享数据库连接与 API key（键名如 `DB_HOST/DB_USER/DB_PASSWORD/...`）。**私下传输，绝不进群聊/文档/截图** |
| `MediaCrawler/config/base_config.py` | **在 git 里有基线版本**，但各机的本地调参（关键词残值/风控 sleep 等）**绝不提交**——直接要机器 A 的当前版本才能拿到未提交的本地调整，别指望 git pull |

### 2.2 机器 C 本机要求

- Windows + PowerShell，Python 3.11+
- **已安装 Chrome 或 Edge**（爬虫用 CDP 模式驱动本机真实浏览器，反检测依赖它）
- 一个**机器 A 没在用的快手账号**（两机同号并发搜索 = 给自己送风控）
- 网络能直连共享 RDS：**跑前关闭 Clash/系统代理**（实测代理会让数据库连接超时）

### 2.3 安装依赖（项目根目录执行）

```powershell
cd <项目根目录>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r MediaCrawler\requirements.txt
```

### 2.4 验证数据库连通（必做，别等爬完才发现写不进去）

```powershell
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
```

### 2.5 核对 `MediaCrawler/config/base_config.py` 关键项

```python
LOGIN_TYPE = "qrcode"
SAVE_DATA_OPTION = "db"          # 必须是 db：直接写共享库原生表
ENABLE_CDP_MODE = True
CDP_CONNECT_EXISTING = False     # False = 自动开新浏览器让你扫码
HEADLESS = False                 # 必须 False，否则扫不了码
CRAWLER_MAX_NOTES_COUNT = 40     # 每词新增入库封顶
CRAWLER_MIN_SLEEP_SEC = 8        # ⚠️ 所有 sleep/风控参数一律不许调小
KS_SKIP_EXISTING_NOTES = True    # 已入库的跳过，配额只烧在真新增上
```

> 评论抓取（config 里 `ENABLE_GET_COMMENTS = False`）由**命令行 `--get_comment yes` 开启**，
> 不用改配置文件。图片/视频下载保持关闭（`ENABLE_GET_MEIDAS = False`），不要打开。

---

## 三、首个任务：第 2 轮 ks 补爬（12 词）

### 3.0 机器 B 的教训 → 先做单词健康验证

机器 B 的故障形态是"**一切看起来正常但永远抓到零**"：登录成功、任务秒完成、日志无报错。
为避免机器 C 重蹈覆辙，**先用 1 个词验证搜索接口真的返回数据，再放全量**：

1. **人工预检**：在机器 C 的浏览器里打开 kuaishou.com，登录你的快手账号，
   手动搜索「中山大学 宿舍」——确认能看到正常的视频结果列表（不是空页/异常页）。
2. 机器 A 先只播种 1 个词（`宿舍条件`，ks），机器 C 跑下面 §3.1 的命令。
3. **判定标准（看机器 C 的运行日志）**：
   - ✅ 健康：日志出现 `items_seen` > 0（哪怕最后入库为 0——可能都是重复/被过滤）
   - ❌ 复现机器 B 故障：`pages_fetched=1, items_seen=0, stop_reason=empty_page`
     且几十秒就结束 → **立刻停**，报告机器 A，换账号或换时段，不要反复重试
4. 健康验证通过后，机器 A 播种其余 11 词，机器 C 继续跑同一条命令（队列模式会自动认领）。

### 3.1 爬取命令（机器 C）

```powershell
cd <项目根目录>\MediaCrawler

.\.venv\Scripts\python.exe main.py `
  --platform ks `
  --from-queue yes `
  --worker machine-c `
  --get_comment yes `
  --fresh yes
```

**逐参数解释：**

| 参数 | 作用 |
|---|---|
| `--platform ks` | 快手 |
| `--from-queue yes` | 队列模式：扫码登录一次，循环认领关键词直到队列排空，自动退出 |
| `--worker machine-c` | 你的身份标识（监控页显示谁在爬哪个词；可换成负责人拼音） |
| `--get_comment yes` | 抓一级评论（每帖最多 10 条），评论进情绪分析语料 |
| `--fresh yes` | 尽量新内容优先 |
| **（没有 `--start_date`）** | ⚠️ **快手铁律：绝不带时间窗口**。快手无服务端时间排序，带窗口实测会全灭空窗 |

### 3.2 跑起来之后

1. 浏览器自动弹出 → 用**你自己的**快手账号扫码
2. 登录后自动循环认领，队列排空后打印 `queue drained` 自动退出
3. 快手节奏较快（第 1 轮实测 12 词约半小时~1 小时），不像小红书要睡几分钟

### 3.3 监控（随时可跑，另开终端，项目根目录）

```powershell
.\.venv\Scripts\python.exe scripts\crawl_queue_status.py --platform ks
```

期望最终状态：`pending=0 claimed=0`，done 是大头。
`claimed` 带 `[卡死待回收]` = 某机崩了，**报告机器 A** 处理（回收命令只允许机器 A 执行）。

### 3.4 跑完之后

把三样东西报给机器 A：①最终队列状态输出；②日志里若干条 `items_seen/items_stored` 样例；
③有没有 `empty_page`/验证码记录。**入库四步由机器 A 执行**，机器 C 到此为止。

---

## 四、后续轮次：机器 C 的常规角色

每轮的分工（机器 A 播种和入库，机器 A + C 并行爬取）：

| 步骤 | 谁 | 干什么 |
|---|---|---|
| 播种 | A | 把当轮 12 词 × 平台写入队列 |
| 爬 xhs | **A + C 并行** | 同一条命令、只有 `--worker` 不同（见下）；两机用**不同**小红书账号 |
| 爬 ks | A 或 C 任一 | §3.1 的命令（**不带 --start_date**） |
| 爬 zhihu | A 或 C 任一 | 同 xhs 命令但 `--platform zhihu` |
| 入库+审核 | A | sync → process → 向量 → 事件生成 → 人工审核 |

**机器 C 的 xhs 命令**（仅在机器 A 通知本轮开爬后执行）：

```powershell
cd <项目根目录>\MediaCrawler
.\.venv\Scripts\python.exe main.py `
  --platform xhs `
  --from-queue yes `
  --worker machine-c `
  --get_comment yes `
  --fresh yes `
  --start_date <机器A告知的日期，= 今天往前30天，如 2026-06-16>
```

**小红书的节奏预警**（和快手完全不同，这是保守风控模式，不是卡死）：
- 每个关键词最多抓 **5 条详情**，每条详情前后各睡 1~3 分钟
- 单机跑 6 个词 ≈ **2~2.5 小时**，日志长时间"没动静"是在 `Sleeping ... before detail fetch`
- **绝不因为慢去调参数**——触发验证码会 fail-fast 停掉整个关键词

---

## 五、坑清单（每条都真实发生过）

| 坑 | 表现 | 规避/处置 |
|---|---|---|
| ks 静默限流（机器 B 之死） | 登录正常、秒完成、`items_seen=0` | 先做 §3.0 单词验证；复现就停手上报 |
| ks 带 `--start_date` | 综合排序返老视频，窗口过滤后全灭 | ks 永远不带时间窗口 |
| 两机同一账号 | 风控概率飙升 | A、C 各用各的账号（每个平台都是） |
| Clash/系统代理开着 | 连 RDS 超时、脚本报网络错 | 跑前关代理，先跑 `verify_db_connection.py` |
| 小红书日志"卡住" | 其实在 sleep | 看日志 `Sleeping ...`，别 Ctrl+C |
| 为提速调小 sleep | 验证码 → fail-fast 整轮白跑 | 一律不许调 |
| 队列计数偏少 | `items_stored=0` 但数据在库里 | 已知记账缺陷，以数据库实际行数为准 |
| 微博平台码 | 写 `weibo` 会报错 | 是 `wb` |

---

## 附录 A：总关键词计划（96 词 8 轮）

> 播种由机器 A 执行，此表供机器 C 了解全局进度。平台策略：每轮词播 xhs + ks 双平台；
> 知乎每两轮补播一次。当前进度：**第 1 轮完成；第 2 轮 xhs 完成、ks 由机器 C 补爬（当前任务）**。

| 轮次 | 词组 | 关键词 | 状态 |
|---|---|---|---|
| 1 | T1 进行中事件+口碑词 | 宿舍搬迁 搬宿舍 学术不端 实名举报 课间缩短 图书馆预约 吐槽 避雷 劝退 维权 投诉 后悔 | ✅ 完成 |
| 2 | 住宿后勤 | 宿舍条件 宿舍空调 宿舍热水 宿舍卫生 宿舍维修 宿舍限电 宿舍分配 四人间 洗衣机 澡堂 门禁 快递 | xhs ✅ / **ks ← 机器C补爬** |
| 3 | 饮食+毕业招生季 | 食堂 饭堂 食堂价格 食堂涨价 食堂卫生 外卖 夜宵 毕业季 毕业照 录取 分数线 招生 | 待开始 |
| 4 | 学业教务 A | 选课 抢课 转专业 绩点 保研 考研 挂科 补考 期末 早八 学分 延毕 | 待开始 |
| 5 | 学业教务 B+就业 | 毕业论文 查重 就业 实习 秋招 校招 考公 offer 辅导员 教务处 奖学金 助学金 | 待开始 |
| 6 | 行政权益+安全 A | 评优 处分 校规 请假 报销 学生会 校医院 心理咨询 诈骗 电诈 偷拍 骚扰 | 待开始 |
| 7 | 安全 B+设施 | 校车 电动车 消防 失物 图书馆 体育馆 游泳池 教学楼 校园网 电梯 施工 修路 | 待开始（ks「体育馆」有一条 failed 待重排） |
| 8 | 校区+节点性 | 东校区 南校区 珠海校区 深圳校区 校庆 放假安排 社团 校园卡 转学 新生 迎新 开学 | 待开始 |

> 节奏：隔天一轮；T1 每两周复播追增量。目标：近 30 天帖子 ≥500、总量 1500~3000（到 3000 边际收益变平）。

## 附录 B：机器 A 侧的配套动作备忘（机器 C 不执行）

```powershell
# 第 2 轮 ks 补爬播种：先 1 词验证
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform ks --keywords "宿舍条件" --dry-run
# 验证通过后播其余 11 词
.\.venv\Scripts\python.exe scripts\seed_crawl_queue.py --platform ks `
  --keywords "宿舍空调,宿舍热水,宿舍卫生,宿舍维修,宿舍限电,宿舍分配,四人间,洗衣机,澡堂,门禁,快递" --dry-run
# 爬完入库四步（--limit 0 必须写！--refresh 传导复播时顺路刷新的互动量）
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --limit 0 --refresh
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 0 --refresh
.\.venv\Scripts\python.exe scripts\build_post_vectors.py
.\.venv\Scripts\python.exe scripts\generate_public_events.py --preview   # 确认后去掉 --preview
```
