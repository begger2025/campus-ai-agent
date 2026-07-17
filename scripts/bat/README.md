# scripts/bat — 双击即用的 Windows 批处理

给不敲命令行的组员用的入口，全部会先 `cd` 回项目根再执行，**在资源管理器双击即可**。
前置条件：先在项目根跑过一次 `setup.bat`（建 venv + 装依赖）。

| 批处理 | 作用 | 对应脚本 |
|--------|------|----------|
| `save_weibo_login.bat` | 保存微博登录态（只需一次） | `scripts/save_weibo_login.py` |
| `save_tieba_login.bat` | 保存贴吧登录态（只需一次，否则贴吧常为 0 条） | `scripts/save_tieba_login.py` |
| `crawl.bat` | 备用链路采集，输出 `data/samples/posts_*.json` | `crawler/run_once.py` |
| `import_latest.bat` | 自动找最新样本导入数据库 | `scripts/import_posts.py` |
| `init_db.bat` | 初始化建表 | `scripts/init_db.py` |
| `seed_demo.bat` | 本地空库灌演示数据（**勿对共享 MySQL 用**） | `scripts/seed_demo.py` |
| `verify_db.bat` | 验证数据库连接与表完整性 | `scripts/verify_db_connection.py` |
| `view_db.bat` | 终端打印库统计与最近 20 条帖子 | `scripts/view_db.py` |

典型采集流程：登录态（一次）→ `crawl.bat` → `import_latest.bat` → 回根目录 `run.bat` 看页面。

根目录保留的高频批处理是另一组：`setup.bat`（首次安装）、`run.bat`（启动）、
`dev.bat`（开发模式）、`demo.bat`（离线快照演示）、`stop.bat`（停止）。
