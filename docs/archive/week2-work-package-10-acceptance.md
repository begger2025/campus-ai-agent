# Week2 后端工作包 10 验收报告：后端 Smoke Test 与文档

验收日期：2026-06-07

## 结论

工作包 10 已完成并通过验收。

本次验收覆盖第二周公共舆情后端主链路：

```text
MediaCrawler 数据 -> raw_posts -> processed_posts -> public_events
-> 管理员登录 -> 管理员审核发布事件
-> 普通用户查看 published 事件
-> 用户提交反馈 -> 管理员查看反馈与日志
```

第二周 smoke test 不覆盖个人事项 Agent，不检查：

```text
personal_advices
/api/agent/personal/impact
/api/users/{user_id}/advices
```

## 本次新增或更新文件

```text
scripts/check_wp10.py
scripts/generate_public_events.py
scripts/smoke_backend.py
scripts/smoke_backend.ps1
docs/backend-smoke-test.md
docs/api.md
docs/database.md
docs/week2-work-package-10-acceptance.md
README.md
```

## 关键实现

1. 新增 `scripts/generate_public_events.py`，作为 `processed_posts -> public_events` 的命令行入口。
2. 新增 `scripts/smoke_backend.py`，串联数据库初始化、采集数据同步、帖子清洗、Agent 事件生成、后端接口调用、权限检查、审核日志检查、用户反馈检查。
3. 新增 `scripts/smoke_backend.ps1`，作为 Windows 一键 smoke test 入口。
4. 新增 `docs/backend-smoke-test.md`，记录验收命令、预期输出、权限检查和排错方式。
5. 更新 `docs/api.md`，补齐第二周实际后端接口，包括认证、管理员后台、反馈、日志、公共舆情 Agent。
6. 更新 `docs/database.md`，补齐第二周 smoke test 涉及的数据库表与检查项。
7. 更新 `README.md`，加入“第二周后端 Smoke Test”入口。

## 执行过的验收命令

文件完整性与语法检查：

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; compile(Path('scripts/smoke_backend.py').read_text(encoding='utf-8'), 'scripts/smoke_backend.py', 'exec'); compile(Path('scripts/generate_public_events.py').read_text(encoding='utf-8'), 'scripts/generate_public_events.py', 'exec'); compile(Path('scripts/check_wp10.py').read_text(encoding='utf-8'), 'scripts/check_wp10.py', 'exec'); print('python syntax ok')"
```

结果：

```text
python syntax ok
```

WP10 总验收：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp10.py --limit 20 --port 9010
```

结果摘要：

```text
[OK] backend smoke doc contains fixed commands and API checks
[OK] api.md documents auth, feedback, and admin log APIs
[OK] database.md documents Week2 operational tables
[OK] README includes Week2 backend smoke test entry
[OK] Week2 backend smoke test PASSED
WP10 backend smoke test checks PASSED.
```

一键 PowerShell 入口验收：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_backend.ps1 -Limit 20 -Port 9011
```

结果摘要：

```text
[OK] init database
[OK] sync media to raw_posts
[OK] process raw_posts
[OK] generate public_events
[OK] GET /health
[OK] GET /api/posts
[OK] GET /api/events
[OK] admin overview without token -> 401
[OK] admin overview with normal user token -> 403
[OK] GET /api/admin/overview
[OK] PATCH /api/admin/events/1/status
[OK] POST /api/feedback
[OK] GET /api/admin/feedback
[OK] GET /api/admin/system-logs
[OK] GET /api/admin/operation-logs
[OK] Week2 backend smoke test PASSED
```

## 回归检查

工作包 4：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py
```

结果：

```text
WP4 data pipeline checks PASSED.
```

工作包 5：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp5.py
```

结果：

```text
WP5 public opinion Agent checks PASSED.
```

工作包 8：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp8.py
```

结果：

```text
WP8 admin backend API checks PASSED.
```

工作包 9：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp9.py
```

结果：

```text
WP9 logs, feedback, crawl task checks PASSED.
```

## 数据库验收结果

Smoke test 最终确认共享 MySQL 中关键表均有数据：

```text
raw_posts > 0
processed_posts > 0
public_events > 0
crawl_tasks > 0
agent_run_logs > 0
event_review_logs > 0
admin_operation_logs > 0
user_feedback > 0
```

实际一次 smoke 输出中的计数摘要：

```text
raw_posts=100
processed_posts=100
public_events=4
crawl_tasks=6
agent_run_logs=6
event_review_logs=11
admin_operation_logs=12
user_feedback=4
```

## 权限验收结果

`/api/admin/overview` 权限检查通过：

```text
不带 token -> 401
普通用户 token -> 403
管理员 token -> 200
```

## 注意事项

1. 本 smoke test 不依赖真实网站实时爬取；如果 MediaCrawler 表没有可同步数据，脚本会写入固定 fixture，保证后端链路可验收。
2. 由于共享数据库中已有数据，部分同步或清洗步骤可能显示 `inserted=0`，这表示数据已存在，不代表链路失败。
3. `keyword=campus` 在当前数据中可能没有匹配事件，脚本会自动 fallback 到不带关键词的 Agent 分析，以保证 smoke test 重点验证链路可用性。
4. 执行 smoke test 会向共享数据库写入验收用任务、Agent 运行日志、审核日志、管理员操作日志和反馈记录。
