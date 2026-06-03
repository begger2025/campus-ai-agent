# 如何采集真实数据（非 demo）

微博 **432**、贴吧 **超时** 是因为没有登录态 / 被反爬。按下面做即可。

---

## 方案 A：微博登录态（推荐）

### 1. 保存登录（只需一次）

```cmd
cd C:\Users\pissy\Desktop\campus-ai-agent
.\.venv\Scripts\python.exe scripts\save_weibo_login.py
```

- 会自动打开 Chrome
- 在页面里 **登录你的微博账号**
- 回到黑窗口 **按回车**
- 生成文件：`data/cookies/weibo_state.json`（不要上传到 GitHub）

### 2. 采集

```cmd
双击 crawl.bat
```

或：

```cmd
.\.venv\Scripts\python.exe crawler\run_once.py --no-demo
```

`--no-demo`：真实采集不足 20 条时 **不** 自动补 demo，方便你看真实结果。

### 3. 看结果

- 日志里 `微博采集完成: N 条`，N > 0 即成功
- JSON：`data/samples/posts_*.json`，看 `meta.mode` 应为 `live` 或 `live+demo_fallback`

---

## 方案 B：手动复制 Cookie（可选）

1. 浏览器登录 [m.weibo.cn](https://m.weibo.cn)
2. F12 → 网络 → 刷新 → 任选一个 `getIndex` 请求 → 复制 **Cookie** 整段
3. 写入项目根目录 `.env`：

```env
WEIBO_COOKIE=SUB=xxx; SSOLoginState=xxx; ...
```

4. 再运行 `crawl.bat`

---

## 贴吧仍失败时

在 `.env` 可增加：

```env
TIEBA_TIMEOUT=90
TIEBA_RETRIES=5
CRAWLER_HEADLESS=false
```

`CRAWLER_HEADLESS=false` 会弹出浏览器，有时能绕过验证（需人工点验证码）。

---

## 导入后端

```cmd
.\.venv\Scripts\python.exe scripts\import_posts.py data\samples\posts_最新.json
双击 run.bat
```

浏览器打开：http://127.0.0.1:9000/posts

---

## 注意

- 仅用于课程/研究，控制频率，不要高频爬取
- 不要提交 `data/cookies/`、`.env` 到 Git
- 真实爬取仍可能因平台策略失败，失败记录写在 `docs/crawl-issues.md`
