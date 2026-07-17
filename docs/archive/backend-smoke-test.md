# Week2 后端 Smoke Test 验收指南

本文档用于复现第二周后端公共舆情主链路验收。当前 smoke test 只覆盖公共舆情链路，不覆盖个人事项 Agent。

## 验收范围

固定链路：

```text
初始化数据库
-> 同步 MediaCrawler 数据到 raw_posts
-> 清洗 raw_posts 到 processed_posts
-> 基于 processed_posts 生成 public_events
-> 启动后端
-> 管理员登录
-> 管理员查看后台概览
-> 管理员审核并发布事件
-> 普通用户查看 published 事件
-> 用户提交反馈
-> 管理员查看反馈与日志
```

第二周不验收：

```text
personal_advices
/api/agent/personal/impact
/api/users/{user_id}/advices
个人事项 Agent 建议生成链路
```

## 前置条件

1. 已进入主项目目录：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
```

2. `.env` 中的 `DATABASE_URL` 指向共享 MySQL。

3. 虚拟环境已存在：

```powershell
Test-Path .\.venv\Scripts\python.exe
```

4. 不要求实时爬真实网站。脚本会优先同步已有 MediaCrawler 表；如果没有可用采集数据，会写入一条固定 fixture 数据用于验收链路。

## 一键验收

推荐直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_backend.ps1 -Limit 200 -Port 9010
```

可选参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_backend.ps1 `
  -Limit 200 `
  -Port 9010 `
  -Keyword campus `
  -AdminUsername smoke_admin `
  -AdminPassword smoke_admin_password `
  -UserUsername smoke_user `
  -UserPassword smoke_user_password
```

成功标志：

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
[OK] PATCH /api/admin/events/{id}/status
[OK] POST /api/feedback
[OK] GET /api/admin/feedback
[OK] GET /api/admin/system-logs
[OK] Week2 backend smoke test PASSED
```

失败时脚本会返回非 0 exit code，并输出具体失败步骤。

## 分步命令

如需人工逐步验收，可按以下顺序执行。

初始化数据库：

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

同步 MediaCrawler 数据：

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform all --limit 200
```

清洗 raw_posts：

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 200
```

生成 public_events：

```powershell
.\.venv\Scripts\python.exe scripts\generate_public_events.py --keyword campus --limit 200
```

启动后端：

```powershell
.\.venv\Scripts\python.exe backend\main.py
```

另开一个 PowerShell 窗口检查接口：

```powershell
Invoke-RestMethod http://127.0.0.1:9000/health
Invoke-RestMethod "http://127.0.0.1:9000/api/posts?page=1&page_size=5"
Invoke-RestMethod "http://127.0.0.1:9000/api/events?page=1&page_size=5"
```

管理员登录：

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:9000/api/auth/login" `
  -ContentType "application/json" `
  -Body '{"username":"admin","password":"你的管理员密码"}'

$headers = @{ Authorization = "Bearer $($login.data.access_token)" }
```

管理员概览：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:9000/api/admin/overview" `
  -Headers $headers
```

管理员查看事件：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:9000/api/admin/events?status=all&page=1&page_size=5" `
  -Headers $headers
```

管理员发布事件，将 `{event_id}` 替换成真实事件 id：

```powershell
Invoke-RestMethod `
  -Method Patch `
  -Uri "http://127.0.0.1:9000/api/admin/events/{event_id}/status" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"status":"published","review_comment":"smoke test publish"}'
```

提交反馈：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:9000/api/feedback" `
  -ContentType "application/json" `
  -Body '{"feedback_type":"content_issue","content":"smoke test feedback","contact":"wp10@example.com"}'
```

管理员查看反馈与日志：

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/admin/feedback?page=1&page_size=5" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:9000/api/admin/system-logs?page=1&page_size=5" -Headers $headers
Invoke-RestMethod "http://127.0.0.1:9000/api/admin/operation-logs?page=1&page_size=5" -Headers $headers
```

## 数据库验收项

Smoke test 至少检查：

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

## 权限验收项

`/api/admin/overview` 必须满足：

```text
不带 token -> 401
普通用户 token -> 403
管理员 token -> 200
```

## 常见失败排查

1. `Python virtual environment not found`：先运行项目安装脚本或确认 `.venv` 是否在主项目目录下。
2. MySQL 连接失败：检查当前网络是否允许访问共享 MySQL 的 3306 端口，并确认 `.env` 的 `DATABASE_URL` 正确。
3. `/api/admin/overview` 返回 401：管理员登录失败或 token 没有放入 `Authorization: Bearer ...`。
4. `/api/events` 为空：确认至少有一个事件被发布为 `published`；管理员接口中的 draft/rejected/archived 不会出现在普通用户接口。
5. MediaCrawler 没有数据：这不阻塞 smoke test，脚本会写入固定 fixture，保证后端链路可验收。
