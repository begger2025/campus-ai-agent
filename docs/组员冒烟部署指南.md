# 组员部署 + 两台机协同冒烟指南

> **给谁看**：收到项目文件夹、要和协调人（发你文件的同学）一起做"两台机分布式爬取冒烟测试"的组员。
> **你要达成什么**：在你自己的电脑上把爬虫跑起来，用 `--from-queue yes` 模式，和协调人的电脑**同时**从共享数据库认领互不重叠的关键词一起爬。
> **难度**：跟着做即可；卡住了把对应章节 + 报错整段发给 AI 或协调人。命令都在 **PowerShell**（Windows 自带）里执行。

---

## 0. 先搞清楚：你和协调人各干什么

| 谁 | 做什么 |
|---|---|
| **协调人**（发你文件的人） | 已建好共享数据库的队列表；负责**播种关键词**、**把你的公网 IP 加进数据库白名单**、跑他自己那台、用监控脚本看进度 |
| **你**（组员） | 装环境、**把公网 IP 告诉协调人**、跑你这台爬虫、把结果告诉协调人 |

**⚠️ 开跑前，你必须先找协调人确认两件事（否则一定连不上/没活干）：**
1. **他已经把你的公网 IP 加进了阿里云 RDS 白名单**（见第 4 步，你先把 IP 给他）；
2. **他已经播种了队列任务**（否则你一跑就"queue drained 秒退"，因为没关键词可领）。

---

## 1. 装软件（一次性）

| 软件 | 怎么装 | 必需？ |
|---|---|---|
| **Google Chrome** | [google.cn/chrome](https://www.google.cn/chrome/) 下载安装 | ✅ 必需（爬虫会自动拉起 Chrome 让你扫码登录） |
| **Python 3.11** | [python.org](https://www.python.org/downloads/release/python-3119/) 装 3.11.x；安装时**勾选 "Add Python to PATH"** | ✅ 必需 |
| **uv**（Python 环境工具） | 装完 Python 后，PowerShell 里跑：`pip install uv` | ✅ 强烈推荐（重建环境最快） |
| **Node.js** | [nodejs.org](https://nodejs.org/) | ⛔ 只有跑**知乎**才要；本次冒烟用**快手**，不用装 |

装完在 PowerShell 里验证（各自应打印版本号）：
```powershell
python --version      # 期望 Python 3.11.x
uv --version
```

---

## 2. 拿到项目文件

协调人会把文件夹发给你（可能是整个 `campus-ai-agent_v3`，也可能只发 `MediaCrawler` 子文件夹——**你只需要 `MediaCrawler` 这一个子文件夹**就能参与爬取）。

放到一个**路径不含特殊字符**的地方（中文路径也可以，本项目一直用中文路径没问题）。下文用 `<项目路径>` 代指你放 `MediaCrawler` 的位置，例如 `D:\campus\MediaCrawler`。

**两个关键检查：**
1. **确认 `MediaCrawler\.env` 文件在**（这是隐藏文件，里面是数据库账号密码）。如果协调人用压缩包发的，`.env` 有可能被漏掉——打开 `MediaCrawler` 文件夹，在资源管理器"查看"里勾上"隐藏的项目"，确认能看到 `.env`。**看不到就找协调人单独要这个文件**，否则连不上数据库。
2. **删掉拷过来的 `.venv` 文件夹**（在 `MediaCrawler\.venv`）。它是协调人机器上生成的，写死了他的路径，到你这儿用不了，第 3 步会重建。

---

## 3. 重建运行环境（一次性，约 3-5 分钟）

在 PowerShell 里（`cd` 到你的 `MediaCrawler` 目录）：

```powershell
cd "<项目路径>\MediaCrawler"

# 1) 删掉失效的旧环境（如果还在）
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue

# 2) 用 uv 重建虚拟环境（自动用 Python 3.11）
uv venv

# 3) 装依赖（读 requirements.txt，约 2-3 分钟）
uv pip install -r requirements.txt

# 4) 装 playwright 浏览器驱动（CDP 连接失败时的兜底模式要用）
.\.venv\Scripts\python.exe -m playwright install chromium
```

> **没有 uv 的备选**：`py -3.11 -m venv .venv` → `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` → 再跑上面第 4 步。

完成后目录里会有一个新的 `.venv` 文件夹。

---

## 4. 把公网 IP 给协调人（白名单握手）

数据库有 IP 白名单，只有名单里的公网 IP 能连。**你要把自己的公网 IP 发给协调人，他加进白名单后你才能连上。**

**⚠️ 关键顺序：先关代理，再查 IP。** 如果开着 Clash/VPN，查到的是代理出口 IP，加错了没用。

```powershell
# 1) 先关掉本机代理（当前 PowerShell 窗口生效）
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:http_proxy,Env:https_proxy -ErrorAction SilentlyContinue
# 并在任务栏关掉 Clash 的"系统代理"开关

# 2) 查你的公网 IP
Invoke-RestMethod -Uri "https://api.ipify.org"
```

把打印出来的 IP（形如 `123.45.67.89`）发给协调人，让他加进阿里云 RDS 白名单，等他回复"加好了"。

**验证能连上**（协调人加完白名单后跑；`import config` 会自动读取 `MediaCrawler\.env` 里的数据库地址）：
```powershell
cd "<项目路径>\MediaCrawler"
.\.venv\Scripts\python.exe -c "import config,os,socket; h=os.getenv('MYSQL_DB_HOST'); p=int(os.getenv('MYSQL_DB_PORT') or 3306); socket.create_connection((h,p),8).close(); print('可连 RDS:', h, p)"
```
- 打印 **`可连 RDS: rm-... 3306`** → 白名单 + 网络都通了，继续下一步。
- 卡住约 8 秒后报 **`timed out`** → 白名单还没加上（或加的 IP 不对）。回到本步开头，**确认代理已关**再重查 IP 发给协调人。

---

## 5. 每次开跑前的准备（运行时，每次都要）

**① 关代理**（和第 4 步一样，每个新开的 PowerShell 窗口都要重来一遍）：
```powershell
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:http_proxy,Env:https_proxy -ErrorAction SilentlyContinue
$env:NO_PROXY = "127.0.0.1,localhost"
$env:PYTHONIOENCODING = "utf-8"
```
并**关掉 Clash 的"系统代理"开关**。（不关的话：扫码二维码会瞬间闪退、或浏览器连不上。）

**② 用你自己的账号扫码**：拷过来的 `browser_data` 可能带着协调人的登录态。建议删掉快手的登录缓存目录，确保用你自己的号：
```powershell
Remove-Item -Recurse -Force "<项目路径>\MediaCrawler\browser_data\cdp_ks_user_data_dir" -ErrorAction SilentlyContinue
```

---

## 6. 开跑！（核心命令）

确认协调人**已经播种了队列**（你可以先跑第 7 步的自检命令看看队列里有没有 pending 任务），然后：

```powershell
cd "<项目路径>\MediaCrawler"
.\.venv\Scripts\python.exe main.py --platform ks --from-queue yes --get_comment yes --worker 你的名字
```
- `--platform ks`：本次冒烟爬**快手**（和协调人约定同一个平台）。
- `--from-queue yes`：**队列模式**——不用你指定关键词，自动从共享库认领。
- `--worker 你的名字`：填你的名字（如 `--worker lisi`），监控里能看到是你在爬。

**跑起来后会发生什么：**
1. 自动弹出一个 Chrome 窗口，显示快手登录二维码 → **用你手机快手 App 扫码**。
2. 登录成功后，控制台开始滚动日志，你会看到类似：
   ```
   [run_keyword_queue] start worker=lisi platform=ks
   [store.crawl_queue.claim_task] claimed id=2 keyword=食堂 by=lisi
   [run_keyword_queue] done id=2 keyword=食堂 stored=8
   [store.crawl_queue.claim_task] claimed id=4 keyword=体育馆 by=lisi
   ...
   [run_keyword_queue] queue drained, exit
   ```
3. 看到 **`queue drained, exit`** 就是你这台把能领的关键词都爬完了、正常收工。

---

## 7. 怎么知道冒烟成功了（你和协调人一起看）

**核心成功标志：两台机各自领到的关键词互不重叠，合起来正好覆盖协调人播种的全部关键词，最后队列全部 done。**

**① 你这台的控制台**：日志里 `claimed ... keyword=X` 的那些 X，应该和协调人那台领到的**完全不一样**（比如你领"食堂/体育馆"，他领"宿舍/图书馆"），绝不会两台都出现同一个词。两台最后都打印 `queue drained, exit`。

**② 协调人跑监控脚本**（他在主项目根目录跑，你不用跑；这是最权威的一眼看结果）：
```
scripts\crawl_queue_status.py --platform ks
```
- 成功时汇总显示 **`pending=0 claimed=0 done=N failed=0`**（N = 播种的关键词数）；
- 脚本还会列出**"认领中"的任务是谁在爬哪个词**——两个人的名字都出现、且每个词只归一个人，就是零重复认领的铁证。

> 你自己不需要额外查库——**看你控制台的 `claimed ... keyword=X` 日志**，把这些 X 和协调人那台念一遍，对不上号（无重叠）就对了。权威结果以协调人的 status 脚本为准。

**反过来，异常信号：**
- 同一个关键词在两台机的日志里都出现 → 双认领（设计上不该发生，真出现把两边日志发协调人）。
- 你一跑就 `queue drained, exit`、什么都没爬 → 队列里没 pending 任务：让协调人先播种，或队列已经全 done 了。

---

## 8. 常见问题排查表

| 现象 | 原因 | 解法 |
|------|------|------|
| 连库 `2003 ... timed out` | 你的公网 IP 没在数据库白名单里 | **关代理**后重查公网 IP（第 4 步）发协调人，等他加白名单 |
| 二维码弹出即闪退 / 浏览器连不上 | 代理没关干净 | 第 5 步的关代理三行 + 关 Clash 系统代理，重开窗口再跑 |
| 日志出现 `CDP ... fallback to standard mode` 然后点不到登录按钮 | 没装 Chrome，或代理拦了本机 127.0.0.1 | 装 Google Chrome；`$env:NO_PROXY="127.0.0.1,localhost"`；关 Clash |
| 一跑就 `queue drained, exit` | 队列没任务（没播种 / 已全 done） | 找协调人播种；或用第 7 步自检看 pending 是否为 0 |
| `uv: 无法将...识别为命令` | 没装 uv | `pip install uv`；或用第 3 步的原生 venv 备选 |
| `python: 无法将...识别为命令` | Python 没加进 PATH | 重装 Python 3.11 勾选 "Add Python to PATH"，或用 `py -3.11` 代替 `python` |
| 扫码扫的是别人的号 | 用了协调人的登录缓存 | 第 5 步②删掉 `browser_data\cdp_ks_user_data_dir` 重扫 |

---

## 9. 如果你找 AI 帮忙，把这段话发给它

> 我在和同学做一个校园舆情项目的"两台机分布式爬虫冒烟测试"。项目是基于 MediaCrawler 改造的，我作为组员要在自己 Windows 电脑上用 `python main.py --platform ks --from-queue yes` 跑爬虫，从共享的阿里云 MySQL 认领关键词任务，和协调人的电脑同时爬快手、互不重叠。我需要：装 Python 3.11 + uv + Chrome、重建 MediaCrawler 的 .venv（拷来的用不了）、保留 MediaCrawler/.env（含数据库账号）、把我的公网 IP 发给协调人加进 RDS 白名单、关本机代理和 Clash、扫码登录我自己的快手号。请对照我遇到的具体报错帮我排查。

---

## 附：整个流程速览（按顺序）

```
装 Chrome + Python3.11 + uv
      ↓
拿到 MediaCrawler 文件夹（确认 .env 在、删掉旧 .venv）
      ↓
重建环境：uv venv → uv pip install -r requirements.txt → playwright install chromium
      ↓
关代理 → 查公网 IP → 发协调人加白名单 → 自检"可连 RDS"
      ↓
等协调人：白名单加好 + 队列已播种
      ↓
关代理 + 关 Clash（每次开跑都要）
      ↓
main.py --platform ks --from-queue yes --get_comment yes --worker 你的名字 → 扫码
      ↓
看到 queue drained, exit = 你这台收工
      ↓
和协调人一起核对：关键词不重叠、队列全 done = 冒烟成功 🎉
```
