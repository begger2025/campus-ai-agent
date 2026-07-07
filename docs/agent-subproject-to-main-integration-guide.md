# 公共舆情 Agent 子项目接入主项目下一步指导文档

生成日期：2026-06-07  
Agent 子项目：`D:\桌面文件\软件工程大作业\campus-opinion-agent`  
主项目：`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main`

## 1. 当前结论

根据当前检查结果，`campus-opinion-agent` 的 Week2 独立 Agent 开发包已经完成，主项目 `campus-ai-agent_v3` 也已经完成 Week2 后端工作包中的公共舆情主链路。

更关键的是：主项目现在已经不是“还没接 Agent”的状态，而是已经完成了第一轮技术接入。

当前主项目已经具备：

```text
backend/agent/public_opinion_core
backend/services/public_opinion_adapter.py
backend/routers/agent_public.py
backend/routers/admin_events.py
scripts/generate_public_events.py
scripts/smoke_backend.ps1
docs/backend-smoke-test.md
docs/api.md
docs/database.md
```

当前核对结果：

```text
Agent 子项目 public_opinion_core 与主项目 backend/agent/public_opinion_core 文件哈希完全一致。
主项目可以 import Agent 核心包。
Agent 子项目也可以 import 自己的核心包。
```

因此，下一步不要再简单重复“把 Agent 复制到主项目”。真正下一步是：

```text
确认主项目成为运行源
-> 固化 Agent 接入版本
-> 用真实数据库跑完整链路
-> 用接口验收管理员触发、审核、发布
-> 做前端/后台页面联调
-> 再考虑大模型增强
```

## 2. 当前项目分工边界

### 2.1 Agent 子项目现在的角色

`D:\桌面文件\软件工程大作业\campus-opinion-agent` 现在应作为：

```text
Agent 核心算法开发与回归测试参考项目
```

它保留：

- `public_opinion_core` 原始可迁移包。
- fixture 测试。
- CLI smoke test。
- Task1 到 Task9 的开发文档。
- API key 连通性测试脚本。

### 2.2 主项目现在的角色

`D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main` 现在应作为：

```text
正式运行源和最终验收源
```

后续真实运行、数据库写入、管理员审核、前端展示都应以主项目为准。

也就是说：

```text
用户和管理员只使用主项目；
Agent 子项目只用于算法维护、对照和回归测试。
```

## 3. 不要再做的事

接下来不要做这些事：

- 不要把 Agent 子项目整个 FastAPI 或前端搬进主项目。
- 不要让前端直接访问 `campus-opinion-agent`。
- 不要让 Agent 子项目直接写共享 MySQL。
- 不要在两个项目里分别改 Agent 规则但不做同步记录。
- 不要重复新增 `public_analysis_runs`，主项目已经使用 `agent_run_logs`。
- 不要让普通用户接口看到 `draft/rejected/archived` 事件。

## 4. 第一步：确认主项目 Agent 核心与子项目一致

在 PowerShell 执行：

```powershell
$src='D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\app\public_opinion_core'
$dst='D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\backend\agent\public_opinion_core'

Get-ChildItem -LiteralPath $src -Filter '*.py' | ForEach-Object {
  $name=$_.Name
  $srcHash=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
  $dstFile=Join-Path $dst $name
  $dstHash=if(Test-Path $dstFile){(Get-FileHash -LiteralPath $dstFile -Algorithm SHA256).Hash}else{'MISSING'}
  [PSCustomObject]@{
    File=$name
    Same=($srcHash -eq $dstHash)
    SourceHash=$srcHash.Substring(0,8)
    MainHash=if($dstHash -eq 'MISSING'){'MISSING'}else{$dstHash.Substring(0,8)}
  }
} | Format-Table -AutoSize
```

成功标志：

```text
adapter.py         Same = True
clustering.py      Same = True
normalizer.py      Same = True
payload_builder.py Same = True
schemas.py         Same = True
scoring.py         Same = True
sentiment_risk.py  Same = True
service.py         Same = True
__init__.py        Same = True
```

如果有 `False`：

1. 先不要覆盖文件。
2. 分别查看两边改动。
3. 判断是 Agent 子项目更新了，还是主项目后端适配时改了核心逻辑。
4. 确认后再同步。

## 5. 第二步：分别做 import 验证

### 5.1 Agent 子项目 import

```powershell
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent\backend"
.\.venv\Scripts\python.exe -c "from app.public_opinion_core import PublicOpinionAgentService, AnalyzeRequest, build_public_event_payloads; print('subproject agent import ok')"
```

成功标志：

```text
subproject agent import ok
```

### 5.2 主项目 import

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe -c "from backend.agent.public_opinion_core import PublicOpinionAgentService, AnalyzeRequest, build_public_event_payloads; from backend.services.public_opinion_adapter import run_public_opinion_analysis; print('main agent import ok')"
```

成功标志：

```text
main agent import ok
```

## 6. 第三步：在 Agent 子项目跑核心回归

这个步骤用于确认算法包本身没有坏。

```powershell
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent\backend"
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py"
.\.venv\Scripts\python.exe cli.py --format json --preview-limit 1
```

成功标志：

```text
Ran 37 tests
OK
input_count = 30
event_count = 4
public_events = 4
event_post_links = 20
agent_run_logs = 1
```

这一步不连接共享数据库，只验证 Agent 算法包。

## 7. 第四步：在主项目验证数据库与后端链路

进入主项目：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
```

### 7.1 检查数据库连接

```powershell
.\.venv\Scripts\python.exe scripts\verify_db_connection.py
```

成功标志：

```text
SELECT 1 succeeded
DATABASE_URL 指向共享 MySQL
```

### 7.2 初始化表结构

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

成功标志：

```text
不会报错
```

### 7.3 同步 MediaCrawler 数据到 raw_posts

```powershell
.\.venv\Scripts\python.exe scripts\sync_media_to_raw_posts.py --platform all --limit 200
```

成功标志：

```text
raw_posts 数量大于 0
```

注意：如果输出 inserted=0，但 raw_posts 原本已有数据，不一定是失败。

### 7.4 清洗 raw_posts 到 processed_posts

```powershell
.\.venv\Scripts\python.exe scripts\process_raw_posts.py --limit 200
```

成功标志：

```text
processed_posts 数量大于 0
```

### 7.5 预览 Agent 事件，不写库

建议先预览：

```powershell
.\.venv\Scripts\python.exe scripts\generate_public_events.py --limit 200 --preview
```

成功标志：

```text
[OK] public opinion analysis input_count>0 event_count>0
```

预览不会持久化写入 `public_events`。

### 7.6 正式生成 public_events

确认预览正常后再写库：

```powershell
.\.venv\Scripts\python.exe scripts\generate_public_events.py --limit 200 --created-by integration_check
```

成功标志：

```text
[OK] public opinion analysis input_count>0 event_count>0 run_log_id=<数字>
```

## 8. 第五步：跑后端工作包回归验收

这些命令会检查主项目后端目前是否真的满足 Week2 主链路。

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
```

建议按顺序执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_wp4.py --min-raw 1 --min-processed 1 --min-notes 1
.\.venv\Scripts\python.exe scripts\check_wp5.py --limit 50
.\.venv\Scripts\python.exe scripts\check_wp8.py
.\.venv\Scripts\python.exe scripts\check_wp9.py
.\.venv\Scripts\python.exe scripts\check_wp10.py --limit 20 --port 9010
```

成功标志：

```text
WP4 data pipeline checks PASSED
WP5 public opinion Agent checks PASSED
WP8 admin backend API checks PASSED
WP9 logs, feedback, crawl task checks PASSED
WP10 backend smoke test checks PASSED
```

注意：

```text
check_wp5/check_wp10 可能会向共享数据库写入验收事件、Agent 日志、审核日志、操作日志和反馈记录。
如果要避免污染共享数据库，先询问后端负责人是否允许在当前库执行。
```

## 9. 第六步：人工接口验收

### 9.1 启动后端

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main"
.\.venv\Scripts\python.exe backend\main.py
```

默认地址：

```text
http://127.0.0.1:9000
```

另开一个 PowerShell 窗口继续。

### 9.2 健康检查

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/health"
Invoke-RestMethod "http://127.0.0.1:9000/api/ping"
```

成功标志：

```text
status = ok
code = 0
database = campus_ai_agent
```

### 9.3 管理员登录

默认管理员账号来自主项目 `backend/services/auth_service.py`：

```text
username = admin
password = admin123456
```

如果 `.env` 配置了 `ADMIN_USERNAME` 或 `ADMIN_PASSWORD`，以 `.env` 为准。

登录：

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:9000/api/auth/login" `
  -ContentType "application/json" `
  -Body '{"username":"admin","password":"admin123456"}'

$headers = @{ Authorization = "Bearer $($login.data.access_token)" }
```

成功标志：

```text
$login.data.user.role = admin
$headers 中有 Bearer token
```

### 9.4 管理员触发 Agent 分析

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:9000/api/agent/public/analyze" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"keyword":"","limit":50,"platforms":[],"persist":true,"created_by":"manual_check"}'
```

成功标志：

```text
code = 0
data.input_count > 0
data.event_count > 0
data.payload_counts.public_events > 0
data.payload_counts.event_post_links > 0
data.payload_counts.agent_run_logs = 1
```

### 9.5 管理员查看全部事件

```powershell
$adminEvents = Invoke-RestMethod `
  -Uri "http://127.0.0.1:9000/api/admin/events?status=all&page=1&page_size=10" `
  -Headers $headers

$adminEvents.data.items | Select-Object raw_id,title,status,risk_level,source_count
```

成功标志：

```text
能看到 draft/published/rejected/archived 中的事件
```

### 9.6 发布一个 draft 事件

先取一个 draft 事件：

```powershell
$draftEvents = Invoke-RestMethod `
  -Uri "http://127.0.0.1:9000/api/admin/events?status=draft&page=1&page_size=5" `
  -Headers $headers

$eventId = $draftEvents.data.items[0].raw_id
```

发布：

```powershell
Invoke-RestMethod `
  -Method Patch `
  -Uri "http://127.0.0.1:9000/api/admin/events/$eventId/status" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"status":"published","review_comment":"manual integration publish"}'
```

成功标志：

```text
new_status = published
```

### 9.7 普通用户查看 published 事件

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/events?page=1&page_size=10"
```

成功标志：

```text
只返回 status = published 的事件
不返回 draft/rejected/archived
```

事件详情：

```powershell
Invoke-RestMethod "http://127.0.0.1:9000/api/events/$eventId"
```

成功标志：

```text
data.representative_posts 存在
data.risk_reasons 存在
data.concerns 存在
data.source_keywords 存在
```

## 10. 第七步：前端联调

当前前端已经有：

```text
frontend/src/api/events.js
frontend/src/views/EventListView.vue
frontend/src/views/EventDetailView.vue
frontend/src/views/OpinionView.vue
frontend/src/auth/session.js
```

目前前端公共用户侧主要消费：

```text
GET /api/events
GET /api/events/{event_id}
```

这符合“普通用户只能看 published”的规则。

### 10.1 前端普通用户侧验收

启动后端后，启动前端：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-ai-agent_v3\campus-ai-agent-main\frontend"
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

验收点：

- `/opinion` 或事件相关页面能显示已发布事件。
- F12 Network 中 `/api/events` 返回真实 JSON。
- 页面不要使用 mock 数据。
- 事件详情能看到代表性帖子、风险等级、摘要和来源。

### 10.2 后台侧还需要补的前端能力

后端已经有：

```text
POST /api/agent/public/analyze
GET /api/admin/events
PATCH /api/admin/events/{event_id}/status
```

但前端如果还没有后台事件审核页面，下一步应补：

```text
管理员后台页面
-> 运行公共舆情 Agent 按钮
-> draft 事件列表
-> 发布/驳回/归档按钮
-> 查看代表性帖子
-> 查看审核日志
```

建议前端新增 API 模块：

```text
frontend/src/api/adminEvents.js
```

建议函数：

```javascript
import http from './http'

export function runPublicOpinionAgent(payload) {
  return http.post('/agent/public/analyze', payload)
}

export function fetchAdminEvents(params = {}) {
  return http.get('/admin/events', { params })
}

export function updateEventStatus(eventId, payload) {
  return http.patch(`/admin/events/${eventId}/status`, payload)
}

export function fetchEventReviewLogs(eventId, params = {}) {
  return http.get(`/admin/events/${eventId}/review-logs`, { params })
}
```

注意：

```text
这些接口都需要管理员 token。
前端 http.js 已经会自动从 session 注入 Authorization Bearer token。
```

## 11. 第八步：确定后续开发的唯一源

现在最容易出问题的是两个项目同时存在 Agent 核心代码。

建议定一个规则：

```text
主项目 backend/agent/public_opinion_core 是运行源。
Agent 子项目 campus-opinion-agent 是算法参考和回归测试源。
```

后续如果要改 Agent 规则，有两种流程，二选一。

### 11.1 推荐流程 A：先改主项目，再同步回子项目

适合当前阶段，因为主项目已经完成后端接入。

流程：

```text
修改主项目 backend/agent/public_opinion_core
-> 跑主项目 check_wp5/check_wp10
-> 再同步回 campus-opinion-agent
-> 跑 Agent 子项目 unittest 和 CLI
```

### 11.2 流程 B：先改 Agent 子项目，再同步到主项目

适合后续算法负责人独立迭代。

流程：

```text
修改 campus-opinion-agent/backend/app/public_opinion_core
-> 跑 Agent 子项目 unittest 和 CLI
-> 复制 public_opinion_core 到主项目
-> 跑哈希核对
-> 跑主项目 check_wp5/check_wp10
```

不管选哪种，都必须做：

```text
哈希核对
Agent 子项目测试
主项目 WP5/WP10 验收
```

## 12. 第九步：大模型能力的接入顺序

你之前提到后续希望通过 API Key 调用大模型。建议不要现在就替换规则型 Agent。

推荐顺序：

```text
第一阶段：规则型 Agent 入库和审核闭环稳定
第二阶段：API Key 连通性测试
第三阶段：大模型只增强 summary/agent_summary/risk_reasons
第四阶段：管理员审核页面展示“大模型建议”
第五阶段：再考虑让大模型参与聚类或风险判断
```

Agent 子项目已经有 API Key smoke test：

```text
D:\桌面文件\软件工程大作业\campus-opinion-agent\backend\scripts\test_llm_api.py
```

测试命令：

```powershell
cd "D:\桌面文件\软件工程大作业\campus-opinion-agent\backend"
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts\test_llm_api.py
```

成功后，再考虑在主项目新增：

```text
backend/agent/public_opinion_core/llm_enhancer.py
```

但这不应阻塞当前主项目接入验收。

## 13. 最终接入验收清单

完成以下全部项目后，才能认为“Agent 子项目已经真正接入主项目”：

- [ ] 主项目 `backend/agent/public_opinion_core` 与 Agent 子项目核心文件一致，或差异有明确记录。
- [ ] 主项目能 import `PublicOpinionAgentService`。
- [ ] `raw_posts > 0`。
- [ ] `processed_posts > 0`。
- [ ] `scripts/generate_public_events.py --preview` 能生成事件。
- [ ] `scripts/generate_public_events.py` 能写入 `public_events`。
- [ ] `event_post_links` 能关联代表性帖子。
- [ ] `agent_run_logs` 能记录 Agent 运行。
- [ ] `POST /api/agent/public/analyze` 管理员 token 下可用。
- [ ] `GET /api/admin/events?status=all` 能看到所有状态事件。
- [ ] `PATCH /api/admin/events/{id}/status` 能发布事件。
- [ ] `event_review_logs` 和 `admin_operation_logs` 有记录。
- [ ] `GET /api/events` 只返回 `published`。
- [ ] 前端普通用户页面能显示 published 事件。
- [ ] 管理员后台能触发分析并审核事件，或者至少能通过接口完成同样流程。
- [ ] `scripts\smoke_backend.ps1` 能通过。

## 14. 建议下一步实际执行顺序

按优先级执行：

1. 在主项目跑哈希核对，确认 Agent 核心未分叉。
2. 跑 Agent 子项目 unittest 和 CLI，确认算法包本身可用。
3. 在主项目跑 `check_wp4.py`，确认真实数据链路可用。
4. 在主项目跑 `generate_public_events.py --preview`，确认真实 `processed_posts` 能生成事件。
5. 在主项目跑 `generate_public_events.py`，确认事件可入库。
6. 启动后端，手工调用 `/api/agent/public/analyze`。
7. 手工通过 `/api/admin/events/{id}/status` 发布事件。
8. 手工访问 `/api/events` 和 `/api/events/{id}`。
9. 启动前端，确认普通用户页面看到真实 published 事件。
10. 如果前端没有后台审核页，安排前端负责人补“运行 Agent + 事件审核”页面。
11. 最后跑 `smoke_backend.ps1` 做总验收。

## 15. 最终汇报模板

可以这样向组内说明当前阶段：

```text
公共舆情 Agent 子项目已经完成 Week2 独立开发包，主项目后端也已完成 Week2 后端工作包。
目前 Agent 核心已经迁入主项目 backend/agent/public_opinion_core，且与子项目核心文件哈希一致。
主项目已经具备 processed_posts -> Agent -> public_events/event_post_links/agent_run_logs -> 管理员审核 -> published 事件展示的后端链路。

下一阶段重点不是继续写 Agent 核心，而是做主项目真实数据验收、接口验收、前端普通用户展示联调、管理员后台触发和审核页面联调。
后续如接入大模型，应作为规则型 Agent 之后的增强层，不影响当前入库和审核闭环。
```
