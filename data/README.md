# data/ — 运行时数据目录

除本 README 与 `fixtures/` 外，本目录全部是**运行时产物**，已被 `.gitignore` 忽略：
Cookie、数据库、缓存、日志一律不进 Git。

## 目录内容

| 文件/目录 | 作用 | 如何产生 |
|-----------|------|----------|
| `campus.db` | SQLite 业务库（未配 MySQL 时的兜底主库） | 后端首次启动自动建 |
| `campus_demo.db` | 离线演示快照（`demo.bat` 使用，不碰共享 MySQL） | `scripts/make_demo_snapshot.py` |
| `chat_memory.sqlite3` | 舆情对话记忆持久层（服务重启后恢复多轮上下文） | 对话时自动写入 |
| `llm_cache.json` | LLM 响应缓存（**禁止提交**，含真实问答内容） | LLM 调用时自动写入 |
| `public_opinion_memory.json` | 舆情 Agent 进程记忆快照（**禁止提交**） | 运行时自动写入 |
| `post_vectors.npz` | 帖子语义向量缓存（语义补召回用） | embedding 构建脚本 |
| `cookies/` | 平台登录态（**禁止提交**） | `scripts/bat/save_*_login.bat` |
| `samples/` | 备用爬虫的采集输出 `posts_*.json` | `scripts/bat/crawl.bat` |
| `logs/` | 运行日志 | 运行时自动写入 |
| `backup_offtopic_posts.json` | 剔除离题帖时的备份（可恢复） | 数据清洗脚本 |
| `fixtures/` | 评测固定数据集（Git 跟踪，见下） | 人工构建 |

## fixtures/ 评测数据集

`fixtures/event_clustering_297.json`：297 条真实采集语料的快照，作为事件聚类/精修消融实验的
固定输入（保证各消融臂输入逐位一致，实验可复现，见 [docs/experiments/](../docs/experiments/)）。
内含帖子作者、平台 ID 与原帖 URL（URL 中的 `xsec_token` 为采集时的临时访问凭证，早已过期）；
仅用于本课程评测，不作他用。

## 数据如何进入页面

| 步骤 | 命令 | 结果 |
|------|------|------|
| 爬取 | `scripts\bat\crawl.bat`（备用链路）或 MediaCrawler | 新增 `samples/posts_*.json` |
| 入库 | `scripts\bat\import_latest.bat` | 写入业务库 |
| 展示 | `run.bat` + 浏览器 | 前端经 `/api` 读取 |

## 如何查看数据库

| 方式 | 说明 |
|------|------|
| `scripts\bat\view_db.bat` | 终端打印表统计与最近 20 条帖子 |
| [DB Browser for SQLite](https://sqlitebrowser.org/) | 图形化浏览、执行 SQL |
| VSCode SQLite 类扩展 | 直接双击 `.db` 文件浏览 |
